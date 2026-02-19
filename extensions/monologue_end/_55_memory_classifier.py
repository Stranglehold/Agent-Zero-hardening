"""
Memory Classification Engine — Agent-Zero Hardening Layer
==========================================================
Hook: monologue_end
Priority: _55 (runs AFTER _50_memorize_fragments and _51_memorize_solutions)

Classifies every memory on four deterministic axes:
  - Validity:  confirmed | inferred | deprecated
  - Relevance: active | dormant
  - Utility:   load_bearing | tactical | archived
  - Source:    user_asserted | agent_inferred | external_retrieved

After classification, runs deterministic conflict resolution:
  - Entity-value divergence detection
  - Negation pattern matching
  - Explicit correction detection
  - Priority: user_asserted > agent_inferred, confirmed > inferred,
    load_bearing > tactical > archived, recency as final tiebreaker

Also handles:
  - Memory health statistics for SALUTE integration (agent._memory_health)
  - Conflict audit log (agent._memory_conflict_log)
  - Periodic maintenance (tactical → archived after N cycles unused)

Storage: Classification metadata is stored INLINE in each Document.metadata
dict within FAISS InMemoryDocstore. Persisted via Memory._save_db().
No sidecar files required.
"""

import json
import os
import re
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

# ── Agent attribute keys ─────────────────────────────────────────────────────

HEALTH_KEY = "_memory_health"
CONFLICT_LOG_KEY = "_memory_conflict_log"
MAINTENANCE_COUNTER_KEY = "_memory_maintenance_counter"

# ── Metadata keys stored on Document.metadata ────────────────────────────────

CLS_KEY = "classification"
LIN_KEY = "lineage"

# ── Regex patterns for conflict detection ────────────────────────────────────

# Entity-value extraction: "uses Python 3.11", "Python version 3.11"
_RE_USES_VERSION = re.compile(
    r'(?:uses?|using|runs?|running)\s+([\w\-]+(?:\s+[\w\-]+)?)\s+'
    r'(?:version\s+)?v?(\d+(?:\.\d+)*)',
    re.I,
)
_RE_NAME_VERSION = re.compile(
    r'([\w\-]+)\s+(?:version|v)\s*(\d+(?:\.\d+)*)',
    re.I,
)
_RE_IS_VALUE = re.compile(
    r'(?:the\s+)?([\w\-]+)\s+(?:is|are|was|uses?)\s+([\w\-./]+)',
    re.I,
)

# Negation patterns: "does not use X" vs "uses X"
_NEGATION_PAIRS = [
    (re.compile(r"\bdoes\s+not\s+use\s+([\w\-]+)", re.I), r"\buses?\s+{}"),
    (re.compile(r"\bis\s+not\s+([\w\-]+)", re.I), r"\bis\s+{}"),
    (re.compile(r"\bdon'?t\s+use\s+([\w\-]+)", re.I), r"\buses?\s+{}"),
    (re.compile(r"\bnot\s+using\s+([\w\-]+)", re.I), r"\busing\s+{}"),
    (re.compile(r"\bno\s+longer\s+uses?\s+([\w\-]+)", re.I), r"\buses?\s+{}"),
]

# Explicit correction: "actually, it's X", "no, the correct answer is Y"
_RE_CORRECTION = re.compile(
    r"(?:actually|no,?\s+(?:the\s+)?correct|correction|wrong|"
    r"not\s+\w+,?\s+but|I\s+meant|let\s+me\s+correct)",
    re.I,
)


