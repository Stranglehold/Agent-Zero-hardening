"""
JSON Connector — Agent-Zero Ontology Layer
==========================================
Reads JSON/JSONL files and maps keys to entity properties.
Supports nested objects via simple dotpath notation.

Stdlib only: json, os, datetime, re.
"""

import json
import os
import re
from datetime import datetime, timezone

ONTOLOGY_DIR = "/a0/usr/ontology"
CONFIG_PATH = os.path.join(ONTOLOGY_DIR, "ontology_config.json")
INGESTION_QUEUE = os.path.join(ONTOLOGY_DIR, "ingestion_queue.jsonl")

# Default key → entity property mapping
DEFAULT_KEY_MAP = {
    "name": ["name", "full_name", "entity_name", "company_name", "org_name",
              "person_name", "title"],
    "description": ["description", "summary", "bio", "about"],
    "date": ["date", "filing_date", "date_of_birth", "start_date", "effective_date"],
    "address": ["address", "location", "street", "city"],
    "amount": ["amount", "value", "total", "contribution"],
    "type": ["type", "category", "entity_type", "org_type"],
    "jurisdiction": ["jurisdiction", "country", "state", "incorporation_state"],
}


def load_config() -> dict:
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def ingest_json(
    file_path: str,
    source_id: str,
    entity_type: str = None,
    key_map: dict = None,
    records_path: str = None,
    max_records: int = 500,
    force_reingest: bool = False,
) -> dict:
    """Read a JSON or JSONL file and extract CandidateEntity dicts.

    records_path: dotpath to array of records in JSON (e.g. "data.items").
                  If None, treat file as JSONL or top-level array.
    key_map: dict mapping property names to lists of source keys to try.

    Returns: {"candidates": [...], "skipped": int, "errors": int}
    """
    print(f"[ONT-INGEST] json_connector: reading {file_path} as source_id={source_id}", flush=True)

    if key_map is None:
        key_map = DEFAULT_KEY_MAP

    config = load_config()
    max_records = min(max_records, config.get('source_connectors', {}).get('max_batch_size', 500))

    candidates = []
    skipped = 0
    errors = 0

    if not os.path.isfile(file_path):
        print(f"[ONT-INGEST] File not found: {file_path}", flush=True)
        return {"candidates": [], "skipped": 0, "errors": 1}

    ingested_ids = set() if force_reingest else _load_ingested_ids(source_id)

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read().strip()

        # Try JSONL first (line-delimited JSON)
        records = []
        if '\n' in content and not content.startswith('['):
            for line_num, line in enumerate(content.splitlines(), 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append((f"line_{line_num}", json.loads(line)))
                except json.JSONDecodeError:
                    errors += 1
        else:
            # Standard JSON
            try:
                data = json.loads(content)
            except json.JSONDecodeError as e:
                print(f"[ONT-INGEST] JSON parse error: {e}", flush=True)
                return {"candidates": [], "skipped": 0, "errors": 1}

            # Navigate to records path
            if records_path:
                data = _get_nested(data, records_path)

            if isinstance(data, list):
                records = [(f"item_{i}", item) for i, item in enumerate(data)]
            elif isinstance(data, dict):
                records = [("root", data)]
            else:
                return {"candidates": [], "skipped": 0, "errors": 1}

        for record_id, record in records[:max_records]:
            full_record_id = f"{source_id}:{record_id}"
            if full_record_id in ingested_ids:
                skipped += 1
                continue

            try:
                if not isinstance(record, dict):
                    errors += 1
                    continue

                props = _map_record(record, key_map)
                if not props.get('name'):
                    errors += 1
                    continue

                etype = entity_type or _infer_type(record, props)
                rels = _extract_relationships(record)

                candidates.append({
                    "entity_type": etype,
                    "properties": props,
                    "relationships": rels,
                    "provenance": {
                        "source_id": source_id,
                        "source_type": "json",
                        "record_id": record_id,
                        "ingested_at": datetime.now(timezone.utc).isoformat(),
                        "confidence": 1.0,
                    },
                })
            except Exception as e:
                print(f"[ONT-INGEST] Record {record_id} error: {e}", flush=True)
                errors += 1

    except Exception as e:
        print(f"[ONT-INGEST] JSON read error: {e}", flush=True)
        errors += 1

    print(f"[ONT-INGEST] JSON result: {len(candidates)} candidates, {skipped} skipped, {errors} errors", flush=True)

    if candidates:
        _append_to_queue(candidates)

    return {"candidates": candidates, "skipped": skipped, "errors": errors}


def _get_nested(data, dotpath: str):
    """Navigate nested dict/list by dotpath like 'data.items'."""
    parts = dotpath.split('.')
    current = data
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit():
            idx = int(part)
            current = current[idx] if idx < len(current) else None
        else:
            return None
        if current is None:
            return None
    return current


def _map_record(record: dict, key_map: dict) -> dict:
    """Map JSON record keys to entity property names."""
    props = {}

    def get_val(keys):
        for key in keys:
            # Direct lookup
            if key in record:
                return record[key]
            # Case-insensitive
            for k, v in record.items():
                if k.lower() == key.lower() and v is not None:
                    return v
        return None

    for prop_name, source_keys in key_map.items():
        val = get_val(source_keys)
        if val is not None:
            if isinstance(val, (dict, list)):
                props[prop_name] = val
            else:
                props[prop_name] = str(val).strip()

    # Identifiers: look for known identifier keys
    identifiers = {}
    id_keys = ['ein', 'duns', 'ticker', 'lei', 'registration_number',
                'isin', 'cusip', 'fec_id', 'lobbyist_id', 'contract_id']
    for key in id_keys:
        val = record.get(key) or record.get(key.upper())
        if val:
            identifiers[key] = str(val).strip()

    # Also check 'identifiers' sub-object
    if isinstance(record.get('identifiers'), dict):
        identifiers.update(record['identifiers'])

    if identifiers:
        props['identifiers'] = identifiers

    # Include remaining scalar fields as raw properties
    for key, val in record.items():
        k_clean = re.sub(r'\s+', '_', str(key).lower().strip())
        if k_clean not in props and isinstance(val, (str, int, float)):
            props[k_clean] = str(val).strip()

    return props


def _infer_type(record: dict, props: dict) -> str:
    """Infer entity type from record structure."""
    keys_lower = " ".join(k.lower() for k in record.keys())
    if any(kw in keys_lower for kw in ('company', 'org', 'corporation', 'employer')):
        return 'organization'
    if any(kw in keys_lower for kw in ('dob', 'date_of_birth', 'first_name', 'ssn')):
        return 'person'
    if any(kw in keys_lower for kw in ('amount', 'isin', 'cusip', 'ticker')):
        return 'financial_instrument'
    return 'entity'


def _extract_relationships(record: dict) -> list:
    """Extract explicit relationship hints from JSON record."""
    rels = []

    # Common relationship fields
    rel_fields = {
        'employer': 'employs',
        'company': 'employs',
        'organization': 'employs',
        'parent_company': 'owns',
        'subsidiary': 'owns',
        'location': 'located_at',
        'address': 'located_at',
    }

    for field, rel_type in rel_fields.items():
        val = record.get(field)
        if val and isinstance(val, str) and val.strip():
            rels.append({
                "type": rel_type,
                "target_hint": val.strip(),
            })

    # Explicit relationships array
    if isinstance(record.get('relationships'), list):
        for rel in record['relationships']:
            if isinstance(rel, dict) and rel.get('type') and rel.get('target'):
                rels.append({
                    "type": rel['type'],
                    "target_hint": str(rel['target']),
                })

    return rels


def _load_ingested_ids(source_id: str) -> set:
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
    os.makedirs(ONTOLOGY_DIR, exist_ok=True)
    with open(INGESTION_QUEUE, 'a', encoding='utf-8') as f:
        for cand in candidates:
            f.write(json.dumps(cand) + '\n')
