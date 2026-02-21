"""
Memory Enhancement — Agent-Zero Hardening Layer
=================================================
Hook: message_loop_prompts_after
Priority: _56 (runs AFTER _55_memory_relevance_filter)

Six-stage retrieval pipeline per turn:
  1. Query Expansion: 3 FAISS queries (original, keyword, domain-scoped),
     merged by memory ID keeping highest similarity per document.
  2. Temporal Decay: exponential recency blended with similarity; exempt
     memories (load_bearing, user_asserted, confirmed) bypass decay.
  3. Related Memory Boost: preliminary top-k checked for related IDs;
     linked memories in the broader pool receive a score boost.
  4. Top-K Selection: final cap from model profile or config.
  5. Access Tracking: access_count += 1, last_accessed = utcnow().
  6. Co-Retrieval Logging: append to /a0/usr/memory/co_retrieval_log.json.

Formula:
  recency_score = exp(-decay_rate * age_in_hours)
  decay_rate    = ln(2) / half_life_hours
  final_score   = (1 - decay_weight) * similarity + decay_weight * recency

Reads:
  - query_expansion, temporal_decay, related_memories config sections
  - memory section from active model profile (if available)
  - BST domain classification from agent._bst_store
Writes:
  - loop_data.extras_persistent["memories"], ["solutions"]
  - Document.metadata lineage (access_count, last_accessed)
  - /a0/usr/memory/co_retrieval_log.json
"""

import json
import math
import os
import re
from datetime import datetime, timezone
from typing import Any

from agent import LoopData
from python.helpers.extension import Extension
from python.helpers.memory import Memory

# ── Configuration ────────────────────────────────────────────────────────────

CONFIG_PATH = "/a0/usr/memory/classification_config.json"
PROFILE_DIR = "/a0/usr/model_profiles"
CO_RETRIEVAL_LOG = "/a0/usr/memory/co_retrieval_log.json"
MAX_CO_RETRIEVAL_ENTRIES = 500

DEFAULT_CONFIG = {
    "load_bearing_keywords": [
        "must", "always", "never", "requirement", "constraint",
        "critical", "essential", "mandatory", "do not", "required",
    ],
    "max_injected_memories": 8,
}

DEFAULT_QE_CONFIG = {
    "enabled": True,
    "retrieval_k_per_variant": 8,
    "use_domain_scoping": True,
    "use_keyword_extraction": True,
    "max_keywords": 12,
}

DEFAULT_DECAY_CONFIG = {
    "enabled": True,
    "decay_weight": 0.15,
    "half_life_hours": 168,
    "exempt_utilities": ["load_bearing"],
    "exempt_sources": ["user_asserted"],
    "exempt_validities": ["confirmed"],
    "min_recency_score": 0.1,
}

DEFAULT_RELATED_CONFIG = {
    "enabled": True,
    "tag_overlap_threshold": 3,
    "related_boost": 0.08,
    "max_related_per_memory": 10,
    "rebuild_interval_cycles": 25,
}

# Metadata keys (must match _55_memory_classifier.py)
CLS_KEY = "classification"
LIN_KEY = "lineage"

# BST access keys (must match _10_belief_state_tracker.py)
BST_STORE_KEY = "_bst_store"
BST_BELIEF_KEY = "__bst_belief_state__"

# Utility rank for sorting (higher = more important)
_UTILITY_ORDER = {"load_bearing": 2, "tactical": 1, "archived": 0}

# Role directory for domain overlap checks
ROLES_DIR = "/a0/usr/organizations/roles"

# ── Stopwords for keyword extraction ─────────────────────────────────────────

STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been",
    "being", "have", "has", "had", "do", "does", "did", "will",
    "would", "could", "should", "may", "might", "shall", "can",
    "to", "of", "in", "for", "on", "with", "at", "by", "from",
    "it", "this", "that", "these", "those", "i", "you", "he",
    "she", "we", "they", "me", "him", "her", "us", "them",
    "my", "your", "his", "its", "our", "their", "and", "or",
    "but", "not", "no", "if", "then", "so", "just", "about",
    "up", "out", "how", "what", "when", "where", "who", "which",
    "there", "here", "all", "each", "some", "any", "into", "as",
}