class MemoryClassifier(Extension):
    """Classifies memories on four axes with deterministic conflict resolution."""

    async def execute(self, loop_data: LoopData = LoopData(), **kwargs) -> Any:
        try:
            config = _load_config()
            db = await Memory.get(self.agent)
            if not db or not db.db:
                return

            all_docs = db.db.get_all_docs()
            if not all_docs:
                return

            # Extract user message for source detection
            user_msg = _extract_user_message(self.agent, loop_data)

            # Current role and BST domain for lineage
            role_id = None
            bst_domain = ""
            try:
                role = getattr(self.agent, "_org_active_role", None)
                if role:
                    role_id = role.get("role_id")
            except Exception:
                pass
            try:
                store = getattr(self.agent, "_bst_store", {})
                belief = store.get("__bst_belief_state__", {})
                bst_domain = belief.get("domain", "")
            except Exception:
                pass

            maint_cycle = getattr(self.agent, MAINTENANCE_COUNTER_KEY, 0)

            # ── Phase 1: Classify untagged memories ──────────────────────
            newly_classified = []
            for doc_id, doc in all_docs.items():
                if not hasattr(doc, "metadata"):
                    continue
                if CLS_KEY in doc.metadata:
                    continue  # Already classified

                doc.metadata[CLS_KEY] = _classify(doc, user_msg, config)
                doc.metadata[LIN_KEY] = _new_lineage(
                    role_id, bst_domain, maint_cycle,
                )
                newly_classified.append((doc_id, doc))

            # ── Phase 2: Conflict resolution ─────────────────────────────
            conflict_count = 0
            for doc_id, doc in newly_classified:
                conflicts = await _detect_conflicts(
                    db, doc, doc_id, all_docs, config
                )
                for loser_id, winner_id in conflicts:
                    _resolve_conflict(all_docs, loser_id, winner_id)
                    conflict_count += 1

            # ── Phase 3: Persist changes ─────────────────────────────────
            if newly_classified:
                try:
                    db._save_db()
                except Exception:
                    pass  # Will persist on next natural Memory save

                self.agent.context.log.log(
                    type="info",
                    content=(
                        f"[MEM-CLASS] Classified {len(newly_classified)} memories, "
                        f"resolved {conflict_count} conflicts"
                    ),
                )

            # ── Phase 4: Periodic maintenance ────────────────────────────
            counter = getattr(self.agent, MAINTENANCE_COUNTER_KEY, 0) + 1
            setattr(self.agent, MAINTENANCE_COUNTER_KEY, counter)

            interval = config.get("maintenance_interval_loops", 25)
            if interval > 0 and counter % interval == 0:
                changed = _run_maintenance(all_docs, config, counter)
                if changed:
                    try:
                        db._save_db()
                    except Exception:
                        pass

            # ── Phase 5: Update health stats ─────────────────────────────
            _update_health_stats(self.agent, all_docs, conflict_count)

            # ── Phase 6: Update conflict log ─────────────────────────────
            if conflict_count > 0:
                _append_conflict_log(self.agent, newly_classified)

        except Exception as e:
            try:
                self.agent.context.log.log(
                    type="warning",
                    content=f"[MEM-CLASS] Error (passthrough): {e}",
                )
            except Exception:
                pass


# ── User message extraction ──────────────────────────────────────────────────

def _extract_user_message(agent, loop_data) -> str:
    """Get user message text for source detection."""
    # Try loop_data first
    if loop_data and hasattr(loop_data, "user_message") and loop_data.user_message:
        try:
            if hasattr(loop_data.user_message, "output_text"):
                return loop_data.user_message.output_text()
            return str(loop_data.user_message)
        except Exception:
            pass

    # Fall back to most recent user message from history
    try:
        history = getattr(agent, "history", None) or []
        for msg in reversed(history):
            if isinstance(msg, dict) and msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, str):
                    return content
                if isinstance(content, list):
                    return " ".join(
                        p.get("text", "") if isinstance(p, dict) else str(p)
                        for p in content
                    )
    except Exception:
        pass

    return ""


# ── Four-Axis Classification ────────────────────────────────────────────────

def _classify(doc, user_msg: str, config: dict) -> dict:
    """Deterministic classification on four axes."""
    text = getattr(doc, "page_content", "")
    area = doc.metadata.get("area", "")

    source = _detect_source(text, area, user_msg)
    validity = "confirmed" if source == "user_asserted" else "inferred"
    utility = _detect_utility(text, config)
    relevance = "active"

    return {
        "validity": validity,
        "relevance": relevance,
        "utility": utility,
        "source": source,
    }


def _detect_source(text: str, area: str, user_msg: str) -> str:
    """Detect memory source from area metadata and content overlap."""
    # Solutions are always agent-inferred
    if area == "solutions":
        return "agent_inferred"

    # Check for external data markers (URLs + timestamps)
    if (re.search(r"https?://\S+", text)
            and re.search(r"\d{4}-\d{2}-\d{2}", text)):
        return "external_retrieved"

    # Check content overlap with user message
    if user_msg and _text_overlaps(text, user_msg):
        return "user_asserted"

    return "agent_inferred"


def _text_overlaps(memory_text: str, user_msg: str) -> bool:
    """Check if memory text substantially overlaps with user message."""
    if not memory_text or not user_msg:
        return False

    mem = memory_text.lower().strip()
    msg = user_msg.lower().strip()

    # Direct substring match
    if len(mem) > 10 and mem in msg:
        return True

    # Word overlap ratio
    mem_words = set(mem.split())
    msg_words = set(msg.split())
    if not mem_words or not msg_words:
        return False

    overlap = len(mem_words & msg_words)
    smaller = min(len(mem_words), len(msg_words))
    return smaller > 0 and (overlap / smaller) >= 0.6


def _detect_utility(text: str, config: dict) -> str:
    """Detect utility class from keyword signals."""
    keywords = config.get("load_bearing_keywords", [])
    text_lower = text.lower()

    for keyword in keywords:
        if keyword.lower() in text_lower:
            return "load_bearing"

    return "tactical"


# ── Lineage ──────────────────────────────────────────────────────────────────

