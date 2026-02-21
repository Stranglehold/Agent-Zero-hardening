"""
Relationship Extractor — Agent-Zero Ontology Layer
===================================================
Discovers relationships between resolved entities using 5 methods:
  1. Co-occurrence: entities in same source record → co_mentioned
  2. Property-based: shared address → co_located, shared org → affiliated
  3. Temporal proximity: events involving same entities within time window
  4. Graph-based: promote Layer 10b memory links to typed relationships
  5. Confidence scoring: explicit=1.0, co-occur(3+src)=0.8, co-occur(1-2)=0.5,
                         property=0.6, temporal=0.4

Stdlib only: json, os, datetime, collections, re.
"""

import json
import os
import re
from collections import defaultdict
from datetime import datetime, timezone

ONTOLOGY_DIR = "/a0/usr/ontology"
CONFIG_PATH = os.path.join(ONTOLOGY_DIR, "ontology_config.json")
RELATIONSHIPS_FILE = os.path.join(ONTOLOGY_DIR, "relationships.jsonl")
CO_RETRIEVAL_LOG = "/a0/usr/memory/co_retrieval_log.json"

DEFAULT_CONFIG = {
    "enabled": True,
    "co_occurrence_min_sources": 1,
    "temporal_window_days": 30,
    "min_confidence_to_surface": 0.3,
    "promote_memory_links": True,
    "max_hops_for_path_analysis": 4,
}


def load_config() -> dict:
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
            return cfg.get('relationship_extraction', DEFAULT_CONFIG)
    except Exception:
        return DEFAULT_CONFIG


# ═════════════════════════════════════════════════════════════════════════════
# Method 1: Co-Occurrence Relationships
# ═════════════════════════════════════════════════════════════════════════════

def extract_co_occurrence(candidates: list, config: dict = None) -> list:
    """Entities in the same source record → co_mentioned relationship.

    candidates: list of resolved CandidateEntity dicts (must have provenance).
    Returns list of relationship dicts to store.
    """
    if config is None:
        config = load_config()
    min_sources = config.get('co_occurrence_min_sources', 1)

    # Group candidates by source record
    record_groups = defaultdict(list)
    for cand in candidates:
        prov = cand.get('provenance', {})
        key = f"{prov.get('source_id', '')}:{prov.get('record_id', '')}"
        record_groups[key].append(cand)

    # Count co-occurrences across source records
    # pair → set of source_ids
    pair_sources = defaultdict(set)
    pair_records = defaultdict(list)

    for record_key, group in record_groups.items():
        if len(group) < 2:
            continue
        source_id = group[0].get('provenance', {}).get('source_id', '')
        ont_meta = lambda c: c.get('_ontology_meta', {})

        # Get entity IDs (assigned during store phase, or generate from name)
        ids = []
        for cand in group:
            eid = cand.get('_entity_id', _temp_id(cand))
            ids.append((eid, cand))

        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                id_a, cand_a = ids[i]
                id_b, cand_b = ids[j]
                pair = tuple(sorted([id_a, id_b]))
                pair_sources[pair].add(source_id)
                pair_records[pair].append({
                    'source_id': source_id,
                    'record_id': record_key,
                    'cand_a': cand_a,
                    'cand_b': cand_b,
                })

    relationships = []
    now = datetime.now(timezone.utc).isoformat()

    for pair, sources in pair_sources.items():
        source_count = len(sources)
        if source_count < min_sources:
            continue

        confidence = 0.8 if source_count >= 3 else 0.5
        records = pair_records[pair]
        first_record = records[0]
        cand_a = first_record['cand_a']
        cand_b = first_record['cand_b']

        relationships.append({
            "rel_id": _rel_id(pair[0], "co_mentioned", pair[1]),
            "type": "co_mentioned",
            "from_entity": pair[0],
            "to_entity": pair[1],
            "from_entity_name": cand_a.get('properties', {}).get('name', ''),
            "to_entity_name": cand_b.get('properties', {}).get('name', ''),
            "properties": {
                "co_occurrence_count": source_count,
                "source_ids": list(sources),
            },
            "confidence": confidence,
            "provenance": {"source_ids": list(sources)},
            "created_at": now,
            "updated_at": now,
            "deprecated": False,
        })

    return relationships


