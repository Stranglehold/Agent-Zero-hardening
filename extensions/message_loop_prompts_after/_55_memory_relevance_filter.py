"""
Memory Relevance Filter — Agent-Zero Hardening Layer
=====================================================
Hook: message_loop_prompts_after
Priority: _55 (runs AFTER _50_recall_memories)

Post-processes recalled memories by applying classification-based filters:
  1. Validity filter: Exclude deprecated memories entirely
  2. Role-relevance filter: Suppress memories from non-overlapping BST
     domains (unless load_bearing)
  3. Utility ranking: load_bearing > tactical > archived, then by
     access_count descending
  4. Cap total injected memories at configurable limit

Also handles:
  - Access tracking: increment access_count and last_accessed on injected
    memories for archival lifecycle
  - Graceful degradation: if no org active, skip role filtering and apply
    only validity + utility ranking

Reads: agent._org_active_role (from org dispatcher)
Writes: loop_data.extras_persistent["memories"], ["solutions"]
"""

import json
import os
from datetime import datetime, timezone
from typing import Any

from agent import LoopData
from python.helpers.extension import Extension
from python.helpers.memory import Memory

# ── Configuration ────────────────────────────────────────────────────────────

CONFIG_PATH = "/a0/usr/memory/classification_config.json"

DEFAULT_CONFIG = {
    "load_bearing_keywords": [
        "must", "always", "never", "requirement", "constraint",
        "critical", "essential", "mandatory", "do not", "required",
    ],
    "archival_threshold_cycles": 50,
    "deprecation_retention_cycles": 100,
    "max_injected_memories": 8,
    "maintenance_interval_loops": 25,
    "conflict_top_k": 5,
    "enable_purge": False,
}

# Metadata keys (must match _55_memory_classifier.py)
CLS_KEY = "classification"
LIN_KEY = "lineage"

# Utility rank for sorting (higher = more important)
_UTILITY_ORDER = {"load_bearing": 2, "tactical": 1, "archived": 0}


