from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg2
from psycopg2.extras import Json, RealDictCursor


def connect():
    return psycopg2.connect(
        host=os.environ["PGHOST"], port=os.getenv("PGPORT", "5432"),
        dbname=os.environ["PGDATABASE"], user=os.environ["PGUSER"], password=os.environ["PGPASSWORD"],
        connect_timeout=5, application_name="medic-ocr-api",
    )


def ping() -> bool:
    with connect() as connection, connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        return cursor.fetchone()[0] == 1


def resolve_expected(expected_drug_id: int | None, expected_name: str | None) -> tuple[int | None, str | None]:
    if expected_drug_id is None:
        return None, expected_name.strip() if expected_name else None
    with connect() as connection, connection.cursor() as cursor:
        cursor.execute("SELECT folder_name FROM public.drug_products WHERE drug_id = %s", (expected_drug_id,))
        row = cursor.fetchone()
    if not row:
        raise ValueError(f"Unknown expected_drug_id: {expected_drug_id}")
    return expected_drug_id, str(row[0])


def create_job(verification_id: UUID, expected_drug_id: int | None, expected_name: str | None, images: list[dict[str, Any]]) -> None:
    with connect() as connection, connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO public.verification_jobs (verification_id,status,expected_drug_id,expected_name) VALUES (%s,'PROCESSING',%s,%s)",
            (str(verification_id), expected_drug_id, expected_name),
        )
        for image in images:
            cursor.execute(
                """INSERT INTO public.verification_images
                   (verification_id,side,original_filename,content_type,byte_size,sha256,storage_path)
                   VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                (str(verification_id), image["side"], image["original_filename"], image["content_type"],
                 image["byte_size"], image["sha256"], image["storage_path"]),
            )


def complete_job(verification_id: UUID, outcome: str, fused: dict[str, Any], ocr_result: dict[str, Any], yolo_result: dict[str, Any], result_file: Path) -> None:
    with connect() as connection, connection.cursor() as cursor:
        cursor.execute(
            """UPDATE public.verification_jobs SET status='COMPLETED',outcome=%s,final_prediction=%s,
               final_confidence=%s,decision_source=%s,decision_reason=%s,completed_at=now()
               WHERE verification_id=%s""",
            (outcome, fused.get("final_prediction"), fused.get("final_confidence"), fused.get("decision_source"),
             fused.get("decision_reason"), str(verification_id)),
        )
        cursor.execute(
            """INSERT INTO public.verification_results
               (verification_id,ocr_result,yolo_result,fused_result,result_file) VALUES (%s,%s,%s,%s,%s)""",
            (str(verification_id), Json(ocr_result), Json(yolo_result), Json(fused), str(result_file)),
        )


def fail_job(verification_id: UUID, message: str) -> None:
    with connect() as connection, connection.cursor() as cursor:
        cursor.execute(
            "UPDATE public.verification_jobs SET status='FAILED',error_message=%s,completed_at=now() WHERE verification_id=%s",
            (message[:4000], str(verification_id)),
        )


def list_jobs(limit: int, offset: int) -> list[dict[str, Any]]:
    with connect() as connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(
            """SELECT verification_id,status,outcome,expected_drug_id,expected_name,final_prediction,
               final_confidence,decision_source,created_at,completed_at FROM public.verification_jobs
               ORDER BY created_at DESC LIMIT %s OFFSET %s""", (limit, offset),
        )
        return [dict(row) for row in cursor.fetchall()]


def get_job(verification_id: UUID) -> dict[str, Any] | None:
    with connect() as connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute("SELECT * FROM public.verification_jobs WHERE verification_id=%s", (str(verification_id),))
        job = cursor.fetchone()
        if not job:
            return None
        cursor.execute(
            "SELECT side,original_filename,content_type,byte_size,sha256,storage_path FROM public.verification_images WHERE verification_id=%s ORDER BY side",
            (str(verification_id),),
        )
        images = [dict(row) for row in cursor.fetchall()]
        cursor.execute("SELECT ocr_result,yolo_result,fused_result,result_file FROM public.verification_results WHERE verification_id=%s", (str(verification_id),))
        result = cursor.fetchone()
    return {**dict(job), "images": images, "result": dict(result) if result else None}


def result_document(verification_id: UUID, payload: dict[str, Any]) -> Path:
    root = Path(os.getenv("RESULT_ROOT", "/data/results"))
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{verification_id}.json"
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    temporary.replace(target)
    return target