# ═════════════════════════════════════════════════════════════════════════════
# Method 2: Property-Based Relationships
# ═════════════════════════════════════════════════════════════════════════════

def extract_property_based(candidates: list, config: dict = None) -> list:
    """Shared address → co_located, shared org reference → affiliated."""
    if config is None:
        config = load_config()

    from resolution_engine import canonicalize_address

    now = datetime.now(timezone.utc).isoformat()
    relationships = []

    # Group by canonicalized address
    address_groups = defaultdict(list)
    for cand in candidates:
        props = cand.get('properties', {})
        addr = props.get('address', '') or props.get('location', '')
        if addr:
            canonical = canonicalize_address(str(addr))
            if canonical and len(canonical) > 10:
                address_groups[canonical].append(cand)

    for addr, group in address_groups.items():
        if len(group) < 2:
            continue
        ids = [_temp_id(c) for c in group]
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                id_a = ids[i]
                id_b = ids[j]
                relationships.append({
                    "rel_id": _rel_id(id_a, "co_located", id_b),
                    "type": "co_located",
                    "from_entity": id_a,
                    "to_entity": id_b,
                    "from_entity_name": group[i].get('properties', {}).get('name', ''),
                    "to_entity_name": group[j].get('properties', {}).get('name', ''),
                    "properties": {"address": addr},
                    "confidence": 0.6,
                    "provenance": {},
                    "created_at": now,
                    "updated_at": now,
                    "deprecated": False,
                })

    # Shared organization affiliation
    org_groups = defaultdict(list)
    for cand in candidates:
        props = cand.get('properties', {})
        org = props.get('organization', '') or props.get('employer', '')
        if org and len(org) > 3:
            org_key = org.lower().strip()
            org_groups[org_key].append(cand)

    for org_key, group in org_groups.items():
        if len(group) < 2:
            continue
        ids = [_temp_id(c) for c in group]
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                id_a = ids[i]
                id_b = ids[j]
                relationships.append({
                    "rel_id": _rel_id(id_a, "affiliated", id_b),
                    "type": "related_to",
                    "from_entity": id_a,
                    "to_entity": id_b,
                    "from_entity_name": group[i].get('properties', {}).get('name', ''),
                    "to_entity_name": group[j].get('properties', {}).get('name', ''),
                    "properties": {"type": "affiliated", "shared_org": org_key},
                    "confidence": 0.6,
                    "provenance": {},
                    "created_at": now,
                    "updated_at": now,
                    "deprecated": False,
                })

    return relationships


# ═════════════════════════════════════════════════════════════════════════════
# Method 3: Temporal Relationships
# ═════════════════════════════════════════════════════════════════════════════

