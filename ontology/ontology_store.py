"""
Ontology Store — Agent-Zero Ontology Layer
==========================================
Function library for storing resolved entities as classified memories in FAISS
and managing the relationship graph (relationships.jsonl).

Entities are stored with area="ontology" and extended metadata including:
  - Standard Layer 10 classification (validity, relevance, utility, source)
  - Standard Layer 10 lineage (created_at, access_count, etc.)
  - New ontology metadata (entity_type, entity_id, properties, provenance_chain)

Relationships are stored as typed, directional edges in a JSONL file.

No external dependencies. FAISS access goes through Agent-Zero's Memory API.
"""

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from typing import Any

ONTOLOGY_DIR = "/a0/usr/ontology"
RELATIONSHIPS_FILE = os.path.join(ONTOLOGY_DIR, "relationships.jsonl")
CONFIG_PATH = os.path.join(ONTOLOGY_DIR, "ontology_config.json")

ENTITY_AREA = "ontology"
ENTITY_ID_PREFIX = "ent_"

# Layer 10 classification defaults for ontology entities
DEFAULT_CLASSIFICATION = {
    "validity": "confirmed",
    "relevance": "active",
    "utility": "tactical",
    "source": "external_retrieved",
}


# ═════════════════════════════════════════════════════════════════════════════
# Entity ID Generation
# ═════════════════════════════════════════════════════════════════════════════

def generate_entity_id(entity_type: str, name: str, provenance: dict = None) -> str:
    """Generate stable entity ID from type + normalized name + optional provenance."""
    norm = name.lower().strip() if name else "unknown"
    prov_key = ""
    if provenance:
        prov_key = provenance.get('source_id', '') + ':' + provenance.get('record_id', '')
    key = f"{entity_type}:{norm}:{prov_key}"
    digest = hashlib.sha256(key.encode()).hexdigest()[:12]
    return f"{ENTITY_ID_PREFIX}{digest}"


# ═════════════════════════════════════════════════════════════════════════════
# Natural-Language Summary Generation
# ═════════════════════════════════════════════════════════════════════════════

def build_entity_summary(entity: dict, relationships: list = None) -> str:
    """Build natural-language summary of entity for FAISS semantic search.

    Max 500 chars. Format:
    "[name] ([entity_type]) — [key properties]. [relationship summary]."
    """
    props = entity.get('properties', {})
    entity_type = entity.get('entity_type', 'entity')
    name = props.get('name', 'Unknown')

    parts = [f"{name} ({entity_type})"]

    # Add description or key properties
    if props.get('description'):
        parts.append(props['description'][:120])
    else:
        detail_parts = []
        if props.get('type'):
            detail_parts.append(f"Type: {props['type']}")
        if props.get('jurisdiction'):
            detail_parts.append(f"Jurisdiction: {props['jurisdiction']}")
        if props.get('role'):
            detail_parts.append(f"Role: {props['role']}")
        if props.get('date_of_birth'):
            detail_parts.append(f"DOB: {props['date_of_birth']}")
        if detail_parts:
            parts.append(", ".join(detail_parts))

    # Add aliases
    aliases = props.get('aliases', [])
    if aliases:
        alias_str = ", ".join(aliases[:3])
        parts.append(f"Also known as: {alias_str}")

    # Add provenance summary
    prov_chain = entity.get('provenance_chain', [])
    if prov_chain:
        sources = [p.get('source_id', '') for p in prov_chain if p.get('source_id')]
        if sources:
            parts.append(f"Sources: {', '.join(sources[:3])}")

    # Add relationship summary
    if relationships:
        rel_parts = []
        for rel in relationships[:4]:
            rel_type = rel.get('type', 'related_to')
            target = rel.get('to_entity_name', rel.get('to_entity', ''))
            if target:
                rel_parts.append(f"{rel_type}: {target}")
        if rel_parts:
            parts.append("Connections: " + ", ".join(rel_parts))

    summary = " — ".join(parts)
    return summary[:500]


# ═════════════════════════════════════════════════════════════════════════════
# Entity Storage (FAISS via Memory API)
# ═════════════════════════════════════════════════════════════════════════════

