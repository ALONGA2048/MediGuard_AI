"""Strict identifier provenance and exact-value normalization.

No OCR digit inference, substring matching, check-digit repair or nearest ID.
ZXing's HRI representation (including GS1 AIs) is preserved verbatim.
"""
import re


def normalize_barcode(value):
    return str(value or '').strip()


def canonical_format(value):
    return re.sub(r'[^A-Z0-9]', '', str(value).upper())


def valid_barcode_value(value, format_name):
    value = normalize_barcode(value)
    fmt = canonical_format(format_name)
    if not value or fmt in ('', 'UNKNOWN', 'NONE'):
        return False
    lengths = {'EAN13': 13, 'EAN8': 8, 'UPCA': 12}
    if fmt in lengths:
        if not re.fullmatch(r'[0-9]{%d}' % lengths[fmt], value):
            return False
        total = sum(int(digit) * (3 if i % 2 == 0 else 1)
                    for i, digit in enumerate(reversed(value[:-1])))
        return (10 - total % 10) % 10 == int(value[-1])
    # Other supported formats rely on ZXing's valid flag and built-in checks.
    return fmt in {'CODE128', 'CODE39', 'CODE93', 'CODABAR', 'ITF', 'UPCE',
                   'QRCODE', 'MICROQRCODE', 'RMQRCODE', 'DATAMATRIX', 'AZTEC',
                   'PDF417', 'MICROPDF417', 'MAXICODE', 'DATABAR', 'DATABAROMNI',
                   'DATABARLIMITED', 'DATABARSTACKED', 'DATABAREXPANDED',
                   'DATABAREXPANDEDSTACKED', 'DATABARSTACKEDOMNI', 'DXFILMEDGE'}


def decoded_evidence(items):
    """Only the decoder provenance contract may enter the matching boundary."""
    unique = {}
    for item in items or []:
        if not isinstance(item, dict):
            continue
        if (item.get('source') != 'BARCODE_DECODED'
                or item.get('decoder') != 'zxingcpp'
                or item.get('decode_success') is not True):
            continue
        raw = item.get('raw_value', item.get('value', item.get('text', '')))
        value = normalize_barcode(raw)
        if not valid_barcode_value(value, item.get('format', '')):
            continue
        if item.get('normalized_value', value) != value:
            continue
        if value not in unique:
            unique[value] = {**item, 'raw_value': raw, 'value': value,
                             'text': value, 'normalized_value': value}
    return list(unique.values())


def identifier_statistics(result):
    """Group-level flags; barcode/license counts can overlap in the same group."""
    sources = result.get('identifier_sources', [])
    barcode = [s for s in sources if s.get('source') == 'BARCODE_DECODED']
    license_items = [s for s in sources if s.get('source') == 'LICENSE_OCR']
    candidates = [c for p in result.get('photos', []) if p
                  for c in p.get('barcode_diagnostics', {}).get('barcode_candidates', [])]
    has_decoded = bool(barcode) or any(decoded_evidence(p.get('barcode_details', []))
                                      for p in result.get('photos', []) if p)
    success = result.get('status') in {'MATCHED', 'EXACT_ID', 'NAME_ONLY_UNIQUE'}
    return {
        'barcode_decoded_count': int(has_decoded),
        'barcode_exact_match_count': int(any(s.get('status') == 'BARCODE_EXACT_MATCH' for s in barcode)),
        'license_exact_match_count': int(any(s.get('status') == 'LICENSE_EXACT_MATCH' for s in license_items)),
        'barcode_decoded_db_not_found_count': int(any(s.get('status') == 'BARCODE_DECODED_DB_NOT_FOUND' for s in barcode)),
        'barcode_ambiguous_count': int(any(s.get('status') == 'BARCODE_AMBIGUOUS' for s in barcode)),
        # No-code pictures are not failed barcodes. Count attempted ROIs with no decode.
        'barcode_decode_failure_count': int(bool(candidates) and not has_decoded
                                           and any(c.get('decode_attempted') for c in candidates)),
        'barcode_no_decode_count': int(not has_decoded),
        'ocr_text_match_count': int(success and result.get('identifier_source') == 'PACKAGE_TEXT_OCR'
                                    and result.get('identification_method') != 'OCR_DISAMBIGUATED_IDENTIFIER'),
        'ocr_identifier_disambiguated_count': int(success and result.get('identification_method') == 'OCR_DISAMBIGUATED_IDENTIFIER'),
    }


def attach_database_results(photos, matched):
    by_value = {s['value']: s for s in matched.get('identifier_sources', [])
                if s.get('source') == 'BARCODE_DECODED'}
    for photo in photos:
        if not photo:
            continue
        diagnostics = photo.get('barcode_diagnostics', {})
        matches = []
        for item in photo.get('barcode_details', []):
            record = by_value.get(item.get('normalized_value'))
            if record:
                item['database_match'] = record['database_match']
                matches.append(dict(record))
        diagnostics['barcode_database_matches'] = matches
        photo['barcode_database_matches'] = matches
