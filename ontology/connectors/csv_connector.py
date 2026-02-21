"""
CSV Connector — Agent-Zero Ontology Layer
==========================================
Ingests CSV/TSV files, maps columns to entity properties using default_mappings
from ontology_config.json, and writes CandidateEntity dicts to ingestion queue.

Stdlib only: csv, json, os, datetime, re.
"""

import csv
import json
import os
import re
from datetime import datetime, timezone

ONTOLOGY_DIR = "/a0/usr/ontology"
CONFIG_PATH = os.path.join(ONTOLOGY_DIR, "ontology_config.json")
INGESTION_QUEUE = os.path.join(ONTOLOGY_DIR, "ingestion_queue.jsonl")

DEFAULT_MAPPINGS = {
    "name_columns": ["name", "full_name", "entity_name", "company_name", "org_name",
                     "person_name", "organization_name"],
    "date_columns": ["date", "filing_date", "effective_date", "start_date", "dob",
                     "date_of_birth"],
    "amount_columns": ["amount", "value", "total", "contribution", "sum"],
    "address_columns": ["address", "location", "city", "state", "street"],
    "org_columns": ["company", "employer", "organization", "org", "employer_name"],
    "identifier_columns": ["ein", "duns", "ticker", "registration_number", "id",
                            "fec_id", "lobbyist_id"],
}


def load_config() -> dict:
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def ingest_csv(
    file_path: str,
    source_id: str,
    entity_type: str = None,
    delimiter: str = None,
    max_rows: int = 500,
    force_reingest: bool = False,
) -> dict:
    """Read a CSV/TSV file and extract CandidateEntity dicts.

    Returns: {"candidates": [...], "skipped": int, "errors": int}
    """
    print(f"[ONT-INGEST] csv_connector: reading {file_path} as source_id={source_id}", flush=True)

    config = load_config()
    mappings = config.get('source_connectors', {}).get('default_mappings', {}).get('csv', DEFAULT_MAPPINGS)
    max_rows = min(max_rows, config.get('source_connectors', {}).get('max_batch_size', 500))

    candidates = []
    skipped = 0
    errors = 0

    if not os.path.isfile(file_path):
        print(f"[ONT-INGEST] File not found: {file_path}", flush=True)
        return {"candidates": [], "skipped": 0, "errors": 1}

    # Load already-ingested record IDs to skip duplicates
    ingested_ids = set()
    if not force_reingest:
        ingested_ids = _load_ingested_ids(source_id)

    try:
        with open(file_path, 'r', encoding='utf-8-sig', newline='') as f:
            # Auto-detect delimiter if not specified
            if delimiter is None:
                sample = f.read(2048)
                f.seek(0)
                sniffer = csv.Sniffer()
                try:
                    dialect = sniffer.sniff(sample, delimiters=',\t|;')
                    delimiter = dialect.delimiter
                except Exception:
                    delimiter = ','

            reader = csv.DictReader(f, delimiter=delimiter)

            if reader.fieldnames is None:
                # No header — use positional mapping
                f.seek(0)
                reader = csv.reader(f, delimiter=delimiter)
                rows = list(reader)
                for row_num, row in enumerate(rows[:max_rows], 1):
                    record_id = f"{source_id}:row_{row_num}"
                    if record_id in ingested_ids:
                        skipped += 1
                        continue
                    if row:
                        props = {"name": row[0]} if row else {}
                        for i, val in enumerate(row[1:], 1):
                            props[f"field_{i}"] = val
                        candidates.append(_make_candidate(
                            props, entity_type or "entity", source_id,
                            record_id, confidence=0.5,
                        ))
                return {"candidates": candidates, "skipped": skipped, "errors": errors}

            headers_lower = {h.lower().strip(): h for h in (reader.fieldnames or [])}

            for row_num, row in enumerate(reader, 1):
                if len(candidates) >= max_rows:
                    break

                record_id = f"row_{row_num}"
                full_record_id = f"{source_id}:{record_id}"

                if full_record_id in ingested_ids:
                    skipped += 1
                    continue

                try:
                    props = _map_row_to_properties(row, headers_lower, mappings)

                    if not props.get('name'):
                        # Try to find any name-like value
                        for h, v in row.items():
                            if v and h:
                                props['name'] = str(v).strip()
                                break

                    if not props.get('name'):
                        errors += 1
                        continue

                    # Determine entity type from data if not specified
                    etype = entity_type or _infer_entity_type(props, row)

                    candidates.append(_make_candidate(
                        props, etype, source_id, record_id, confidence=1.0,
                    ))
                except Exception as e:
                    print(f"[ONT-INGEST] Row {row_num} error: {e}", flush=True)
                    errors += 1

    except Exception as e:
        print(f"[ONT-INGEST] CSV read error: {e}", flush=True)
        errors += 1

    print(f"[ONT-INGEST] CSV result: {len(candidates)} candidates, {skipped} skipped, {errors} errors", flush=True)

    # Write to queue
    if candidates:
        _append_to_queue(candidates)

    return {"candidates": candidates, "skipped": skipped, "errors": errors}


