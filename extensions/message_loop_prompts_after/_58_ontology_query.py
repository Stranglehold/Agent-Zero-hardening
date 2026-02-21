"""
Ontology Query — Agent-Zero Hardening Layer
============================================
Hook: message_loop_prompts_after
Priority: _58 (runs AFTER _56_memory_enhancement)

Extends memory retrieval with ontology-aware entity detection:
  1. Entity detection: scan user message for known entity names/aliases in FAISS
  2. Ontology search: FAISS queries with entity-specific expansions
  3. Relationship expansion: read 1-hop relationships from relationships.jsonl
  4. Context injection: write structured entity+relationship context to extras

Reads:
  - /a0/usr/ontology/ontology_config.json
  - FAISS (area="ontology" entity memories)
  - /a0/usr/ontology/relationships.jsonl
Writes:
  - loop_data.extras_persistent["ontology_context"]
"""

import json
import os
import re
from typing import Any

from agent import LoopData
from python.helpers.extension import Extension
from python.helpers.memory import Memory

# ── Paths ─────────────────────────────────────────────────────────────────────

ONTOLOGY_DIR = "/a0/usr/ontology"
CONFIG_PATH = os.path.join(ONTOLOGY_DIR, "ontology_config.json")
RELATIONSHIPS_FILE = os.path.join(ONTOLOGY_DIR, "relationships.jsonl")

ENTITY_AREA = "ontology"

DEFAULT_CONFIG = {
    "enabled": True,
    "entity_detection_in_messages": True,
    "auto_expand_relationships": True,
    "relationship_hops": 1,
    "max_connected_entities": 10,
    "inject_format": "structured",
}

# Minimum name length to consider for entity detection
MIN_ENTITY_NAME_LEN = 3
# Minimum similarity threshold for entity FAISS search
ENTITY_SEARCH_THRESHOLD = 0.4


class OntologyQuery(Extension):
    """Entity detection and relationship expansion for memory retrieval."""

    async def execute(self, loop_data: LoopData = LoopData(), **kwargs) -> Any:
        try:
            print("[ONT-QUERY] execute() called", flush=True)

            config = _load_ontology_config()
            if not config.get("enabled", True):
                return

            ont_config = config.get("ontology_query", DEFAULT_CONFIG)
            if not ont_config.get("enabled", True):
                return

            # Get user message
            query = _get_query(loop_data)
            if not query:
                return
            print(f"[ONT-QUERY] User message: {query[:60]!r}", flush=True)

            db = await Memory.get(self.agent)
            if not db or not db.db:
                return

            all_docs = db.db.get_all_docs()
            if not all_docs:
                print("[ONT-QUERY] No docs in FAISS, skipping", flush=True)
                return

            # ── Step 1: Entity Detection ───────────────────────────────────
            matched_entities = []
            if ont_config.get("entity_detection_in_messages", True):
                matched_entities = await _detect_entities(
                    query, db, all_docs, ont_config,
                )
                print(f"[ONT-QUERY] Entity detection: {len(matched_entities)} matches", flush=True)

            if not matched_entities:
                print("[ONT-QUERY] No ontology entities matched, skipping", flush=True)
                return

            # ── Step 2: Relationship Expansion ────────────────────────────
            rel_context = []
            if ont_config.get("auto_expand_relationships", True):
                rel_context = _expand_relationships(
                    matched_entities,
                    max_entities=ont_config.get("max_connected_entities", 10),
                    min_confidence=config.get("relationship_extraction", {}).get(
                        "min_confidence_to_surface", 0.3
                    ),
                )
                print(f"[ONT-QUERY] Relationship expansion: {len(rel_context)} relationships", flush=True)

            # ── Step 3: Build Connected Entity Summaries ───────────────────
            connected_summaries = await _get_connected_entities(
                matched_entities, rel_context, db, all_docs,
                max_entities=ont_config.get("max_connected_entities", 10),
            )

            # ── Step 4: Inject context ─────────────────────────────────────
            if matched_entities or rel_context:
                context_text = _format_context(
                    matched_entities, rel_context, connected_summaries,
                    inject_format=ont_config.get("inject_format", "structured"),
                )
                if context_text:
                    if loop_data.extras_persistent is None:
                        loop_data.extras_persistent = {}
                    loop_data.extras_persistent["ontology_context"] = context_text
                    print(
                        f"[ONT-QUERY] Injected {len(matched_entities)} entities "
                        f"+ {len(rel_context)} relationships into context",
                        flush=True,
                    )

        except Exception as e:
            try:
                self.agent.context.log.log(
                    type="warning",
                    content=f"[ONT-QUERY] Error (passthrough): {e}",
                )
            except Exception:
                pass