class MemoryEnhancement(Extension):
    """Six-stage memory retrieval: expand -> decay -> boost -> select -> track -> log."""

    async def execute(self, loop_data: LoopData = LoopData(), **kwargs) -> Any:
        try:
            print("[MEM-ENHANCE] execute() called", flush=True)
            if loop_data.extras_persistent is None:
                loop_data.extras_persistent = {}
            extras = loop_data.extras_persistent
            has_solutions = "solutions" in extras

            config = _load_config()
            qe_config = config.get("query_expansion", DEFAULT_QE_CONFIG)
            decay_config = config.get("temporal_decay", DEFAULT_DECAY_CONFIG)
            related_config = config.get("related_memories", DEFAULT_RELATED_CONFIG)

            db = await Memory.get(self.agent)
            if not db or not db.db:
                return

            all_docs = db.db.get_all_docs()
            if not all_docs:
                return

            # ── Load thresholds ───────────────────────────────────────────
            max_injected = config.get("max_injected_memories", 8)
            sim_threshold = 0.3
            try:
                sim_threshold = self.agent.config.memory_recall_similarity_threshold
            except Exception:
                pass

            profile_mem = _load_profile_memory_section()
            if profile_mem:
                max_injected = profile_mem.get("max_injected", max_injected)
                prof_thresh = profile_mem.get("similarity_threshold")
                if prof_thresh is not None and prof_thresh > sim_threshold:
                    sim_threshold = prof_thresh

            # ── Role domains for filtering ────────────────────────────────
            role = getattr(self.agent, "_org_active_role", None)
            role_domains = []
            if role:
                role_domains = role.get("capabilities", {}).get(
                    "bst_domains", []
                )

            # ── BST domain ────────────────────────────────────────────────
            bst_domain = _get_bst_domain(self.agent)

            # ── Maintenance cycle (for co-retrieval logging) ──────────────
            maint_cycle = getattr(
                self.agent, "_memory_maintenance_counter", 0
            )

            query = _get_query(loop_data)
            if not query:
                print("[MEM-ENHANCE] No user message found, skipping", flush=True)
                return
            print(f"[MEM-ENHANCE] User message: {query[:50]!r}", flush=True)

            all_injected_ids = []

            # ── Process memories (main + fragments + ontology entities) ───
            try:
                result = await _run_pipeline(
                    db, all_docs, query, bst_domain, role_domains,
                    sim_threshold, max_injected,
                    "area == 'main' or area == 'fragments' or area == 'ontology'",
                    qe_config, decay_config, related_config,
                )

                if result:
                    txt = "\n\n".join(
                        getattr(doc, "page_content", "")
                        for doc, _ in result
                    )
                    try:
                        extras["memories"] = self.agent.parse_prompt(
                            "agent.system.memories.md", memories=txt,
                        )
                    except Exception:
                        extras["memories"] = (
                            f"# Recalled Memories\n\n{txt}"
                        )

                    ids = _update_access(result, all_docs)
                    all_injected_ids.extend(ids)
                    print(f"[MEM-ENHANCE] Final selection: {len(ids)} memories injected", flush=True)
                else:
                    extras.pop("memories", None)
                    print("[MEM-ENHANCE] Final selection: 0 memories injected", flush=True)
            except Exception as mem_err:
                print(f"[MEM-ENHANCE] Memories pipeline error: {mem_err}", flush=True)

            # ── Process solutions ─────────────────────────────────────────
            if has_solutions:
                try:
                    sol_cap = max(2, max_injected // 2)
                    result = await _run_pipeline(
                        db, all_docs, query, bst_domain, role_domains,
                        sim_threshold, sol_cap,
                        "area == 'solutions'",
                        qe_config, decay_config, related_config,
                    )

                    if result:
                        txt = "\n\n".join(
                            getattr(doc, "page_content", "")
                            for doc, _ in result
                        )
                        try:
                            extras["solutions"] = self.agent.parse_prompt(
                                "agent.system.solutions.md", solutions=txt,
                            )
                        except Exception:
                            extras["solutions"] = (
                                f"# Recalled Solutions\n\n{txt}"
                            )

                        ids = _update_access(result, all_docs)
                        all_injected_ids.extend(ids)
                    else:
                        del extras["solutions"]
                except Exception:
                    pass

            # ── Persist access updates ────────────────────────────────────
            if all_injected_ids:
                try:
                    db._save_db()
                except Exception:
                    pass

            # ── Co-retrieval logging ──────────────────────────────────────
            if all_injected_ids:
                _log_co_retrieval(
                    all_injected_ids, bst_domain, maint_cycle,
                )
                print("[MEM-ENHANCE] Co-retrieval logged", flush=True)

        except Exception as e:
            try:
                self.agent.context.log.log(
                    type="warning",
                    content=f"[MEM-ENHANCE] Error (passthrough): {e}",
                )
            except Exception:
                pass


# ── Full Pipeline ────────────────────────────────────────────────────────────

async def _run_pipeline(
    db, all_docs, query, bst_domain, role_domains,
    sim_threshold, max_injected, area_filter,
    qe_config, decay_config, related_config,
) -> list[tuple]:
    """Run the 4-stage scoring pipeline: expand -> decay -> boost -> select.

    Returns [(doc, final_score)] for injection.
    """
    # Stage 1: Query Expansion
    merged = await _query_expansion_search(
        db, query, bst_domain, sim_threshold, qe_config, area_filter,
    )
    print(f"[MEM-ENHANCE] Query expansion: {len(merged)} candidates from 3 queries", flush=True)
    if not merged:
        return []

    # Stage 2: Filter + Temporal Decay
    scored = _filter_and_decay(
        merged, all_docs, role_domains, decay_config,
    )
    print(f"[MEM-ENHANCE] After decay: {len(scored)} candidates", flush=True)
    if not scored:
        return []

    # Stage 3: Related Memory Boost
    scored = _apply_related_boost(
        scored, all_docs, max_injected, related_config,
    )

    # Stage 4: Top-K Selection
    return [(doc, score) for doc, score, _ in scored[:max_injected]]


# ── Stage 1: Query Expansion ─────────────────────────────────────────────────

async def _query_expansion_search(
    db, query, bst_domain, threshold, qe_config, area_filter,
) -> list[tuple]:
    """Run multi-variant FAISS queries and merge by memory ID.

    Returns [(doc, max_similarity_score)] with duplicates merged.
    """
    if not qe_config.get("enabled", True):
        # Single query fallback
        results = await db.search_similarity_threshold(
            query=query, limit=50, threshold=threshold,
            filter=area_filter,
        )
        return _unpack_results(results)

    k = qe_config.get("retrieval_k_per_variant", 8)
    max_kw = qe_config.get("max_keywords", 12)

    # Generate query variants
    queries = [query]  # 1. original

    if qe_config.get("use_keyword_extraction", True):
        kw_query = extract_keywords(query, max_kw)
        if kw_query and kw_query.strip() != query.lower().strip():
            queries.append(kw_query)  # 2. keyword-only

    if qe_config.get("use_domain_scoping", True) and bst_domain:
        kw_for_domain = extract_keywords(query, max_kw) or query
        domain_query = f"{bst_domain}: {kw_for_domain}"
        queries.append(domain_query)  # 3. domain-scoped

    # Run searches and merge by memory ID, keeping highest score
    merged = {}  # doc_id -> (doc, max_score)
    for q in queries:
        try:
            results = await db.search_similarity_threshold(
                query=q, limit=k, threshold=threshold,
                filter=area_filter,
            )
        except Exception:
            continue

        for item in results:
            doc, score = item if isinstance(item, tuple) else (item, 1.0)
            if not hasattr(doc, "metadata"):
                continue
            doc_id = doc.metadata.get("id", "")
            if not doc_id:
                continue
            if doc_id not in merged or score > merged[doc_id][1]:
                merged[doc_id] = (doc, score)

    return list(merged.values())


def _unpack_results(results) -> list[tuple]:
    """Unpack search results into [(doc, score)]."""
    unpacked = []
    for item in results:
        doc, score = item if isinstance(item, tuple) else (item, 1.0)
        if hasattr(doc, "metadata"):
            unpacked.append((doc, score))
    return unpacked


def extract_keywords(text: str, max_keywords: int = 12) -> str:
    """Deterministic keyword extraction: remove stopwords, cap at N terms."""
    words = re.findall(r"\b\w+\b", text.lower())
    keywords = [w for w in words if w not in STOPWORDS and len(w) > 2]
    return " ".join(keywords[:max_keywords])


# ── Stage 2: Filter + Temporal Decay ─────────────────────────────────────────

def _filter_and_decay(
    merged_pool: list[tuple],
    all_docs: dict,
    role_domains: list,
    decay_config: dict,
) -> list[tuple]:
    """Apply validity/role filters and temporal decay scoring.

    Returns [(doc, blended_score, utility_rank)] sorted descending.
    """
    decay_enabled = decay_config.get("enabled", True)
    decay_weight = decay_config.get("decay_weight", 0.15)
    scored = []

    for doc, sim_score in merged_pool:
        cls = doc.metadata.get(CLS_KEY, {})
        lin = doc.metadata.get(LIN_KEY, {})

        # Validity filter: exclude deprecated
        if cls.get("validity") == "deprecated":
            continue

        # Role-relevance filter
        utility = cls.get("utility", "tactical")
        if role_domains and utility != "load_bearing":
            mem_domain = lin.get("bst_domain", "")
            if mem_domain and mem_domain not in role_domains:
                continue
            if not mem_domain:
                created_by = lin.get("created_by_role")
                if created_by and not _role_domain_overlaps(
                    created_by, role_domains
                ):
                    continue

        # Temporal decay
        if decay_enabled:
            recency = _calc_recency_score(doc.metadata, decay_config)
            blended = (
                (1 - decay_weight) * sim_score + decay_weight * recency
            )
        else:
            blended = sim_score

        utility_rank = _UTILITY_ORDER.get(utility, 0)
        scored.append((doc, blended, utility_rank))

    scored.sort(key=lambda x: (x[2], x[1]), reverse=True)
    return scored


def _calc_recency_score(doc_metadata: dict, decay_config: dict) -> float:
    """Exponential recency score. Returns 1.0 for exempt memories."""
    cls = doc_metadata.get(CLS_KEY, {})
    lin = doc_metadata.get(LIN_KEY, {})

    # Exemption checks
    if cls.get("utility") in decay_config.get("exempt_utilities", []):
        return 1.0
    if cls.get("source") in decay_config.get("exempt_sources", []):
        return 1.0
    if cls.get("validity") in decay_config.get("exempt_validities", []):
        return 1.0

    # Age calculation: prefer last_accessed, fallback created_at, timestamp
    time_ref = (
        lin.get("last_accessed")
        or lin.get("created_at")
        or doc_metadata.get("timestamp")
    )
    if not time_ref:
        return 1.0

    try:
        ref_dt = datetime.fromisoformat(time_ref)
        if ref_dt.tzinfo is None:
            ref_dt = ref_dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        age_hours = max(0, (now - ref_dt).total_seconds() / 3600)
    except Exception:
        return 1.0

    half_life = decay_config.get("half_life_hours", 168)
    if half_life <= 0:
        return 1.0

    decay_rate = math.log(2) / half_life
    recency = math.exp(-decay_rate * age_hours)

    min_score = decay_config.get("min_recency_score", 0.1)
    return max(min_score, recency)


# ── Stage 3: Related Memory Boost ────────────────────────────────────────────

def _apply_related_boost(
    scored: list[tuple],
    all_docs: dict,
    max_injected: int,
    related_config: dict,
) -> list[tuple]:
    """Boost near-cutoff memories that are linked to top-k selections.

    Returns re-sorted scored list.
    """
    if not related_config.get("enabled", True):
        return scored

    if len(scored) <= max_injected:
        return scored  # Everything fits, no boosting needed

    boost = related_config.get("related_boost", 0.08)

    # Collect related IDs from preliminary top-k
    related_ids = set()
    for doc, _, _ in scored[:max_injected]:
        if not hasattr(doc, "metadata"):
            continue
        lin = doc.metadata.get(LIN_KEY, {})
        rids = lin.get("related_memory_ids", [])
        if isinstance(rids, list):
            related_ids.update(rids)

    if not related_ids:
        return scored

    # Boost related memories that are below the cutoff
    boosted = False
    for i in range(max_injected, len(scored)):
        doc, score, util_rank = scored[i]
        if not hasattr(doc, "metadata"):
            continue
        doc_id = doc.metadata.get("id", "")
        if doc_id in related_ids:
            scored[i] = (doc, score + boost, util_rank)
            boosted = True

    if boosted:
        scored.sort(key=lambda x: (x[2], x[1]), reverse=True)

    return scored


# ── BST Domain Access ────────────────────────────────────────────────────────

def _get_bst_domain(agent) -> str:
    """Get current BST domain classification from agent context."""
    try:
        store = getattr(agent, BST_STORE_KEY, {})
        belief = store.get(BST_BELIEF_KEY)
        return belief.get("domain", "") if belief else ""
    except Exception:
        return ""


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


# ── Role Domain Check ────────────────────────────────────────────────────────

def _role_domain_overlaps(
    created_by_role: str, current_domains: list,
) -> bool:
    """Check if the creating role's domains overlap with current role."""
    try:
        path = os.path.join(ROLES_DIR, f"{created_by_role}.json")
        if not os.path.isfile(path):
            return True
        with open(path, "r", encoding="utf-8") as f:
            profile = json.load(f)
        creator_domains = profile.get(
            "capabilities", {}
        ).get("bst_domains", [])
        return bool(set(creator_domains) & set(current_domains))
    except Exception:
        return True


# ── Access Tracking ──────────────────────────────────────────────────────────

def _update_access(
    filtered_results: list[tuple], all_docs: dict,
) -> list[str]:
    """Increment access_count on injected memories. Returns list of IDs."""
    now = datetime.now(timezone.utc).isoformat()
    injected_ids = []

    for doc, _ in filtered_results:
        if not hasattr(doc, "metadata"):
            continue
        doc_id = doc.metadata.get("id", "")
        if not doc_id:
            continue

        injected_ids.append(doc_id)

        # Update ORIGINAL document in docstore (not the search copy)
        original = all_docs.get(doc_id)
        if not original or not hasattr(original, "metadata"):
            continue

        lin = original.metadata.get(LIN_KEY)
        if not lin:
            lin = {
                "created_at": original.metadata.get("timestamp", now),
                "created_by_role": None,
                "bst_domain": "",
                "classified_at_cycle": 0,
                "supersedes": None,
                "superseded_by": None,
                "access_count": 0,
                "last_accessed": None,
                "related_memory_ids": [],
            }
            original.metadata[LIN_KEY] = lin

        lin["access_count"] = lin.get("access_count", 0) + 1
        lin["last_accessed"] = now

    return injected_ids


# ── Co-Retrieval Logging ─────────────────────────────────────────────────────

def _log_co_retrieval(
    memory_ids: list[str], query_domain: str, cycle: int,
):
    """Append co-retrieval entry. FIFO eviction at max_entries."""
    if len(memory_ids) < 2:
        return

    log_data = {"max_entries": MAX_CO_RETRIEVAL_ENTRIES, "entries": []}
    try:
        if os.path.isfile(CO_RETRIEVAL_LOG):
            with open(CO_RETRIEVAL_LOG, "r", encoding="utf-8") as f:
                log_data = json.load(f)
    except Exception:
        pass

    entries = log_data.get("entries", [])
    max_entries = log_data.get("max_entries", MAX_CO_RETRIEVAL_ENTRIES)

    entries.append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "query_domain": query_domain,
        "memory_ids": memory_ids,
        "cycle": cycle,
    })

    if len(entries) > max_entries:
        entries = entries[-max_entries:]

    log_data["entries"] = entries
    if "cluster_candidates" not in log_data:
        log_data["cluster_candidates"] = []

    try:
        os.makedirs(os.path.dirname(CO_RETRIEVAL_LOG), exist_ok=True)
        with open(CO_RETRIEVAL_LOG, "w", encoding="utf-8") as f:
            json.dump(log_data, f, indent=2)
    except Exception:
        pass


# ── Model Profile Loading ────────────────────────────────────────────────────

def _load_profile_memory_section() -> dict:
    """Load memory section from active model profile."""
    try:
        if not os.path.isdir(PROFILE_DIR):
            return {}
        default = os.path.join(PROFILE_DIR, "default.json")
        profile_path = default
        for name in os.listdir(PROFILE_DIR):
            if name != "default.json" and name.endswith(".json"):
                profile_path = os.path.join(PROFILE_DIR, name)
                break
        if not os.path.isfile(profile_path):
            return {}
        with open(profile_path, "r", encoding="utf-8") as f:
            profile = json.load(f)
        return profile.get("memory", {})
    except Exception:
        return {}


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