async def store_entity(agent, entity: dict, entity_id: str = None) -> str:
    """Store resolved entity as classified memory in FAISS.

    Returns entity_id.
    """
    try:
        from python.helpers.memory import Memory
    except ImportError:
        return ""

    props = entity.get('properties', {})
    entity_type = entity.get('entity_type', 'entity')
    name = props.get('name', 'Unknown')
    provenance = entity.get('provenance', {})

    if not entity_id:
        entity_id = generate_entity_id(entity_type, name, provenance)

    # Load existing relationships for this entity to include in summary
    existing_rels = get_entity_relationships(entity_id)
    summary = build_entity_summary(entity, existing_rels)

    now = datetime.now(timezone.utc).isoformat()

    # Build classification (Layer 10 axes)
    confidence = provenance.get('confidence', 0.5) if provenance else 0.5
    validity = "confirmed" if confidence >= 0.8 else "inferred"

    metadata = {
        "area": ENTITY_AREA,
        "id": entity_id,
        "timestamp": now,
        # Layer 10 classification
        "classification": {
            "validity": validity,
            "relevance": "active",
            "utility": "tactical",
            "source": "external_retrieved",
        },
        # Layer 10 lineage
        "lineage": {
            "created_at": now,
            "created_by_role": None,
            "bst_domain": "investigation",
            "classified_at_cycle": 0,
            "supersedes": None,
            "superseded_by": None,
            "access_count": 0,
            "last_accessed": None,
            "related_memory_ids": [],
        },
        # Ontology metadata
        "ontology": {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "properties": props,
            "provenance_chain": entity.get('provenance_chain', [provenance] if provenance else []),
            "merge_history": entity.get('merge_history', []),
            "investigation_tags": entity.get('investigation_tags', []),
        },
    }

    try:
        db = await Memory.get(agent)
        mem_id = await db.insert_text(summary, metadata)
        print(f"[ONT-STORE] Stored entity {entity_id} ({entity_type}: {name}) as memory {mem_id}", flush=True)
        return entity_id
    except Exception as e:
        print(f"[ONT-STORE] Failed to store entity {entity_id}: {e}", flush=True)
        return ""


async def update_entity(agent, entity_id: str, entity: dict) -> bool:
    """Update entity in FAISS: delete old memory, create new one."""
    try:
        from python.helpers.memory import Memory
        db = await Memory.get(agent)

        # Delete existing
        try:
            await db.delete_documents_by_query(
                query=f"area == 'ontology' and id == '{entity_id}'"
            )
        except Exception:
            pass

        # Store updated
        new_id = await store_entity(agent, entity, entity_id)
        return bool(new_id)
    except Exception as e:
        print(f"[ONT-STORE] Failed to update entity {entity_id}: {e}", flush=True)
        return False


async def search_entities(
    agent, query: str, entity_type: str = None,
    limit: int = 10, threshold: float = 0.3,
) -> list:
    """Search ontology entities in FAISS by semantic query."""
    try:
        from python.helpers.memory import Memory
        db = await Memory.get(agent)

        area_filter = f"area == '{ENTITY_AREA}'"
        if entity_type:
            # Filter by entity_type requires metadata filtering post-search
            pass

        results = await db.search_similarity_threshold(
            query=query,
            limit=limit * 2,  # Over-fetch to allow post-filtering
            threshold=threshold,
            filter=area_filter,
        )

        docs = []
        for item in results:
            doc = item[0] if isinstance(item, tuple) else item
            if not hasattr(doc, 'metadata'):
                continue
            ont = doc.metadata.get('ontology', {})
            if entity_type and ont.get('entity_type') != entity_type:
                continue
            docs.append(doc)
            if len(docs) >= limit:
                break

        return docs
    except Exception as e:
        print(f"[ONT-STORE] Search failed: {e}", flush=True)
        return []


async def get_entity_by_id(agent, entity_id: str):
    """Retrieve an entity memory by its ontology entity_id."""
    try:
        from python.helpers.memory import Memory
        db = await Memory.get(agent)
        all_docs = db.db.get_all_docs()
        for doc in all_docs.values():
            if not hasattr(doc, 'metadata'):
                continue
            ont = doc.metadata.get('ontology', {})
            if ont.get('entity_id') == entity_id:
                return doc
        return None
    except Exception:
        return None


# ═════════════════════════════════════════════════════════════════════════════
# Relationship Storage (JSONL)
# ═════════════════════════════════════════════════════════════════════════════

