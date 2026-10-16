import os
import time
from collections import defaultdict

import psycopg2


SCHEMA_MAPPING = {
    "product_id": "drug_products.drug_id",
    "folder_name": "drug_products.folder_name",
    "name_en": "drug_products.drug_name_en/normalized_name_en",
    "name_zh": "drug_products.drug_name_zh/normalized_name_zh",
    "strength": "drug_products.strength_normalized",
    "dosage_form": "drug_products.dosage_form_en/dosage_form_zh/dosage_form_code",
    "release_type": "drug_products.release_type",
    "license": "drug_products.license_kind/license_number",
    "manufacturer": "drug_products.manufacturer_en/manufacturer_zh",
    "aliases": "drug_aliases.drug_id -> drug_products.drug_id",
    "barcodes": "drug_barcodes.drug_id -> drug_products.drug_id",
    "ingredients": "drug_ingredients.drug_id -> drug_products.drug_id",
}


class DrugRepository:
    def __init__(self, config=None):
        self.config = config or {
            "host": os.getenv("PGHOST", "localhost"),
            "port": os.getenv("PGPORT", "5432"),
            "dbname": os.getenv("PGDATABASE", "medicine_ocr"),
            "user": os.getenv("PGUSER", "postgres"),
            "password": os.environ["PGPASSWORD"],
        }
        started = time.perf_counter_ns()
        self.conn = psycopg2.connect(**self.config)
        try:
            self.conn.set_session(readonly=True, autocommit=True)
            self.database_connect_time_ms = (time.perf_counter_ns() - started) / 1e6
            self.weights = self._load_weights()
            self.alias_maps = self._load_alias_maps()
        except Exception:
            self.conn.close()
            raise

    def close(self):
        self.conn.close()

    def _load_weights(self):
        expected = {"drug_name", "ingredient", "strength", "manufacturer", "dosage_form"}
        with self.conn.cursor() as cur:
            cur.execute("SELECT field_name, weight FROM public.matching_weights ORDER BY field_name")
            weights = {name: float(weight) for name, weight in cur.fetchall()}
        if set(weights) != expected or abs(sum(weights.values()) - 100.0) > 1e-6:
            raise RuntimeError(f"invalid matching_weights: {weights}")
        return weights

    def _load_alias_maps(self):
        maps = {"ingredient": {}, "dosage_form": {}, "manufacturer": {}, "normalization": {}}
        with self.conn.cursor() as cur:
            cur.execute("SELECT normalized_alias, canonical FROM public.ingredient_aliases ORDER BY alias_id")
            maps["ingredient"] = {alias: canonical for alias, canonical in cur.fetchall()}
            cur.execute("SELECT normalized_alias, canonical_en, canonical_zh, dosage_form_code, release_type FROM public.dosage_form_aliases ORDER BY alias_id")
            maps["dosage_form"] = {alias: (en, zh, code, release) for alias, en, zh, code, release in cur.fetchall()}
            cur.execute("SELECT normalized_alias, canonical FROM public.manufacturer_aliases ORDER BY alias_id")
            maps["manufacturer"] = {alias: canonical for alias, canonical in cur.fetchall()}
            cur.execute("SELECT field_name, normalized_alias, canonical FROM public.normalization_aliases ORDER BY alias_id")
            maps["normalization"] = {(field, alias): canonical for field, alias, canonical in cur.fetchall()}
        return maps

    def fetch_candidates(self):
        started = time.perf_counter_ns()
        with self.conn.cursor() as cur:
            cur.execute("""SELECT drug_id, folder_name, drug_name_en, drug_name_zh,
                normalized_name_en, normalized_name_zh, strength_normalized,
                dosage_form_en, dosage_form_zh, dosage_form_code, release_type,
                license_kind, license_number, manufacturer_en, manufacturer_zh
                FROM public.drug_products ORDER BY drug_id""")
            columns = [d.name for d in cur.description]
            products = [dict(zip(columns, row)) for row in cur.fetchall()]
            ids = [p["drug_id"] for p in products]
            cur.execute("SELECT drug_id, alias, normalized_alias, language_code, alias_type FROM public.drug_aliases WHERE drug_id = ANY(%s)", (ids,))
            aliases = defaultdict(list)
            for drug_id, alias, normalized, language, kind in cur.fetchall():
                aliases[drug_id].append((alias, normalized, language, kind))
            cur.execute("SELECT drug_id, barcode, barcode_type FROM public.drug_barcodes WHERE drug_id = ANY(%s)", (ids,))
            barcodes = defaultdict(list)
            for drug_id, barcode, kind in cur.fetchall(): barcodes[drug_id].append((barcode, kind))
            cur.execute("SELECT drug_id, ingredient_normalized, language_code FROM public.drug_ingredients WHERE drug_id = ANY(%s) ORDER BY drug_id, ingredient_order", (ids,))
            ingredients = defaultdict(list)
            for drug_id, ingredient, language in cur.fetchall(): ingredients[drug_id].append((ingredient, language))
        for product in products:
            drug_id = product["drug_id"]
            product["aliases"] = aliases[drug_id]
            product["barcodes"] = barcodes[drug_id]
            product["ingredients"] = ingredients[drug_id]
        return products, (time.perf_counter_ns() - started) / 1e6

    def lookup_exact_identifiers(self, barcodes, licenses):
        """Return exact identifier hits using parameterized, read-only SQL."""
        started = time.perf_counter_ns()
        barcode_hits = defaultdict(set)
        license_hits = defaultdict(set)
        clean_barcodes = sorted({str(value).strip() for value in barcodes if str(value).strip()})
        clean_licenses = sorted({(str(item["kind"]), str(item["number"])) for item in licenses})
        with self.conn.cursor() as cur:
            if clean_barcodes:
                cur.execute(
                    "SELECT btrim(barcode), drug_id FROM public.drug_barcodes WHERE btrim(barcode) = ANY(%s)",
                    (clean_barcodes,),
                )
                for barcode, drug_id in cur.fetchall():
                    barcode_hits[str(barcode)].add(drug_id)
            for kind, number in clean_licenses:
                cur.execute(
                    """SELECT drug_id FROM public.drug_products
                       WHERE license_number = %s
                         AND license_kind IS NOT NULL
                         AND license_kind = %s""",
                    (number, kind),
                )
                for (drug_id,) in cur.fetchall():
                    license_hits[(kind, number)].add(drug_id)
        return {
            "barcodes": dict(barcode_hits),
            "licenses": dict(license_hits),
        }, (time.perf_counter_ns() - started) / 1e6