# ── Entity Detection ──────────────────────────────────────────────────────────

async def _detect_entities(query: str, db, all_docs: dict, config: dict) -> list:
    """Find ontology entities whose names appear in or match the query.

    Returns list of matched Document objects.
    """
    # Extract candidate names from query (capitalized sequences)
    candidate_names = _extract_names_from_query(query)

    matched = {}  # entity_id → doc

    # Strategy 1: Check all ontology docs for name overlap with query
    query_lower = query.lower()
    for doc_id, doc in all_docs.items():
        if not hasattr(doc, 'metadata'):
            continue
        if doc.metadata.get('area') != ENTITY_AREA:
            continue

        ont = doc.metadata.get('ontology', {})
        entity_id = ont.get('entity_id', '')
        if not entity_id or entity_id in matched:
            continue

        props = ont.get('properties', {})
        entity_name = props.get('name', '')
        aliases = props.get('aliases', [])

        # Check if entity name or alias appears in query
        all_names = [entity_name] + (aliases if isinstance(aliases, list) else [])
        for name in all_names:
            if not name or len(name) < MIN_ENTITY_NAME_LEN:
                continue
            if name.lower() in query_lower:
                matched[entity_id] = doc
                break

    # Strategy 2: Semantic FAISS search for entity-specific queries
    threshold = ENTITY_SEARCH_THRESHOLD
    limit = config.get("max_connected_entities", 10)

    try:
        results = await db.search_similarity_threshold(
            query=query,
            limit=limit,
            threshold=threshold,
            filter=f"area == '{ENTITY_AREA}'",
        )
        for item in results:
            doc = item[0] if isinstance(item, tuple) else item
            if not hasattr(doc, 'metadata'):
                continue
            ont = doc.metadata.get('ontology', {})
            entity_id = ont.get('entity_id', '')
            if entity_id and entity_id not in matched:
                matched[entity_id] = doc
    except Exception:
        pass

    return list(matched.values())


def _extract_names_from_query(query: str) -> list:
    """Extract capitalized word sequences from query as entity name candidates."""
    # Match 1-4 word capitalized sequences
    pattern = re.compile(
        r'\b([A-Z][a-zA-Z]{1,25}(?:\s+[A-Z][a-zA-Z]{1,25}){0,3})\b'
    )
    names = []
    seen = set()
    for match in pattern.finditer(query):
        name = match.group(1)
        if name.lower() not in seen and len(name) > MIN_ENTITY_NAME_LEN:
            seen.add(name.lower())
            names.append(name)
    return names


# ── Relationship Expansion ────────────────────────────────────────────────────