def _map_row_to_properties(row: dict, headers_lower: dict, mappings: dict) -> dict:
    """Map CSV row columns to entity property dict."""
    props = {}

    def get_col(col_names):
        for col in col_names:
            col_l = col.lower()
            if col_l in headers_lower:
                orig_header = headers_lower[col_l]
                val = row.get(orig_header, '').strip()
                if val:
                    return val
        return ''

    # Name
    name = get_col(mappings.get('name_columns', DEFAULT_MAPPINGS['name_columns']))
    if name:
        props['name'] = name

    # Date
    date = get_col(mappings.get('date_columns', DEFAULT_MAPPINGS['date_columns']))
    if date:
        props['date'] = date

    # Amount
    amount = get_col(mappings.get('amount_columns', DEFAULT_MAPPINGS['amount_columns']))
    if amount:
        props['amount'] = amount

    # Address
    address = get_col(mappings.get('address_columns', DEFAULT_MAPPINGS['address_columns']))
    if address:
        props['address'] = address

    # Organization affiliation
    org = get_col(mappings.get('org_columns', DEFAULT_MAPPINGS.get('org_columns', [])))
    if org:
        props['organization'] = org

    # Identifiers
    identifiers = {}
    for id_col in mappings.get('identifier_columns', DEFAULT_MAPPINGS.get('identifier_columns', [])):
        id_col_l = id_col.lower()
        if id_col_l in headers_lower:
            val = row.get(headers_lower[id_col_l], '').strip()
            if val:
                identifiers[id_col_l] = val
    if identifiers:
        props['identifiers'] = identifiers

    # Include all remaining non-empty columns as raw properties
    for header, val in row.items():
        if val and val.strip():
            h_key = re.sub(r'\s+', '_', header.lower().strip())
            if h_key not in props:
                props[h_key] = val.strip()

    return props


def _infer_entity_type(props: dict, row: dict) -> str:
    """Heuristically infer entity type from property names."""
    row_keys = " ".join(k.lower() for k in row.keys())
    if any(kw in row_keys for kw in ('company', 'org', 'corporation', 'inc', 'llc', 'employer')):
        return 'organization'
    if any(kw in row_keys for kw in ('dob', 'date_of_birth', 'first_name', 'last_name', 'ssn')):
        return 'person'
    if any(kw in row_keys for kw in ('amount', 'contribution', 'contract_value')):
        return 'financial_instrument'
    return 'entity'


def _make_candidate(
    properties: dict, entity_type: str, source_id: str,
    record_id: str, confidence: float = 1.0,
) -> dict:
    return {
        "entity_type": entity_type,
        "properties": properties,
        "relationships": [],
        "provenance": {
            "source_id": source_id,
            "source_type": "csv",
            "record_id": record_id,
            "ingested_at": datetime.now(timezone.utc).isoformat(),
            "confidence": confidence,
        },
    }


def _load_ingested_ids(source_id: str) -> set:
    """Load set of already-ingested record IDs for this source."""
    if not os.path.isfile(INGESTION_QUEUE):
        return set()
    ids = set()
    try:
        with open(INGESTION_QUEUE, 'r', encoding='utf-8') as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                try:
                    cand = json.loads(s)
                    prov = cand.get('provenance', {})
                    if prov.get('source_id') == source_id:
                        ids.add(f"{source_id}:{prov.get('record_id', '')}")
                except json.JSONDecodeError:
                    pass
    except OSError:
        pass
    return ids


def _append_to_queue(candidates: list):
    """Append candidates to ingestion queue JSONL."""
    os.makedirs(ONTOLOGY_DIR, exist_ok=True)
    with open(INGESTION_QUEUE, 'a', encoding='utf-8') as f:
        for cand in candidates:
            f.write(json.dumps(cand) + '\n')
