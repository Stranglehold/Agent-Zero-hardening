"""
Memory Maintenance — Agent-Zero Hardening Layer
=================================================
Hook: monologue_end
Priority: _57 (runs AFTER _55_memory_classifier)

Four maintenance tasks (run every maintenance_interval_loops cycles):

  1. Deduplication: identify memory pairs with cosine similarity > threshold.
     Resolution: both agent_inferred -> deprecate older; one user_asserted ->
     keep user; both user_asserted -> flag only; load_bearing -> never auto-
     deprecate. Capped at max_pairs_per_cycle.

  2. Related Memory Linking (write-time): compare classification tags across
     active memories. If tag overlap >= threshold, cross-link via
     lineage.related_memory_ids. Tags = {validity, relevance, utility, source,
     bst_domain, area}.

  3. Cluster Candidate Detection: read co_retrieval_log.json, find memory ID
     pairs co-occurring > cluster_threshold times, write to cluster_candidates.

  4. Dormancy Check: flag memories with access_count == 0 after N maintenance
     cycles. Log only — no auto-reclassification.

Reads:
  - deduplication, related_memories config from classification_config.json
  - /a0/usr/memory/co_retrieval_log.json
Writes:
  - Document.metadata (deprecation, superseded_by, related_memory_ids)
  - /a0/usr/memory/co_retrieval_log.json (cluster_candidates)
"""

import json
import os
from collections import Counter
from datetime import datetime, timezone
from itertools import combinations
from typing import Any

from agent import LoopData
from python.helpers.extension import Extension
from python.helpers.memory import Memory

# ── Configuration ────────────────────────────────────────────────────────────

CONFIG_PATH = "/a0/usr/memory/classification_config.json"
CO_RETRIEVAL_LOG = "/a0/usr/memory/co_retrieval_log.json"

DEFAULT_CONFIG = {
    "maintenance_interval_loops": 25,
    "archival_threshold_cycles": 50,
}

DEFAULT_DEDUP_CONFIG = {
    "enabled": True,
    "similarity_threshold": 0.90,
    "auto_deprecate_agent_inferred": True,
    "max_pairs_per_cycle": 20,
    "log_all_candidates": True,
}

DEFAULT_RELATED_CONFIG = {
    "enabled": True,
    "tag_overlap_threshold": 3,
    "related_boost": 0.08,
    "max_related_per_memory": 10,
    "rebuild_interval_cycles": 25,
}

CLUSTER_THRESHOLD = 5  # Min co-occurrences to become cluster candidate

# Metadata keys (must match _55_memory_classifier.py)
CLS_KEY = "classification"
LIN_KEY = "lineage"

# Agent attribute key for this extension's cycle counter
MAINT_COUNTER_KEY = "_memory_maint_57_counter"

# ── Resolution priority ranks ────────────────────────────────────────────────

_SOURCE_RANK = {
    "user_asserted": 3,
    "external_retrieved": 2,
    "agent_inferred": 1,
}

_VALIDITY_RANK = {
    "confirmed": 2,
    "inferred": 1,
    "deprecated": 0,
}


