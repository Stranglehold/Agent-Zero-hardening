"""
Memory Maintenance — Agent-Zero Hardening Layer
=================================================
Hook: monologue_end
Priority: _57 (runs AFTER _55_memory_classifier)

Periodic maintenance on the memory index:
  1. Deduplication: identify memory pairs with cosine similarity > threshold.
     Resolution rules:
       - Both agent_inferred -> deprecate older with superseded_by pointer
       - One user_asserted  -> keep user, deprecate other
       - One confirmed      -> keep confirmed, deprecate other
       - Both user_asserted -> flag only, no auto-action
       - load_bearing       -> never auto-deprecate (flag for review)
     Capped at max_pairs_per_cycle to limit compute.

  2. Cluster candidate detection: read co_retrieval_log.json, find memory
     ID pairs that co-occur > cluster_threshold times, write results to
     cluster_candidates array in the same file.

Runs expensive operations only every maintenance_interval_loops cycles,
following the same cycle-counter pattern as _55_memory_classifier.py.

Reads:
  - deduplication config from /a0/usr/memory/classification_config.json
  - /a0/usr/memory/co_retrieval_log.json for co-retrieval data
Writes:
  - Document.metadata (deprecation, superseded_by pointers)
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
}

DEFAULT_DEDUP_CONFIG = {
    "enabled": True,
    "similarity_threshold": 0.90,
    "auto_deprecate_agent_inferred": True,
    "max_pairs_per_cycle": 20,
    "log_all_candidates": True,
}

CLUSTER_THRESHOLD = 5  # Min co-occurrences to become a cluster candidate

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
    """Periodic deduplication and cluster detection."""

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

            # ── Phase 2: Cluster candidate detection ──────────────────────
            cluster_count = _detect_cluster_candidates()
            if cluster_count > 0:
                self.agent.context.log.log(
                    type="info",
                    content=(
                        f"[MEM-MAINT] Found {cluster_count} "
                        f"cluster candidates"
                    ),
                )

            # ── Persist changes ───────────────────────────────────────────
            if changed:
                try:
                    db._save_db()
                except Exception:
                    pass

        except Exception as e:
            try:
                self.agent.context.log.log(
                    type="warning",
                    content=f"[MEM-MAINT] Error (passthrough): {e}",
                )
            except Exception:
                pass


# ── Deduplication ────────────────────────────────────────────────────────────

async def _run_deduplication(
    db, all_docs: dict, dedup_config: dict,
) -> int:
    """Scan for duplicate memory pairs and resolve.

    Returns count of pairs resolved.
    """
    threshold = dedup_config.get("similarity_threshold", 0.90)
    max_pairs = dedup_config.get("max_pairs_per_cycle", 20)
    auto_deprecate = dedup_config.get(
        "auto_deprecate_agent_inferred", True,
    )

    processed_pairs = set()
    resolved_count = 0

    # Iterate over classified, non-deprecated memories
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

        # Search for similar memories
        try:
            results = await db.search_similarity_threshold(
                query=text,
                limit=6,
                threshold=threshold,
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

            # Skip self-match
            if sim_id == doc_id or not sim_id:
                continue

            # Skip already processed pair (order-independent)
            pair_key = tuple(sorted([doc_id, sim_id]))
            if pair_key in processed_pairs:
                continue
            processed_pairs.add(pair_key)

            # Skip if either is already deprecated
            sim_cls = sim_doc.metadata.get(CLS_KEY, {})
            if sim_cls.get("validity") == "deprecated":
                continue

            doc_cls = doc.metadata.get(CLS_KEY, {})

            # ── Apply resolution rules ────────────────────────────────
            action = _determine_resolution(
                doc_id, doc_cls, doc.metadata,
                sim_id, sim_cls, sim_doc.metadata,
                auto_deprecate,
            )

            if action == "skip":
                continue

            if action == "flag_only":
                # Log but don't auto-deprecate
                continue

            loser_id, winner_id = action

            # Deprecate loser
            _deprecate_memory(all_docs, loser_id, winner_id)
            resolved_count += 1

    return resolved_count


def _determine_resolution(
    id_a: str, cls_a: dict, meta_a: dict,
    id_b: str, cls_b: dict, meta_b: dict,
    auto_deprecate: bool,
) -> Any:
    """Determine deduplication resolution.

    Returns:
        "skip"       — don't process
        "flag_only"  — both user_asserted or load_bearing involved
        (loser, winner) tuple — deprecate loser
    """
    source_a = cls_a.get("source", "agent_inferred")
    source_b = cls_b.get("source", "agent_inferred")
    utility_a = cls_a.get("utility", "tactical")
    utility_b = cls_b.get("utility", "tactical")
    validity_a = cls_a.get("validity", "inferred")
    validity_b = cls_b.get("validity", "inferred")

    # Rule: load_bearing — never auto-deprecate, flag for review
    if utility_a == "load_bearing" or utility_b == "load_bearing":
        return "flag_only"

    # Rule: both user_asserted — flag only, no action
    if source_a == "user_asserted" and source_b == "user_asserted":
        return "flag_only"

    # Rule: one user_asserted — keep user, deprecate other
    if source_a == "user_asserted" and source_b != "user_asserted":
        return (id_b, id_a)  # B loses, A (user) wins
    if source_b == "user_asserted" and source_a != "user_asserted":
        return (id_a, id_b)  # A loses, B (user) wins

    # Rule: one confirmed — keep confirmed, deprecate other
    if validity_a == "confirmed" and validity_b != "confirmed":
        return (id_b, id_a)
    if validity_b == "confirmed" and validity_a != "confirmed":
        return (id_a, id_b)

    # Rule: both agent_inferred — deprecate older
    if (source_a == "agent_inferred" and source_b == "agent_inferred"
            and auto_deprecate):
        # Determine older by lineage timestamp
        ts_a = _get_created_at(meta_a)
        ts_b = _get_created_at(meta_b)
        if ts_a <= ts_b:
            return (id_a, id_b)  # A is older, deprecate A
        return (id_b, id_a)  # B is older, deprecate B

    # Default: skip (don't auto-resolve ambiguous cases)
    return "skip"


def _get_created_at(metadata: dict) -> str:
    """Extract creation timestamp from metadata."""
    lin = metadata.get(LIN_KEY, {})
    return (
        lin.get("created_at")
        or metadata.get("timestamp", "")
    )


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
        # Don't overwrite existing supersedes — may have multiple
        existing = winner.metadata[LIN_KEY].get("supersedes")
        if existing and existing != loser_id:
            # Store as list if multiple
            if isinstance(existing, list):
                if loser_id not in existing:
                    existing.append(loser_id)
            else:
                winner.metadata[LIN_KEY]["supersedes"] = [
                    existing, loser_id,
                ]
        else:
            winner.metadata[LIN_KEY]["supersedes"] = loser_id


# ── Cluster Candidate Detection ──────────────────────────────────────────────

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

    # Count co-occurrences of memory ID pairs
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

    # Find pairs exceeding threshold
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

    if not new_candidates:
        return 0

    # Update existing candidates' counts
    updated = []
    for c in log_data.get("cluster_candidates", []):
        cids = tuple(sorted(c.get("memory_ids", [])))
        if cids in pair_counts:
            c["co_retrieval_count"] = pair_counts[cids]
            c["last_seen"] = pair_last_seen.get(cids, c.get("last_seen", ""))
        updated.append(c)

    # Add new candidates
    updated.extend(new_candidates)
    log_data["cluster_candidates"] = updated

    # Write back
    try:
        with open(CO_RETRIEVAL_LOG, "w", encoding="utf-8") as f:
            json.dump(log_data, f, indent=2)
    except Exception:
        pass

    return len(new_candidates)


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