class MemoryRelevanceFilter(Extension):
    """Role-aware memory filter with classification-based ranking."""

    async def execute(self, loop_data: LoopData = LoopData(), **kwargs) -> Any:
        try:
            extras = loop_data.extras_persistent
            if not extras:
                return

            has_memories = "memories" in extras
            has_solutions = "solutions" in extras
            if not has_memories and not has_solutions:
                return  # Recall didn't run this iteration

            config = _load_config()
            db = await Memory.get(self.agent)
            if not db or not db.db:
                return

            all_docs = db.db.get_all_docs()
            if not all_docs:
                return

            max_injected = config.get("max_injected_memories", 8)

            # Get current role for relevance filtering
            role = getattr(self.agent, "_org_active_role", None)
            role_domains = []
            if role:
                role_domains = role.get("capabilities", {}).get("bst_domains", [])

            # Build search query from user message
            query = _get_query(loop_data)
            if not query:
                return  # Can't search without query

            # Get similarity threshold from agent config
            threshold = 0.3
            try:
                threshold = self.agent.config.memory_recall_similarity_threshold
            except Exception:
                pass

            # ── Filter memories (main + fragments) ───────────────────────
            if has_memories:
                try:
                    raw = await db.search_similarity_threshold(
                        query=query,
                        limit=50,
                        threshold=threshold,
                        filter="area == 'main' or area == 'fragments'",
                    )
                    filtered = _filter_and_rank(raw, all_docs, role_domains, max_injected)

                    if filtered:
                        txt = "\n\n".join(
                            getattr(doc, "page_content", "")
                            for doc, _ in filtered
                        )
                        try:
                            extras["memories"] = self.agent.parse_prompt(
                                "agent.system.memories.md", memories=txt,
                            )
                        except Exception:
                            extras["memories"] = f"# Recalled Memories\n\n{txt}"

                        _update_access(filtered, all_docs)
                    else:
                        del extras["memories"]
                except Exception:
                    pass  # Keep original recall on error

            # ── Filter solutions ─────────────────────────────────────────
            if has_solutions:
                try:
                    raw = await db.search_similarity_threshold(
                        query=query,
                        limit=20,
                        threshold=threshold,
                        filter="area == 'solutions'",
                    )
                    sol_cap = max(2, max_injected // 2)
                    filtered = _filter_and_rank(raw, all_docs, role_domains, sol_cap)

                    if filtered:
                        txt = "\n\n".join(
                            getattr(doc, "page_content", "")
                            for doc, _ in filtered
                        )
                        try:
                            extras["solutions"] = self.agent.parse_prompt(
                                "agent.system.solutions.md", solutions=txt,
                            )
                        except Exception:
                            extras["solutions"] = f"# Recalled Solutions\n\n{txt}"

                        _update_access(filtered, all_docs)
                    else:
                        del extras["solutions"]
                except Exception:
                    pass

            # Persist access count updates
            try:
                db._save_db()
            except Exception:
                pass

        except Exception as e:
            try:
                self.agent.context.log.log(
                    type="warning",
                    content=f"[MEM-FILTER] Error (passthrough): {e}",
                )
            except Exception:
                pass


# ── Query Extraction ─────────────────────────────────────────────────────────

def _get_query(loop_data) -> str:
    """Extract search query from loop data."""
    if hasattr(loop_data, "user_message") and loop_data.user_message:
        try:
            if hasattr(loop_data.user_message, "output_text"):
                return loop_data.user_message.output_text()
            return str(loop_data.user_message)
        except Exception:
            pass
    return ""


# ── Filter and Rank ──────────────────────────────────────────────────────────

def _filter_and_rank(
    search_results,
    all_docs: dict,
    role_domains: list,
    cap: int,
) -> list[tuple]:
    """Apply classification filters and rank. Returns [(doc, score)]."""
    scored = []

    for item in search_results:
        doc, sim_score = item if isinstance(item, tuple) else (item, 1.0)

        doc_id = doc.metadata.get("id", "") if hasattr(doc, "metadata") else ""
        cls = doc.metadata.get(CLS_KEY, {}) if hasattr(doc, "metadata") else {}
        lin = doc.metadata.get(LIN_KEY, {}) if hasattr(doc, "metadata") else {}

        # ── Validity filter: exclude deprecated ──────────────────────
        if cls.get("validity") == "deprecated":
            continue

        # ── Role-relevance filter ────────────────────────────────────
        utility = cls.get("utility", "tactical")

        if role_domains and utility != "load_bearing":
            # First check: memory's BST domain at creation time
            mem_domain = lin.get("bst_domain", "")
            if mem_domain and mem_domain not in role_domains:
                continue  # Domain mismatch, suppress

            # Second check: creator role's domain overlap
            if not mem_domain:
                created_by = lin.get("created_by_role")
                if created_by and not _role_domain_overlaps(
                    created_by, role_domains
                ):
                    continue  # Suppress non-overlapping

        # ── Score for ranking ────────────────────────────────────────
        utility_score = _UTILITY_ORDER.get(utility, 0)
        access_count = lin.get("access_count", 0)

        # Composite rank: utility class primary, access count secondary,
        # similarity score tertiary
        rank = (utility_score, access_count, sim_score)
        scored.append((doc, sim_score, rank))

    # Sort by rank descending
    scored.sort(key=lambda x: x[2], reverse=True)

    return [(doc, score) for doc, score, _ in scored[:cap]]


ROLES_DIR = "/a0/usr/organizations/roles"


def _role_domain_overlaps(created_by_role: str, current_domains: list) -> bool:
    """Check if the creating role's domains overlap with current role."""
    try:
        path = os.path.join(ROLES_DIR, f"{created_by_role}.json")
        if not os.path.isfile(path):
            return True  # Can't determine — don't suppress

        with open(path, "r", encoding="utf-8") as f:
            profile = json.load(f)

        creator_domains = profile.get("capabilities", {}).get("bst_domains", [])
        return bool(set(creator_domains) & set(current_domains))
    except Exception:
        return True  # On error, don't suppress


# ── Access Tracking ──────────────────────────────────────────────────────────

def _update_access(filtered_results: list[tuple], all_docs: dict):
    """Increment access_count on injected memories."""
    now = datetime.now(timezone.utc).isoformat()

    for doc, _ in filtered_results:
        doc_id = doc.metadata.get("id", "") if hasattr(doc, "metadata") else ""
        if not doc_id:
            continue

        # Update the ORIGINAL document in docstore (not the search copy)
        original = all_docs.get(doc_id)
        if not original or not hasattr(original, "metadata"):
            continue

        lin = original.metadata.get(LIN_KEY)
        if not lin:
            lin = {
                "created_at": original.metadata.get("timestamp", now),
                "created_by_role": None,
                "supersedes": None,
                "superseded_by": None,
                "access_count": 0,
                "last_accessed": None,
            }
            original.metadata[LIN_KEY] = lin

        lin["access_count"] = lin.get("access_count", 0) + 1
        lin["last_accessed"] = now


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