class MemoryMaintenance(Extension):
    """Periodic deduplication, linking, cluster detection, dormancy check."""

    async def execute(self, loop_data: LoopData = LoopData(), **kwargs) -> Any:
        try:
            config = _load_config()
            interval = config.get("maintenance_interval_loops", 25)

            # Cycle counter — only run expensive ops periodically
            counter = getattr(self.agent, MAINT_COUNTER_KEY, 0) + 1
            setattr(self.agent, MAINT_COUNTER_KEY, counter)

            if interval <= 0 or counter % interval != 0:
                return

            db = await Memory.get(self.agent)
            if not db or not db.db:
                return

            all_docs = db.db.get_all_docs()
            if not all_docs:
                return

            dedup_config = config.get("deduplication", DEFAULT_DEDUP_CONFIG)
            related_config = config.get("related_memories", DEFAULT_RELATED_CONFIG)
            changed = False

            # ── Phase 1: Deduplication ────────────────────────────────────
            if dedup_config.get("enabled", True):
                dedup_count = await _run_deduplication(
                    db, all_docs, dedup_config,
                )
                if dedup_count > 0:
                    changed = True
                    self.agent.context.log.log(
                        type="info",
                        content=(
                            f"[MEM-MAINT] Deduplicated {dedup_count} "
                            f"memory pairs"
                        ),
                    )

            # ── Phase 2: Related Memory Linking ───────────────────────────
            if related_config.get("enabled", True):
                link_count = _run_related_linking(
                    all_docs, related_config,
                )
                if link_count > 0:
                    changed = True
                    self.agent.context.log.log(
                        type="info",
                        content=(
                            f"[MEM-MAINT] Linked {link_count} "
                            f"related memory pairs"
                        ),
                    )

            # ── Phase 3: Cluster Candidate Detection ──────────────────────
            cluster_count = _detect_cluster_candidates()
            if cluster_count > 0:
                self.agent.context.log.log(
                    type="info",
                    content=(
                        f"[MEM-MAINT] Found {cluster_count} "
                        f"cluster candidates"
                    ),
                )

            # ── Phase 4: Dormancy Check ───────────────────────────────────
            archival_threshold = config.get("archival_threshold_cycles", 50)
            dormant_count = _check_dormancy(
                all_docs, counter, archival_threshold,
            )
            if dormant_count > 0:
                changed = True
                self.agent.context.log.log(
                    type="info",
                    content=(
                        f"[MEM-MAINT] {dormant_count} memories "
                        f"flagged as dormancy candidates"
                    ),
                )

            # ── Persist changes ───────────────────────────────────────────
            if changed:
                try:
                    db._save_db()
                except Exception:
                    pass

            # ── Ontology maintenance hook ─────────────────────────────────
            # Promote Layer 10b memory links to typed relationships when
            # the ontology layer is enabled.
            _run_ontology_hook(all_docs)

        except Exception as e:
            try:
                self.agent.context.log.log(
                    type="warning",
                    content=f"[MEM-MAINT] Error (passthrough): {e}",
                )
            except Exception:
                pass


# ── Phase 1: Deduplication ───────────────────────────────────────────────────

async def _run_deduplication(
    db, all_docs: dict, dedup_config: dict,
) -> int:
    """Scan for duplicate memory pairs and resolve. Returns resolved count."""
    threshold = dedup_config.get("similarity_threshold", 0.90)
    max_pairs = dedup_config.get("max_pairs_per_cycle", 20)
    auto_deprecate = dedup_config.get(
        "auto_deprecate_agent_inferred", True,
    )

    processed_pairs = set()
    resolved_count = 0

    # Collect non-deprecated candidates
    candidates = []
    for doc_id, doc in all_docs.items():
        if not hasattr(doc, "metadata"):
            continue
        cls = doc.metadata.get(CLS_KEY, {})
        if cls.get("validity") == "deprecated":
            continue
        text = getattr(doc, "page_content", "")
        if not text or len(text) < 10:
            continue
        candidates.append((doc_id, doc, text))

    for doc_id, doc, text in candidates:
        if resolved_count >= max_pairs:
            break

        try:
            results = await db.search_similarity_threshold(
                query=text, limit=6, threshold=threshold,
            )
        except Exception:
            continue

        for item in results:
            if resolved_count >= max_pairs:
                break

            sim_doc, score = (
                item if isinstance(item, tuple) else (item, 1.0)
            )
            sim_id = (
                sim_doc.metadata.get("id", "")
                if hasattr(sim_doc, "metadata") else ""
            )

            if sim_id == doc_id or not sim_id:
                continue

            pair_key = tuple(sorted([doc_id, sim_id]))
            if pair_key in processed_pairs:
                continue
            processed_pairs.add(pair_key)

            sim_cls = sim_doc.metadata.get(CLS_KEY, {})
            if sim_cls.get("validity") == "deprecated":
                continue

            doc_cls = doc.metadata.get(CLS_KEY, {})

            action = _determine_resolution(
                doc_id, doc_cls, doc.metadata,
                sim_id, sim_cls, sim_doc.metadata,
                auto_deprecate,
            )

            if action == "skip" or action == "flag_only":
                continue

            loser_id, winner_id = action
            _deprecate_memory(all_docs, loser_id, winner_id)
            resolved_count += 1

    return resolved_count