def store_relationship(
    from_entity_id: str,
    to_entity_id: str,
    rel_type: str,
    properties: dict = None,
    confidence: float = 0.5,
    provenance: dict = None,
    from_entity_name: str = "",
    to_entity_name: str = "",
) -> str:
    """Store a typed relationship edge in relationships.jsonl.

    Returns rel_id.
    """
    _ensure_dir(ONTOLOGY_DIR)
    now = datetime.now(timezone.utc).isoformat()

    rel_key = f"{from_entity_id}:{rel_type}:{to_entity_id}"
    rel_id = "rel_" + hashlib.md5(rel_key.encode()).hexdigest()[:12]

    entry = {
        "rel_id": rel_id,
        "type": rel_type,
        "from_entity": from_entity_id,
        "to_entity": to_entity_id,
        "from_entity_name": from_entity_name,
        "to_entity_name": to_entity_name,
        "properties": properties or {},
        "confidence": confidence,
        "provenance": provenance or {},
        "created_at": now,
        "updated_at": now,
        "deprecated": False,
    }

    with open(RELATIONSHIPS_FILE, 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry) + '\n')

    return rel_id


def get_entity_relationships(
    entity_id: str, rel_type: str = None, direction: str = "both",
) -> list:
    """Read relationships for an entity from relationships.jsonl.

    direction: "outgoing" | "incoming" | "both"
    Returns list of relationship dicts (non-deprecated only).
    """
    if not os.path.isfile(RELATIONSHIPS_FILE):
        return []

    rels = []
    try:
        with open(RELATIONSHIPS_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rel = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if rel.get('deprecated'):
                    continue
                if rel_type and rel.get('type') != rel_type:
                    continue

                is_from = rel.get('from_entity') == entity_id
                is_to = rel.get('to_entity') == entity_id

                if direction == "outgoing" and is_from:
                    rels.append(rel)
                elif direction == "incoming" and is_to:
                    rels.append(rel)
                elif direction == "both" and (is_from or is_to):
                    rels.append(rel)
    except OSError:
        pass

    return rels


def get_relationships_for_entities(entity_ids: set) -> list:
    """Read all non-deprecated relationships involving any of the given entity IDs."""
    if not os.path.isfile(RELATIONSHIPS_FILE):
        return []
    rels = []
    try:
        with open(RELATIONSHIPS_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rel = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rel.get('deprecated'):
                    continue
                if rel.get('from_entity') in entity_ids or rel.get('to_entity') in entity_ids:
                    rels.append(rel)
    except OSError:
        pass
    return rels


def deprecate_relationship(rel_id: str):
    """Mark a relationship as deprecated (in-place rewrite)."""
    if not os.path.isfile(RELATIONSHIPS_FILE):
        return
    lines = []
    try:
        with open(RELATIONSHIPS_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                try:
                    rel = json.loads(s)
                    if rel.get('rel_id') == rel_id:
                        rel['deprecated'] = True
                        rel['updated_at'] = datetime.now(timezone.utc).isoformat()
                    lines.append(json.dumps(rel))
                except json.JSONDecodeError:
                    lines.append(s)
    except OSError:
        return
    with open(RELATIONSHIPS_FILE, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')


def compact_relationships():
    """Remove deprecated relationships from the JSONL file."""
    if not os.path.isfile(RELATIONSHIPS_FILE):
        return 0
    lines = []
    removed = 0
    try:
        with open(RELATIONSHIPS_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                try:
                    rel = json.loads(s)
                    if not rel.get('deprecated'):
                        lines.append(json.dumps(rel))
                    else:
                        removed += 1
                except json.JSONDecodeError:
                    lines.append(s)
    except OSError:
        return 0
    with open(RELATIONSHIPS_FILE, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    return removed


def update_relationship_confidence(rel_id: str, new_confidence: float):
    """Update confidence score of a relationship."""
    if not os.path.isfile(RELATIONSHIPS_FILE):
        return
    lines = []
    try:
        with open(RELATIONSHIPS_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                try:
                    rel = json.loads(s)
                    if rel.get('rel_id') == rel_id:
                        rel['confidence'] = new_confidence
                        rel['updated_at'] = datetime.now(timezone.utc).isoformat()
                    lines.append(json.dumps(rel))
                except json.JSONDecodeError:
                    lines.append(s)
    except OSError:
        return
    with open(RELATIONSHIPS_FILE, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')


# ═════════════════════════════════════════════════════════════════════════════
# Utilities
# ═════════════════════════════════════════════════════════════════════════════

def load_ontology_config() -> dict:
    """Load ontology config from disk."""
    try:
        if os.path.isfile(CONFIG_PATH):
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _ensure_dir(path: str):
    if path:
        os.makedirs(path, exist_ok=True)