def extract_temporal(candidates: list, config: dict = None) -> list:
    """Events/records involving same entities within time window → temporally_linked."""
    if config is None:
        config = load_config()
    window_days = config.get('temporal_window_days', 30)

    from resolution_engine import normalize_date

    now = datetime.now(timezone.utc).isoformat()
    relationships = []

    # Group by entity and collect dated records
    dated = []
    for cand in candidates:
        props = cand.get('properties', {})
        date_str = (
            props.get('date')
            or props.get('filing_date')
            or props.get('effective_date')
        )
        norm_date = normalize_date(date_str) if date_str else ''
        if norm_date:
            dated.append((norm_date, _temp_id(cand), cand))

    if not dated:
        return relationships

    # Sort by date and find pairs within window
    dated.sort(key=lambda x: x[0])

    for i in range(len(dated)):
        date_a, id_a, cand_a = dated[i]
        for j in range(i + 1, len(dated)):
            date_b, id_b, cand_b = dated[j]
            if id_a == id_b:
                continue

            try:
                dt_a = datetime.strptime(date_a, '%Y-%m-%d')
                dt_b = datetime.strptime(date_b, '%Y-%m-%d')
                delta = abs((dt_b - dt_a).days)
                if delta > window_days:
                    break  # Sorted, so no more pairs within window

                confidence = max(0.3, 0.4 * (1 - delta / window_days))
                relationships.append({
                    "rel_id": _rel_id(id_a, "temporally_linked", id_b),
                    "type": "related_to",
                    "from_entity": id_a,
                    "to_entity": id_b,
                    "from_entity_name": cand_a.get('properties', {}).get('name', ''),
                    "to_entity_name": cand_b.get('properties', {}).get('name', ''),
                    "properties": {
                        "type": "temporally_linked",
                        "date_a": date_a,
                        "date_b": date_b,
                        "days_apart": delta,
                    },
                    "confidence": round(confidence, 3),
                    "provenance": {},
                    "created_at": now,
                    "updated_at": now,
                    "deprecated": False,
                })
            except ValueError:
                pass

    return relationships


# ═════════════════════════════════════════════════════════════════════════════
# Method 4: Graph-Based Discovery (promote Layer 10b memory links)
# ═════════════════════════════════════════════════════════════════════════════

def promote_memory_links(ontology_docs: list) -> list:
    """Promote Layer 10b related_memory_ids links to typed relationships.

    ontology_docs: list of FAISS Document objects with ontology metadata.
    Returns list of relationship dicts.
    """
    now = datetime.now(timezone.utc).isoformat()
    relationships = []

    for doc in ontology_docs:
        if not hasattr(doc, 'metadata'):
            continue
        ont = doc.metadata.get('ontology', {})
        lin = doc.metadata.get('lineage', {})
        entity_id = ont.get('entity_id', '')
        entity_name = ont.get('properties', {}).get('name', '')

        if not entity_id:
            continue

        related_ids = lin.get('related_memory_ids', [])
        for related_mem_id in related_ids:
            # This is a memory ID, not an entity ID — use as-is, mark as memory link
            relationships.append({
                "rel_id": _rel_id(entity_id, "related_to", related_mem_id),
                "type": "related_to",
                "from_entity": entity_id,
                "to_entity": related_mem_id,
                "from_entity_name": entity_name,
                "to_entity_name": "",
                "properties": {
                    "type": "memory_link",
                    "promoted_from": "layer10b_related_memory",
                },
                "confidence": 0.5,
                "provenance": {"promoted_from": "memory_classification"},
                "created_at": now,
                "updated_at": now,
                "deprecated": False,
            })

    return relationships


# ═════════════════════════════════════════════════════════════════════════════
# Method 5: Co-Retrieval Cluster Promotion
# ═════════════════════════════════════════════════════════════════════════════

def promote_co_retrieval_clusters(entity_id_map: dict) -> list:
    """Promote co-retrieval clusters from Layer 10b log to relationships.

    entity_id_map: {memory_id: entity_id} for ontology entities.
    """
    if not os.path.isfile(CO_RETRIEVAL_LOG):
        return []

    try:
        with open(CO_RETRIEVAL_LOG, 'r', encoding='utf-8') as f:
            log_data = json.load(f)
    except Exception:
        return []

    candidates = log_data.get('cluster_candidates', [])
    now = datetime.now(timezone.utc).isoformat()
    relationships = []

    for cluster in candidates:
        mem_ids = cluster.get('memory_ids', [])
        count = cluster.get('co_retrieval_count', 0)

        # Map to entity IDs
        entity_ids = [entity_id_map.get(mid) for mid in mem_ids if entity_id_map.get(mid)]
        if len(entity_ids) < 2:
            continue

        confidence = min(0.8, 0.3 + count * 0.05)

        for i in range(len(entity_ids)):
            for j in range(i + 1, len(entity_ids)):
                relationships.append({
                    "rel_id": _rel_id(entity_ids[i], "co_retrieved", entity_ids[j]),
                    "type": "related_to",
                    "from_entity": entity_ids[i],
                    "to_entity": entity_ids[j],
                    "from_entity_name": "",
                    "to_entity_name": "",
                    "properties": {
                        "type": "co_retrieved",
                        "co_retrieval_count": count,
                    },
                    "confidence": round(confidence, 3),
                    "provenance": {"promoted_from": "co_retrieval_log"},
                    "created_at": now,
                    "updated_at": now,
                    "deprecated": False,
                })

    return relationships