def _new_lineage(role_id: str | None, bst_domain: str = "",
                  maintenance_cycle: int = 0) -> dict:
    """Build initial lineage metadata."""
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by_role": role_id,
        "bst_domain": bst_domain,
        "classified_at_cycle": maintenance_cycle,
        "supersedes": None,
        "superseded_by": None,
        "access_count": 0,
        "last_accessed": None,
    }


# ── Conflict Detection ──────────────────────────────────────────────────────

async def _detect_conflicts(db, new_doc, new_doc_id, all_docs, config):
    """Find contradictions between new memory and existing ones."""
    conflicts = []
    top_k = config.get("conflict_top_k", 5)

    new_text = getattr(new_doc, "page_content", "")
    if not new_text or len(new_text) < 10:
        return conflicts

    # Similarity search for candidates
    try:
        results = await db.search_similarity_threshold(
            query=new_text,
            limit=top_k + 1,
            threshold=0.5,
        )
    except Exception:
        return conflicts

    for item in results:
        sim_doc, score = item if isinstance(item, tuple) else (item, 1.0)

        sim_id = sim_doc.metadata.get("id", "")
        new_id = new_doc.metadata.get("id", "")
        if sim_id == new_id:
            continue  # Skip self

        # Skip already deprecated
        sim_cls = sim_doc.metadata.get(CLS_KEY, {})
        if sim_cls.get("validity") == "deprecated":
            continue

        sim_text = getattr(sim_doc, "page_content", "")
        if not _is_contradiction(new_text, sim_text):
            continue

        # Determine winner
        new_cls = new_doc.metadata.get(CLS_KEY, {})
        loser_id = _pick_loser(
            new_id, new_cls, new_doc.metadata,
            sim_id, sim_cls, sim_doc.metadata,
        )
        winner_id = sim_id if loser_id == new_id else new_id
        conflicts.append((loser_id, winner_id))

    return conflicts


def _is_contradiction(text_a: str, text_b: str) -> bool:
    """Deterministic contradiction detection via heuristics."""
    a = text_a.lower()
    b = text_b.lower()

    # 1. Explicit correction pattern + topic overlap
    if _RE_CORRECTION.search(a):
        a_words = set(a.split())
        b_words = set(b.split())
        if len(a_words & b_words) >= 3:
            return True

    # 2. Entity-value divergence
    a_entities = _extract_entity_values(a)
    b_entities = _extract_entity_values(b)
    for entity in a_entities:
        if entity in b_entities and a_entities[entity] != b_entities[entity]:
            return True

    # 3. Negation detection
    for neg_re, pos_template in _NEGATION_PAIRS:
        match_a = neg_re.search(a)
        if match_a:
            target = match_a.group(1)
            pos_re = re.compile(pos_template.format(re.escape(target)), re.I)
            if pos_re.search(b):
                return True

        match_b = neg_re.search(b)
        if match_b:
            target = match_b.group(1)
            pos_re = re.compile(pos_template.format(re.escape(target)), re.I)
            if pos_re.search(a):
                return True

    return False


def _extract_entity_values(text: str) -> dict:
    """Extract entity-value pairs from text for divergence checking."""
    entities = {}

    for match in _RE_USES_VERSION.finditer(text):
        entities[match.group(1).strip().lower()] = match.group(2)

    for match in _RE_NAME_VERSION.finditer(text):
        key = match.group(1).strip().lower()
        if key not in entities:
            entities[key] = match.group(2)

    return entities


# ── Conflict Resolution ─────────────────────────────────────────────────────

_SOURCE_RANK = {
    "user_asserted": 3,
    "external_retrieved": 2,
    "agent_inferred": 1,
    "bookshelf_document": 0,
}
_VALIDITY_RANK = {"confirmed": 2, "inferred": 1, "deprecated": 0}
_UTILITY_RANK = {"load_bearing": 2, "tactical": 1, "archived": 0}


def _pick_loser(id_a, cls_a, meta_a, id_b, cls_b, meta_b) -> str:
    """Determine which memory loses. Returns loser's ID."""
    # Rule 1: user_asserted ALWAYS wins
    ra = _SOURCE_RANK.get(cls_a.get("source", ""), 0)
    rb = _SOURCE_RANK.get(cls_b.get("source", ""), 0)
    if ra != rb:
        return id_b if ra > rb else id_a

    # Rule 2: confirmed > inferred
    va = _VALIDITY_RANK.get(cls_a.get("validity", ""), 0)
    vb = _VALIDITY_RANK.get(cls_b.get("validity", ""), 0)
    if va != vb:
        return id_b if va > vb else id_a

    # Rule 3: utility class
    ua = _UTILITY_RANK.get(cls_a.get("utility", ""), 0)
    ub = _UTILITY_RANK.get(cls_b.get("utility", ""), 0)
    if ua != ub:
        return id_b if ua > ub else id_a

    # Rule 4: recency tiebreaker — newer wins, older loses
    ts_a = meta_a.get("timestamp", "")
    ts_b = meta_b.get("timestamp", "")
    if ts_a >= ts_b:
        return id_b  # A is newer or same → B loses
    return id_a  # B is strictly newer → A loses