def _determine_resolution(
    id_a, cls_a, meta_a, id_b, cls_b, meta_b, auto_deprecate,
):
    """Determine deduplication resolution.

    Returns "skip", "flag_only", or (loser_id, winner_id).
    """
    source_a = cls_a.get("source", "agent_inferred")
    source_b = cls_b.get("source", "agent_inferred")
    utility_a = cls_a.get("utility", "tactical")
    utility_b = cls_b.get("utility", "tactical")
    validity_a = cls_a.get("validity", "inferred")
    validity_b = cls_b.get("validity", "inferred")

    # load_bearing: never auto-deprecate
    if utility_a == "load_bearing" or utility_b == "load_bearing":
        return "flag_only"

    # Both user_asserted: flag only
    if source_a == "user_asserted" and source_b == "user_asserted":
        return "flag_only"

    # One user_asserted: keep user, deprecate other
    if source_a == "user_asserted" and source_b != "user_asserted":
        return (id_b, id_a)
    if source_b == "user_asserted" and source_a != "user_asserted":
        return (id_a, id_b)

    # One confirmed: keep confirmed, deprecate other
    if validity_a == "confirmed" and validity_b != "confirmed":
        return (id_b, id_a)
    if validity_b == "confirmed" and validity_a != "confirmed":
        return (id_a, id_b)

    # Both agent_inferred: deprecate older
    if (source_a == "agent_inferred" and source_b == "agent_inferred"
            and auto_deprecate):
        ts_a = _get_created_at(meta_a)
        ts_b = _get_created_at(meta_b)
        if ts_a <= ts_b:
            return (id_a, id_b)
        return (id_b, id_a)

    return "skip"


def _get_created_at(metadata: dict) -> str:
    """Extract creation timestamp from metadata."""
    lin = metadata.get(LIN_KEY, {})
    return lin.get("created_at") or metadata.get("timestamp", "")


def _deprecate_memory(all_docs: dict, loser_id: str, winner_id: str):
    """Mark loser as deprecated with superseded_by pointer."""
    loser = all_docs.get(loser_id)
    winner = all_docs.get(winner_id)

    if loser and hasattr(loser, "metadata"):
        if CLS_KEY not in loser.metadata:
            loser.metadata[CLS_KEY] = {}
        loser.metadata[CLS_KEY]["validity"] = "deprecated"

        if LIN_KEY not in loser.metadata:
            loser.metadata[LIN_KEY] = {}
        loser.metadata[LIN_KEY]["superseded_by"] = winner_id
        loser.metadata[LIN_KEY]["deprecated_at"] = (
            datetime.now(timezone.utc).isoformat()
        )
        loser.metadata[LIN_KEY]["deprecated_reason"] = "deduplication"

    if winner and hasattr(winner, "metadata"):
        if LIN_KEY not in winner.metadata:
            winner.metadata[LIN_KEY] = {}
        existing = winner.metadata[LIN_KEY].get("supersedes")
        if existing and existing != loser_id:
            if isinstance(existing, list):
                if loser_id not in existing:
                    existing.append(loser_id)
            else:
                winner.metadata[LIN_KEY]["supersedes"] = [
                    existing, loser_id,
                ]
        else:
            winner.metadata[LIN_KEY]["supersedes"] = loser_id


# ── Phase 2: Related Memory Linking ──────────────────────────────────────────