# ═════════════════════════════════════════════════════════════════════════════
# Persistence
# ═════════════════════════════════════════════════════════════════════════════

def store_relationships(relationships: list, min_confidence: float = 0.3):
    """Write relationships above threshold to relationships.jsonl, deduplicating."""
    if not relationships:
        return 0

    os.makedirs(ONTOLOGY_DIR, exist_ok=True)

    # Load existing rel_ids to avoid duplicates
    existing_ids = _load_existing_rel_ids()

    stored = 0
    with open(RELATIONSHIPS_FILE, 'a', encoding='utf-8') as f:
        for rel in relationships:
            if rel.get('confidence', 0) < min_confidence:
                continue
            rel_id = rel.get('rel_id', '')
            if rel_id and rel_id in existing_ids:
                continue
            f.write(json.dumps(rel) + '\n')
            stored += 1

    return stored


def _load_existing_rel_ids() -> set:
    if not os.path.isfile(RELATIONSHIPS_FILE):
        return set()
    ids = set()
    try:
        with open(RELATIONSHIPS_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                try:
                    rel = json.loads(s)
                    rid = rel.get('rel_id', '')
                    if rid:
                        ids.add(rid)
                except json.JSONDecodeError:
                    pass
    except OSError:
        pass
    return ids


# ═════════════════════════════════════════════════════════════════════════════
# Utilities
# ═════════════════════════════════════════════════════════════════════════════

def update_confidence_from_co_retrieval(co_retrieval_log: dict) -> int:
    """Update relationship confidence scores based on co-retrieval frequency."""
    if not os.path.isfile(RELATIONSHIPS_FILE):
        return 0

    entries = co_retrieval_log.get('entries', [])
    # Count how often entity pairs appear together in retrieval
    from collections import Counter
    pair_counts = Counter()
    for entry in entries:
        ids = entry.get('memory_ids', [])
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                pair_counts[tuple(sorted([ids[i], ids[j]]))] += 1

    if not pair_counts:
        return 0

    # Load and update relationships
    lines = []
    updated = 0
    try:
        with open(RELATIONSHIPS_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                try:
                    rel = json.loads(s)
                    pair = tuple(sorted([rel.get('from_entity', ''), rel.get('to_entity', '')]))
                    count = pair_counts.get(pair, 0)
                    if count > 0:
                        new_conf = min(0.95, rel.get('confidence', 0.5) + count * 0.02)
                        if new_conf != rel.get('confidence'):
                            rel['confidence'] = round(new_conf, 3)
                            rel['updated_at'] = datetime.now(timezone.utc).isoformat()
                            updated += 1
                    lines.append(json.dumps(rel))
                except json.JSONDecodeError:
                    lines.append(s)
    except OSError:
        return 0

    with open(RELATIONSHIPS_FILE, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')

    return updated


def _temp_id(cand: dict) -> str:
    """Temporary ID for a candidate before formal entity_id assignment."""
    import hashlib
    prov = cand.get('provenance', {})
    props = cand.get('properties', {})
    key = f"{prov.get('source_id', '')}:{prov.get('record_id', '')}:{props.get('name', '')}"
    return "tmp_" + hashlib.md5(key.encode()).hexdigest()[:12]


def _rel_id(from_id: str, rel_type: str, to_id: str) -> str:
    import hashlib
    key = f"{from_id}:{rel_type}:{to_id}"
    return "rel_" + hashlib.md5(key.encode()).hexdigest()[:12]