def _resolve_conflict(all_docs: dict, loser_id: str, winner_id: str):
    """Mark loser as deprecated with cross-references."""
    loser = all_docs.get(loser_id)
    winner = all_docs.get(winner_id)

    if loser and hasattr(loser, "metadata"):
        if CLS_KEY not in loser.metadata:
            loser.metadata[CLS_KEY] = {}
        loser.metadata[CLS_KEY]["validity"] = "deprecated"

        if LIN_KEY not in loser.metadata:
            loser.metadata[LIN_KEY] = _new_lineage(None)
        loser.metadata[LIN_KEY]["superseded_by"] = winner_id

    if winner and hasattr(winner, "metadata"):
        if LIN_KEY not in winner.metadata:
            winner.metadata[LIN_KEY] = _new_lineage(None)
        winner.metadata[LIN_KEY]["supersedes"] = loser_id


# ── Maintenance ──────────────────────────────────────────────────────────────

def _run_maintenance(all_docs: dict, config: dict,
                     current_cycle: int = 0) -> bool:
    """Periodic archival promotion/demotion. Returns True if any changes."""
    changed = False
    archival_threshold = config.get("archival_threshold_cycles", 50)

    for doc_id, doc in list(all_docs.items()):
        if not hasattr(doc, "metadata"):
            continue

        cls = doc.metadata.get(CLS_KEY)
        lin = doc.metadata.get(LIN_KEY)
        if not cls or not lin:
            continue

        validity = cls.get("validity", "inferred")
        utility = cls.get("utility", "tactical")
        access_count = lin.get("access_count", 0)
        classified_at = lin.get("classified_at_cycle", 0)

        if validity == "deprecated":
            continue

        # Tactical → archived if never accessed AND old enough
        cycles_elapsed = current_cycle - classified_at
        if (utility == "tactical" and access_count == 0
                and cycles_elapsed >= archival_threshold):
            cls["utility"] = "archived"
            changed = True

        # Archived → tactical if accessed 3+ times
        elif utility == "archived" and access_count >= 3:
            cls["utility"] = "tactical"
            # Reset cycle so it gets another chance
            lin["classified_at_cycle"] = current_cycle
            lin["access_count"] = 0
            changed = True

    return changed


# ── Health Statistics ────────────────────────────────────────────────────────

def _update_health_stats(agent, all_docs: dict, new_conflicts: int):
    """Update memory health statistics for SALUTE integration."""
    stats = {
        "total_memories": 0,
        "by_validity": {"confirmed": 0, "inferred": 0, "deprecated": 0},
        "by_utility": {"load_bearing": 0, "tactical": 0, "archived": 0},
        "by_source": {
            "user_asserted": 0,
            "agent_inferred": 0,
            "external_retrieved": 0,
        },
        "conflicts_resolved_this_session": 0,
        "last_classification_run": datetime.now(timezone.utc).isoformat(),
    }

    # Carry forward session conflict count
    prev = getattr(agent, HEALTH_KEY, None)
    if prev:
        stats["conflicts_resolved_this_session"] = (
            prev.get("conflicts_resolved_this_session", 0) + new_conflicts
        )
    else:
        stats["conflicts_resolved_this_session"] = new_conflicts

    for doc_id, doc in all_docs.items():
        if not hasattr(doc, "metadata"):
            continue
        cls = doc.metadata.get(CLS_KEY)
        if not cls:
            continue

        stats["total_memories"] += 1

        v = cls.get("validity", "inferred")
        if v in stats["by_validity"]:
            stats["by_validity"][v] += 1

        u = cls.get("utility", "tactical")
        if u in stats["by_utility"]:
            stats["by_utility"][u] += 1

        s = cls.get("source", "agent_inferred")
        if s in stats["by_source"]:
            stats["by_source"][s] += 1

    setattr(agent, HEALTH_KEY, stats)


# ── Conflict Log ─────────────────────────────────────────────────────────────

def _append_conflict_log(agent, newly_classified):
    """Append resolved conflicts to the audit log (last 20)."""
    log = getattr(agent, CONFLICT_LOG_KEY, None) or []
    now = datetime.now(timezone.utc).isoformat()

    for doc_id, doc in newly_classified:
        lin = doc.metadata.get(LIN_KEY, {})
        supersedes = lin.get("supersedes")
        if supersedes:
            log.append({
                "timestamp": now,
                "winner_id": doc_id,
                "loser_id": supersedes,
            })

    setattr(agent, CONFLICT_LOG_KEY, log[-20:])


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