def _run_related_linking(
    all_docs: dict, related_config: dict,
) -> int:
    """Cross-link memories that share sufficient classification tag overlap.

    Tags extracted from: classification values + bst_domain + area.
    Returns number of new link pairs created.
    """
    threshold = related_config.get("tag_overlap_threshold", 3)
    max_per = related_config.get("max_related_per_memory", 10)

    # Collect active memories with their tag sets
    tagged = []  # [(doc_id, doc, tag_set)]
    for doc_id, doc in all_docs.items():
        if not hasattr(doc, "metadata"):
            continue
        cls = doc.metadata.get(CLS_KEY, {})
        if cls.get("validity") == "deprecated":
            continue

        tags = _extract_tags(doc)
        if len(tags) < threshold:
            continue  # Can't possibly meet threshold
        tagged.append((doc_id, doc, tags))

    links_created = 0

    # Compare pairs — cap total work
    for i in range(len(tagged)):
        if links_created >= max_per * 10:
            break

        id_a, doc_a, tags_a = tagged[i]

        for j in range(i + 1, len(tagged)):
            id_b, doc_b, tags_b = tagged[j]

            overlap = len(tags_a & tags_b)
            if overlap < threshold:
                continue

            added_a = _add_related_id(doc_a, id_b, max_per)
            added_b = _add_related_id(doc_b, id_a, max_per)

            if added_a or added_b:
                links_created += 1

    return links_created


def _extract_tags(doc) -> set:
    """Extract tag set from a memory's metadata for overlap comparison.

    Tags = {validity, relevance, utility, source, bst_domain, area}.
    """
    tags = set()
    cls = doc.metadata.get(CLS_KEY, {})
    lin = doc.metadata.get(LIN_KEY, {})

    for key in ("validity", "relevance", "utility", "source"):
        val = cls.get(key)
        if val:
            tags.add(val)

    bst_domain = lin.get("bst_domain", "")
    if bst_domain:
        tags.add(bst_domain)

    area = doc.metadata.get("area", "")
    if area:
        tags.add(area)

    return tags


def _add_related_id(doc, related_id: str, max_per: int) -> bool:
    """Add related_id to doc's lineage.related_memory_ids. Returns True if new."""
    if not hasattr(doc, "metadata"):
        return False

    lin = doc.metadata.get(LIN_KEY)
    if not lin:
        lin = {}
        doc.metadata[LIN_KEY] = lin

    if "related_memory_ids" not in lin:
        lin["related_memory_ids"] = []

    rids = lin["related_memory_ids"]
    if related_id in rids:
        return False

    if len(rids) >= max_per:
        return False

    rids.append(related_id)
    return True


# ── Phase 3: Cluster Candidate Detection ─────────────────────────────────────

def _detect_cluster_candidates() -> int:
    """Scan co-retrieval log for frequently co-occurring memory pairs.

    Returns count of new cluster candidates found.
    """
    try:
        if not os.path.isfile(CO_RETRIEVAL_LOG):
            return 0
        with open(CO_RETRIEVAL_LOG, "r", encoding="utf-8") as f:
            log_data = json.load(f)
    except Exception:
        return 0

    entries = log_data.get("entries", [])
    if not entries:
        return 0

    pair_counts = Counter()
    pair_first_seen = {}
    pair_last_seen = {}

    for entry in entries:
        ids = entry.get("memory_ids", [])
        ts = entry.get("timestamp", "")
        if len(ids) < 2:
            continue
        for id_a, id_b in combinations(sorted(set(ids)), 2):
            pair = (id_a, id_b)
            pair_counts[pair] += 1
            if pair not in pair_first_seen:
                pair_first_seen[pair] = ts
            pair_last_seen[pair] = ts

    existing_candidates = {
        tuple(sorted(c.get("memory_ids", [])))
        for c in log_data.get("cluster_candidates", [])
        if len(c.get("memory_ids", [])) == 2
    }

    new_candidates = []
    for pair, count in pair_counts.items():
        if count >= CLUSTER_THRESHOLD and pair not in existing_candidates:
            new_candidates.append({
                "memory_ids": list(pair),
                "co_retrieval_count": count,
                "first_seen": pair_first_seen.get(pair, ""),
                "last_seen": pair_last_seen.get(pair, ""),
            })

    # Update existing candidates' counts regardless
    for c in log_data.get("cluster_candidates", []):
        cids = tuple(sorted(c.get("memory_ids", [])))
        if cids in pair_counts:
            c["co_retrieval_count"] = pair_counts[cids]
            c["last_seen"] = pair_last_seen.get(
                cids, c.get("last_seen", ""),
            )

    if new_candidates:
        candidates = log_data.get("cluster_candidates", [])
        candidates.extend(new_candidates)
        log_data["cluster_candidates"] = candidates

    # Write back (even if only updating counts)
    try:
        with open(CO_RETRIEVAL_LOG, "w", encoding="utf-8") as f:
            json.dump(log_data, f, indent=2)
    except Exception:
        pass

    return len(new_candidates)