def _expand_relationships(
    matched_entities: list, max_entities: int = 10, min_confidence: float = 0.3,
) -> list:
    """Read 1-hop relationships for matched entities from relationships.jsonl."""
    if not os.path.isfile(RELATIONSHIPS_FILE):
        return []

    entity_ids = set()
    for doc in matched_entities:
        if hasattr(doc, 'metadata'):
            ont = doc.metadata.get('ontology', {})
            eid = ont.get('entity_id', '')
            if eid:
                entity_ids.add(eid)

    if not entity_ids:
        return []

    rels = []
    try:
        with open(RELATIONSHIPS_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                try:
                    rel = json.loads(s)
                except json.JSONDecodeError:
                    continue

                if rel.get('deprecated'):
                    continue
                if rel.get('confidence', 0) < min_confidence:
                    continue

                from_e = rel.get('from_entity', '')
                to_e = rel.get('to_entity', '')
                if from_e in entity_ids or to_e in entity_ids:
                    rels.append(rel)
                    if len(rels) >= max_entities * 3:
                        break
    except OSError:
        pass

    # Sort by confidence descending
    rels.sort(key=lambda r: r.get('confidence', 0), reverse=True)
    return rels[:max_entities]


# ── Connected Entity Retrieval ────────────────────────────────────────────────

async def _get_connected_entities(
    matched_entities: list, relationships: list, db, all_docs: dict,
    max_entities: int = 10,
) -> dict:
    """Fetch entity summaries for connected entities (1-hop neighbors).

    Returns dict: entity_id → page_content summary.
    """
    # Collect connected entity IDs not already matched
    matched_ids = set()
    for doc in matched_entities:
        if hasattr(doc, 'metadata'):
            ont = doc.metadata.get('ontology', {})
            matched_ids.add(ont.get('entity_id', ''))

    connected_ids = set()
    for rel in relationships:
        for eid in (rel.get('from_entity', ''), rel.get('to_entity', '')):
            if eid and eid not in matched_ids:
                connected_ids.add(eid)

    if not connected_ids:
        return {}

    # Look up in all_docs
    summaries = {}
    for doc in all_docs.values():
        if not hasattr(doc, 'metadata'):
            continue
        ont = doc.metadata.get('ontology', {})
        eid = ont.get('entity_id', '')
        if eid in connected_ids:
            summaries[eid] = getattr(doc, 'page_content', '')
            if len(summaries) >= max_entities:
                break

    return summaries


# ── Context Formatting ────────────────────────────────────────────────────────

def _format_context(
    matched_entities: list, relationships: list, connected_summaries: dict,
    inject_format: str = "structured",
) -> str:
    """Format entity + relationship context for prompt injection."""
    if not matched_entities and not relationships:
        return ""

    lines = ["# Ontology Context\n"]

    # Matched entities
    if matched_entities:
        lines.append("## Known Entities\n")
        for doc in matched_entities[:6]:
            if not hasattr(doc, 'metadata'):
                continue
            content = getattr(doc, 'page_content', '')
            if content:
                lines.append(f"- {content}")
        lines.append("")

    # Relationships
    if relationships:
        lines.append("## Known Connections\n")
        for rel in relationships[:10]:
            from_name = rel.get('from_entity_name', rel.get('from_entity', ''))
            to_name = rel.get('to_entity_name', rel.get('to_entity', ''))
            rel_type = rel.get('type', 'related_to')
            props = rel.get('properties', {})
            role = props.get('role', '')
            conf = rel.get('confidence', 0)

            rel_str = f"- {from_name} --[{rel_type}]--> {to_name}"
            if role:
                rel_str += f" (role: {role})"
            rel_str += f" [confidence: {conf:.2f}]"
            lines.append(rel_str)
        lines.append("")

    # Connected entity summaries
    if connected_summaries:
        lines.append("## Connected Entities\n")
        for eid, summary in list(connected_summaries.items())[:5]:
            if summary:
                lines.append(f"- {summary}")
        lines.append("")

    return "\n".join(lines)


# ── Utilities ─────────────────────────────────────────────────────────────────

def _get_query(loop_data) -> str:
    if hasattr(loop_data, "user_message") and loop_data.user_message:
        try:
            if hasattr(loop_data.user_message, "output_text"):
                return loop_data.user_message.output_text()
            return str(loop_data.user_message)
        except Exception:
            pass
    return ""


def _load_ontology_config() -> dict:
    try:
        if os.path.isfile(CONFIG_PATH):
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return {"enabled": True}
