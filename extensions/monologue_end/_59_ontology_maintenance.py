"""
Ontology Maintenance — Agent-Zero Hardening Layer
==================================================
Hook: monologue_end
Priority: _59 (runs AFTER _57_memory_maintenance)

Four ontology maintenance tasks (run every maintenance_interval_cycles):
  1. Queue resolve: run entity resolution on unresolved candidates in ingestion queue
  2. Relationship update: update confidence from co-retrieval data
  3. Compact: remove deprecated relationships from JSONL
  4. Summary rebuild: rebuild entity summaries for recently merged entities

Reads:
  - /a0/usr/ontology/ontology_config.json
  - /a0/usr/ontology/ingestion_queue.jsonl
  - /a0/usr/memory/co_retrieval_log.json
Writes:
  - FAISS (entity memories via ontology_store)
  - /a0/usr/ontology/relationships.jsonl
"""

import json
import os
import sys
from typing import Any

from agent import LoopData
from python.helpers.extension import Extension
from python.helpers.memory import Memory

# ── Paths ─────────────────────────────────────────────────────────────────────

ONTOLOGY_DIR = "/a0/usr/ontology"
CONFIG_PATH = os.path.join(ONTOLOGY_DIR, "ontology_config.json")
CO_RETRIEVAL_LOG = "/a0/usr/memory/co_retrieval_log.json"
RELATIONSHIPS_FILE = os.path.join(ONTOLOGY_DIR, "relationships.jsonl")
INGESTION_QUEUE = os.path.join(ONTOLOGY_DIR, "ingestion_queue.jsonl")

DEFAULT_INTERVAL = 25

# Agent attribute key for this extension's cycle counter
MAINT_COUNTER_KEY = "_ontology_maint_59_counter"


class OntologyMaintenance(Extension):
    """Periodic ontology queue resolution, relationship updates, and compaction."""

    async def execute(self, loop_data: LoopData = LoopData(), **kwargs) -> Any:
        try:
            print("[ONT-MAINT] execute() called", flush=True)

            config = _load_config()
            if not config.get("enabled", True):
                return

            maint_config = config.get("maintenance", {})
            if not maint_config.get("enabled", True):
                return

            interval = maint_config.get("interval_cycles", DEFAULT_INTERVAL)

            counter = getattr(self.agent, MAINT_COUNTER_KEY, 0) + 1
            setattr(self.agent, MAINT_COUNTER_KEY, counter)
            print(f"[ONT-MAINT] cycle {counter}/{interval}", flush=True)

            if interval <= 0 or counter % interval != 0:
                return

            print(f"[ONT-MAINT] FIRING at cycle {counter}", flush=True)

            db = await Memory.get(self.agent)
            if not db or not db.db:
                return

            # ── Phase 1: Queue Resolution ──────────────────────────────────
            resolved_count = await _run_queue_resolution(self.agent, db, config)
            if resolved_count > 0:
                print(f"[ONT-MAINT] Resolved {resolved_count} pending candidates", flush=True)
                self.agent.context.log.log(
                    type="info",
                    content=f"[ONT-MAINT] Resolved {resolved_count} ontology entities",
                )

            # ── Phase 2: Relationship Confidence Update ────────────────────
            if maint_config.get("relationship_confidence_update", True):
                updated = _update_relationship_confidence()
                if updated > 0:
                    print(f"[ONT-MAINT] Updated confidence on {updated} relationships", flush=True)

            # ── Phase 3: Compact Deprecated Relationships ──────────────────
            if maint_config.get("compact_deprecated_relationships", True):
                removed = _compact_relationships()
                if removed > 0:
                    print(f"[ONT-MAINT] Compacted {removed} deprecated relationships", flush=True)

            # ── Phase 4: Rebuild Merged Entity Summaries ───────────────────
            if maint_config.get("rebuild_merged_summaries", True):
                rebuilt = await _rebuild_merged_summaries(self.agent, db)
                if rebuilt > 0:
                    print(f"[ONT-MAINT] Rebuilt {rebuilt} entity summaries", flush=True)

            print("[ONT-MAINT] Maintenance cycle complete", flush=True)

        except Exception as e:
            print(f"[ONT-MAINT] Error: {type(e).__name__}: {e}", flush=True)
            try:
                self.agent.context.log.log(
                    type="warning",
                    content=f"[ONT-MAINT] Error (passthrough): {e}",
                )
            except Exception:
                pass


# ── Phase 1: Queue Resolution ─────────────────────────────────────────────────