# ── Phase 4: Dormancy Check ─────────────────────────────────────────────────

def _check_dormancy(
    all_docs: dict, current_cycle: int, archival_threshold: int,
) -> int:
    """Flag memories with access_count == 0 after N cycles as dormancy candidates.

    Log only — does not auto-reclassify.
    """
    dormant_count = 0

    for doc_id, doc in all_docs.items():
        if not hasattr(doc, "metadata"):
            continue

        cls = doc.metadata.get(CLS_KEY)
        lin = doc.metadata.get(LIN_KEY)
        if not cls or not lin:
            continue

        if cls.get("validity") == "deprecated":
            continue
        if cls.get("relevance") == "dormant":
            continue
        if cls.get("utility") == "load_bearing":
            continue

        # Already flagged
        if lin.get("dormancy_candidate"):
            continue

        access_count = lin.get("access_count", 0)
        if access_count > 0:
            continue

        classified_at = lin.get("classified_at_cycle", 0)
        cycles_elapsed = current_cycle - classified_at

        if cycles_elapsed >= archival_threshold:
            lin["dormancy_candidate"] = True
            lin["dormancy_flagged_at_cycle"] = current_cycle
            dormant_count += 1

    return dormant_count


# ── Ontology Hook ────────────────────────────────────────────────────────────

def _run_ontology_hook(all_docs: dict):
    """Promote Layer 10b related_memory_ids to typed relationships in ontology.

    Only runs if ontology layer is installed and enabled.
    Silently skips if ontology_config.json is absent.
    """
    try:
        ont_config_path = "/a0/usr/ontology/ontology_config.json"
        if not os.path.isfile(ont_config_path):
            return

        with open(ont_config_path, "r", encoding="utf-8") as f:
            ont_cfg = json.load(f)

        if not ont_cfg.get("relationship_extraction", {}).get("promote_memory_links", True):
            return

        # Collect ontology entity docs
        ontology_docs = [
            doc for doc in all_docs.values()
            if hasattr(doc, "metadata") and doc.metadata.get("area") == "ontology"
        ]
        if not ontology_docs:
            return

        import sys
        ontology_dir = "/a0/usr/ontology"
        if ontology_dir not in sys.path:
            sys.path.insert(0, ontology_dir)

        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "relationship_extractor",
            os.path.join(ontology_dir, "relationship_extractor.py"),
        )
        if spec is None:
            return
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        rels = module.promote_memory_links(ontology_docs)
        if rels:
            min_conf = ont_cfg.get("relationship_extraction", {}).get(
                "min_confidence_to_surface", 0.3
            )
            stored = module.store_relationships(rels, min_confidence=min_conf)
            if stored > 0:
                print(f"[MEM-MAINT] Promoted {stored} memory links to typed relationships", flush=True)

    except Exception as e:
        print(f"[MEM-MAINT] Ontology hook error (passthrough): {e}", flush=True)


# ── Config Loading ───────────────────────────────────────────────────────────

def _load_config() -> dict:
    """Load classification config with defaults."""
    try:
        if os.path.isfile(CONFIG_PATH):
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                user_config = json.load(f)
            merged = dict(DEFAULT_CONFIG)
            merged.update(user_config)
            return merged
    except Exception:
        pass
    return dict(DEFAULT_CONFIG)