async def _run_queue_resolution(agent, db, config: dict) -> int:
    """Run entity resolution on pending candidates in the ingestion queue."""
    if not os.path.isfile(INGESTION_QUEUE):
        return 0

    # Read unresolved candidates
    candidates = []
    try:
        with open(INGESTION_QUEUE, 'r', encoding='utf-8') as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                try:
                    cand = json.loads(s)
                    if not cand.get('_resolved'):
                        candidates.append(cand)
                except json.JSONDecodeError:
                    pass
    except OSError:
        return 0

    if not candidates:
        return 0

    max_batch = config.get('source_connectors', {}).get('max_batch_size', 100)
    batch = candidates[:max_batch]

    print(f"[ONT-MAINT] Processing {len(batch)} pending candidates", flush=True)

    try:
        # Import resolution engine (installed at /a0/usr/ontology/)
        sys.path.insert(0, ONTOLOGY_DIR)
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "resolution_engine",
            os.path.join(ONTOLOGY_DIR, "resolution_engine.py")
        )
        if spec is None:
            return 0
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        result = module.resolve_batch(batch, config)
        resolved_entities = result.get('resolved', []) + result.get('distinct', [])

        # Store resolved entities
        spec2 = importlib.util.spec_from_file_location(
            "ontology_store",
            os.path.join(ONTOLOGY_DIR, "ontology_store.py")
        )
        if spec2:
            store_module = importlib.util.module_from_spec(spec2)
            spec2.loader.exec_module(store_module)

            stored = 0
            for entity in resolved_entities:
                try:
                    entity_id = await store_module.store_entity(agent, entity)
                    if entity_id:
                        stored += 1
                except Exception as e:
                    print(f"[ONT-MAINT] Store failed: {e}", flush=True)

            # Mark queue entries as resolved
            candidate_ids = {module._candidate_id(c) for c in batch}
            module.mark_queue_resolved(candidate_ids)

            return stored

    except Exception as e:
        print(f"[ONT-MAINT] Resolution error: {type(e).__name__}: {e}", flush=True)

    return 0


# ── Phase 2: Relationship Confidence Update ────────────────────────────────────

def _update_relationship_confidence() -> int:
    """Update relationship confidence scores from co-retrieval log."""
    if not os.path.isfile(CO_RETRIEVAL_LOG):
        return 0
    if not os.path.isfile(RELATIONSHIPS_FILE):
        return 0

    try:
        with open(CO_RETRIEVAL_LOG, 'r', encoding='utf-8') as f:
            log_data = json.load(f)
    except Exception:
        return 0

    try:
        sys.path.insert(0, ONTOLOGY_DIR)
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "relationship_extractor",
            os.path.join(ONTOLOGY_DIR, "relationship_extractor.py")
        )
        if spec is None:
            return 0
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.update_confidence_from_co_retrieval(log_data)
    except Exception as e:
        print(f"[ONT-MAINT] Confidence update error: {e}", flush=True)
        return 0


# ── Phase 3: Compact Deprecated Relationships ──────────────────────────────────

def _compact_relationships() -> int:
    """Remove deprecated relationships from the JSONL file."""
    if not os.path.isfile(RELATIONSHIPS_FILE):
        return 0

    try:
        sys.path.insert(0, ONTOLOGY_DIR)
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "ontology_store",
            os.path.join(ONTOLOGY_DIR, "ontology_store.py")
        )
        if spec is None:
            return 0
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.compact_relationships()
    except Exception as e:
        print(f"[ONT-MAINT] Compact error: {e}", flush=True)
        return 0


# ── Phase 4: Rebuild Merged Entity Summaries ──────────────────────────────────

async def _rebuild_merged_summaries(agent, db) -> int:
    """Rebuild entity summaries for entities with merge_history entries."""
    all_docs = db.db.get_all_docs()
    rebuilt = 0

    for doc_id, doc in all_docs.items():
        if not hasattr(doc, 'metadata'):
            continue
        if doc.metadata.get('area') != 'ontology':
            continue
        ont = doc.metadata.get('ontology', {})
        if not ont.get('merge_history'):
            continue

        # Rebuild summary for this entity
        try:
            sys.path.insert(0, ONTOLOGY_DIR)
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "ontology_store",
                os.path.join(ONTOLOGY_DIR, "ontology_store.py")
            )
            if spec is None:
                continue
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            # Build entity dict from metadata
            entity = {
                "entity_type": ont.get("entity_type", "entity"),
                "properties": ont.get("properties", {}),
                "provenance_chain": ont.get("provenance_chain", []),
                "merge_history": ont.get("merge_history", []),
            }
            entity_id = ont.get("entity_id", "")

            # Get relationships for this entity
            rels = module.get_entity_relationships(entity_id)
            new_summary = module.build_entity_summary(entity, rels)

            # Update page_content in docstore
            doc.page_content = new_summary
            rebuilt += 1
        except Exception:
            pass

    if rebuilt > 0:
        try:
            db._save_db()
        except Exception:
            pass

    return rebuilt


# ── Config Loading ─────────────────────────────────────────────────────────────

def _load_config() -> dict:
    try:
        if os.path.isfile(CONFIG_PATH):
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
            cfg.setdefault("enabled", True)
            return cfg
    except Exception:
        pass
    return {"enabled": True}
