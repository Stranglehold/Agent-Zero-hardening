"""
Belief State Tracker — Agent-Zero Translation Layer
====================================================
Hook: before_main_llm_call
File: _10_belief_state_tracker.py  (runs before _20_context_watchdog.py)

Role: Intercepts the assembled prompt AFTER prepare_prompt() builds
      loop_data.history_output but BEFORE the LLM call at line 426.
      Finds the last HumanMessage in loop_data.history_output and either:
      - replaces its content with an enriched, slot-resolved version, or
      - replaces its content with a directive to surface one clarifying question.

Taxonomy: slot_taxonomy.json (same directory as this file)
No code changes needed to add domains — edit the JSON only.

Fix history (v1 → v2):
  - Was modifying self.agent.history after prepare_prompt() already snapshotted it
  - Now modifies loop_data.history_output directly (the live LLM call packet)

Fix log (v1 → v2):
  - Was calling Log.log() as a module-level function (doesn't exist)
  - Now calls self.agent.context.log.log() matching the watchdog pattern
"""

import json
import re
from pathlib import Path
from typing import Any

from agent import LoopData
from python.helpers.extension import Extension

# ──────────────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────────────

TAXONOMY_PATH          = Path(__file__).parent / "slot_taxonomy.json"
BELIEF_KEY             = "__bst_belief_state__"
MAX_HISTORY_SCAN_TURNS = 8


# ──────────────────────────────────────────────────────────────────────────────
# Extension entry point
# ──────────────────────────────────────────────────────────────────────────────

class BeliefStateTracker(Extension):
    """
    Agent-Zero extension: before_main_llm_call
    Reads last HumanMessage from loop_data.history_output, runs BST pipeline,
    writes enriched or clarification content back into the same message object.
    """

    async def execute(self, loop_data: LoopData = LoopData(), **kwargs) -> Any:
        try:
            # ── 1. Find the last HumanMessage in the assembled prompt ────────
            human_msg = _get_last_human_message(loop_data.history_output)
            if human_msg is None:
                return

            message = human_msg.content
            if isinstance(message, list):
                # Multi-part content (e.g. vision) — extract text parts only
                message = " ".join(
                    p.get("text", "") if isinstance(p, dict) else str(p)
                    for p in message
                )
            message = str(message).strip()
            if not message:
                return

            # ── 2. Run the BST pipeline ──────────────────────────────────────
            tracker = _BSTEngine(self.agent)
            result  = tracker.process(message)

            # ── 3. Apply result ──────────────────────────────────────────────
            if result["action"] == "enrich":
                human_msg.content = result["enriched_message"]
                self.agent.context.log.log(
                    type="info",
                    content=(
                        f"[BST] Domain: {result['domain']} | "
                        f"Confidence: {result['confidence']:.2f} | "
                        f"Slots: {result['filled_slots']}"
                    ),
                )

            elif result["action"] == "clarify":
                # Replace the user message with a directive telling the model
                # to surface exactly one question before attempting the task.
                human_msg.content = (
                    f"[CLARIFICATION NEEDED]\n"
                    f"Original request: {message}\n\n"
                    f"Before attempting this task, ask the user exactly this "
                    f"question and wait for their answer:\n"
                    f"\"{result['question']}\"\n\n"
                    f"Do not attempt the task until they respond."
                )
                self.agent.context.log.log(
                    type="info",
                    content=(
                        f"[BST] Clarification needed — "
                        f"domain: {result['domain']} | "
                        f"missing: {result['missing_slot']}"
                    ),
                )

            # action == "passthrough" → conversational, no modification needed

        except Exception as e:
            # Never block the agent on tracker failure — degrade to passthrough
            try:
                self.agent.context.log.log(
                    type="warning",
                    content=f"[BST] Non-fatal error, passing through: {e}",
                )
            except Exception:
                pass


# ──────────────────────────────────────────────────────────────────────────────
# History helpers
# ──────────────────────────────────────────────────────────────────────────────

def _get_last_human_message(history_output: list):
    """
    Return the last HumanMessage object from loop_data.history_output.
    Returns None if history is empty or has no human messages.
    We return the object itself (not a copy) so mutations affect the live packet.
    """
    if not history_output:
        return None
    for msg in reversed(history_output):
        # LangChain message types: HumanMessage, AIMessage, SystemMessage etc.
        # Check by class name to avoid a hard import dependency.
        cls_name = type(msg).__name__
        if cls_name in ("HumanMessage", "HumanMessageChunk"):
            return msg
    return None


def _message_text(msg) -> str:
    """Extract plain text content from a LangChain message."""
    content = getattr(msg, "content", "")
    if isinstance(content, list):
        return " ".join(
            p.get("text", "") if isinstance(p, dict) else str(p)
            for p in content
        )
    return str(content)


# ──────────────────────────────────────────────────────────────────────────────
# Core BST engine (unchanged from v1 — all logic lives here)
# ──────────────────────────────────────────────────────────────────────────────

class _BSTEngine:

    def __init__(self, agent):
        self.agent    = agent
        self.taxonomy = self._load_taxonomy()
        self.globs    = self.taxonomy.get("global", {})

    # ── Main entry ────────────────────────────────────────────────────────────

    def process(self, message: str) -> dict:
        # Underspecified / pronoun-only follow-up: re-attach prior belief state
        if self._is_underspecified(message):
            belief = self._get_persisted_belief()
            if belief:
                return self._handle_underspecified(message, belief)

        # Classify
        domain_name, confidence = self._classify(message)

        if domain_name == "conversational" or not domain_name:
            self._clear_belief()
            return {"action": "passthrough", "domain": "conversational"}

        domain  = self.taxonomy["domains"][domain_name]
        history = self._get_history_text()

        belief = {
            "domain":           domain_name,
            "turn":             self._current_turn(),
            "slots":            {},
            "missing_required": [],
            "confidence":       confidence,
        }

        # Resolve required slots
        for slot_name in domain.get("required_slots", []):
            slot_def = domain["slot_definitions"].get(slot_name, {})
            value    = self._resolve_slot(slot_name, slot_def, message, history)
            if value is None and not self._is_conditionally_required(
                slot_name, slot_def, belief["slots"]
            ):
                continue
            belief["slots"][slot_name] = value
            if value is None and not slot_def.get("nullable", True):
                belief["missing_required"].append(slot_name)

        # Resolve optional slots (no questions, opportunistic only)
        for slot_name in domain.get("optional_slots", []):
            slot_def = domain["slot_definitions"].get(slot_name, {})
            value    = self._resolve_slot(slot_name, slot_def, message, history)
            if value is not None:
                belief["slots"][slot_name] = value

        # Recompute confidence from slot fill rate
        required_count = len(domain.get("required_slots", []))
        if required_count > 0:
            filled = required_count - len(belief["missing_required"])
            slot_conf = filled / required_count
            belief["confidence"] = (confidence * 0.4) + (slot_conf * 0.6)
        else:
            belief["confidence"] = confidence

        self._persist_belief(belief)

        threshold = domain.get("confidence_threshold", 0.7)

        # Below threshold — ask for the most critical missing slot
        if belief["confidence"] < threshold and belief["missing_required"]:
            asked = belief.get("clarifications_asked", 0)
            max_q = self.globs.get("max_clarification_questions", 2)
            if asked < max_q:
                missing_slot = belief["missing_required"][0]
                slot_def     = domain["slot_definitions"].get(missing_slot, {})
                question     = slot_def.get(
                    "question",
                    f"Could you clarify: what is the {missing_slot.replace('_', ' ')}?"
                )
                if question:
                    belief["clarifications_asked"] = asked + 1
                    self._persist_belief(belief)
                    return {
                        "action":       "clarify",
                        "domain":       domain_name,
                        "missing_slot": missing_slot,
                        "question":     question,
                        "confidence":   belief["confidence"],
                    }

        # Confidence sufficient — enrich
        return {
            "action":          "enrich",
            "domain":          domain_name,
            "confidence":      belief["confidence"],
            "filled_slots":    [k for k, v in belief["slots"].items() if v is not None],
            "enriched_message": self._enrich_message(message, domain, belief),
        }

    # ── Classification ────────────────────────────────────────────────────────

    def _classify(self, message: str) -> tuple:
        msg_lower = message.lower()
        min_len   = self.globs.get("min_trigger_word_length", 3)
        scores    = {}

        for domain_name, domain in self.taxonomy["domains"].items():
            if domain_name == "conversational":
                continue
            triggers = domain.get("triggers", [])
            hits     = sum(1 for t in triggers if len(t) >= min_len and t in msg_lower)
            if hits > 0:
                weight = sum(len(t.split()) for t in triggers if t in msg_lower)
                scores[domain_name] = hits + (weight * 0.1)

        if not scores:
            return "conversational", 1.0

        best    = max(scores, key=lambda k: scores[k])
        raw_max = max(scores.values())
        confidence = min(1.0, raw_max / max(3.0, raw_max + 1))
        return best, confidence

    # ── Slot resolution ───────────────────────────────────────────────────────

    def _resolve_slot(self, slot_name: str, slot_def: dict, message: str, history: str) -> Any:
        resolvers   = slot_def.get("resolvers", [])
        keyword_map = slot_def.get("keyword_map", {})
        msg_lower   = message.lower()

        for resolver in resolvers:
            if resolver == "keyword_map" and keyword_map:
                for keyword, mapped in keyword_map.items():
                    if keyword in msg_lower:
                        return mapped

            elif resolver == "file_extension_inference":
                ext_map = self.globs.get("file_extensions", {})
                combined = message + " " + history
                for ext, lang in ext_map.items():
                    if ext in combined:
                        return lang

            elif resolver == "last_mentioned_file":
                ref = self._extract_file_ref(message + " " + history[:500])
                if ref:
                    return ref

            elif resolver == "last_mentioned_path":
                ref = self._extract_path_ref(message + " " + history[:500])
                if ref:
                    return ref

            elif resolver == "last_mentioned_entity":
                entity = self._extract_entity(message)
                if entity:
                    return entity

            elif resolver == "history_scan":
                hit = self._scan_history_for_slot(slot_name, history)
                if hit:
                    return hit

            elif resolver == "context_inference":
                value = self._inline_context_resolve(slot_name, slot_def, message)
                if value:
                    return value

        return slot_def.get("default")

    def _is_conditionally_required(self, slot_name: str, slot_def: dict, current_slots: dict) -> bool:
        rw = slot_def.get("required_when")
        if not rw:
            return False
        for key, values in rw.items():
            if isinstance(values, list):
                if current_slots.get(key) in values:
                    return True
            else:
                if current_slots.get(key) == values:
                    return True
        return False

    # ── Message enrichment ────────────────────────────────────────────────────

    def _enrich_message(self, original: str, domain: dict, belief: dict) -> str:
        lines = []
        filled = {k: v for k, v in belief["slots"].items() if v is not None}
        if filled:
            slot_lines = "\n".join(f"  {k}: {v}" for k, v in filled.items())
            lines.append(f"[TASK CONTEXT]\n{slot_lines}")
        preamble = domain.get("preamble")
        if preamble:
            lines.append(f"[INSTRUCTION]\n{preamble}")
        lines.append(f"[USER MESSAGE]\n{original}")
        return "\n\n".join(lines)

    # ── Underspecified handling ───────────────────────────────────────────────

    def _is_underspecified(self, message: str) -> bool:
        msg_lower = message.lower().strip()
        pronouns  = self.globs.get("ambiguous_pronouns", [])
        phrases   = self.globs.get("underspec_phrases", [])
        words     = msg_lower.split()
        if len(words) <= 5 and any(p in msg_lower for p in pronouns):
            return True
        return any(ph in msg_lower for ph in phrases)

    def _handle_underspecified(self, message: str, belief: dict) -> dict:
        domain_name = belief.get("domain", "conversational")
        if domain_name not in self.taxonomy["domains"]:
            return {"action": "passthrough", "domain": "conversational"}

        domain   = self.taxonomy["domains"][domain_name]
        preamble = domain.get("preamble", "")
        filled   = {k: v for k, v in belief.get("slots", {}).items() if v is not None}

        lines = [f"[CONTINUING TASK — Domain: {domain_name}]"]
        if filled:
            lines.append("[PRIOR CONTEXT]\n" + "\n".join(f"  {k}: {v}" for k, v in filled.items()))
        if preamble:
            lines.append(f"[INSTRUCTION]\n{preamble}")
        lines.append(f"[USER MESSAGE]\n{message}")

        return {
            "action":           "enrich",
            "domain":           domain_name,
            "confidence":       belief.get("confidence", 0.7),
            "filled_slots":     list(filled.keys()),
            "enriched_message": "\n\n".join(lines),
        }

    # ── Belief state persistence ──────────────────────────────────────────────

    def _persist_belief(self, belief: dict) -> None:
        try:
            if not hasattr(self.agent, "_bst_store"):
                self.agent._bst_store = {}
            self.agent._bst_store[BELIEF_KEY] = belief
        except Exception:
            pass

    def _get_persisted_belief(self) -> dict | None:
        try:
            store  = getattr(self.agent, "_bst_store", {})
            belief = store.get(BELIEF_KEY)
            if not belief:
                return None
            ttl = self.globs.get("belief_state_ttl_turns", 6)
            if self._current_turn() - belief.get("turn", 0) > ttl:
                self._clear_belief()
                return None
            return belief
        except Exception:
            return None

    def _clear_belief(self) -> None:
        try:
            store = getattr(self.agent, "_bst_store", {})
            store.pop(BELIEF_KEY, None)
        except Exception:
            pass

    # ── History utilities ─────────────────────────────────────────────────────

    def _get_history_text(self) -> str:
        """
        Read recent history text from agent.history for resolver context.
        This is fine to read here — we only need text content for pattern
        matching, not to modify the live call packet.
        """
        try:
            msgs = self.agent.history or []
            recent = msgs[-MAX_HISTORY_SCAN_TURNS:]
            parts = []
            for m in recent:
                content = getattr(m, "content", "") or ""
                if isinstance(content, list):
                    content = " ".join(
                        p.get("text", "") if isinstance(p, dict) else str(p)
                        for p in content
                    )
                parts.append(str(content))
            return " ".join(parts)
        except Exception:
            return ""

    def _current_turn(self) -> int:
        try:
            return len(self.agent.history or [])
        except Exception:
            return 0

    # ── Extraction helpers ────────────────────────────────────────────────────

    def _extract_file_ref(self, text: str) -> str | None:
        patterns = [
            r'`([^`]+\.[a-zA-Z]{1,5})`',
            r'"([^"]+\.[a-zA-Z]{1,5})"',
            r"'([^']+\.[a-zA-Z]{1,5})'",
            r'(\S+\.[a-zA-Z]{1,5})',
        ]
        for pattern in patterns:
            matches = re.findall(pattern, text)
            if matches:
                return matches[-1]
        return None

    def _extract_path_ref(self, text: str) -> str | None:
        patterns = [
            r'(/[a-zA-Z0-9_\-\.]+(?:/[a-zA-Z0-9_\-\.]+)+)',
            r'(~/[a-zA-Z0-9_\-\./]+)',
        ]
        for pattern in patterns:
            matches = re.findall(pattern, text)
            if matches:
                return matches[-1]
        return None

    def _extract_entity(self, text: str) -> str | None:
        for pattern in [r'`([^`]+)`', r'"([^"]+)"', r"'([^']+)'"]:
            matches = re.findall(pattern, text)
            if matches:
                return matches[-1]
        return None

    def _scan_history_for_slot(self, slot_name: str, history: str) -> str | None:
        if any(k in slot_name for k in ["file", "path", "source", "target", "script"]):
            return self._extract_file_ref(history) or self._extract_path_ref(history)
        return None

    def _inline_context_resolve(self, slot_name: str, slot_def: dict, message: str) -> Any:
        msg_lower = message.lower()

        if slot_name == "language":
            for ext, lang in self.globs.get("file_extensions", {}).items():
                if lang in msg_lower:
                    return lang

        if slot_def.get("type") == "bool":
            if any(w in msg_lower for w in ["no", "don't", "do not", "ignore", "skip", "without"]):
                return False
            if any(w in msg_lower for w in ["yes", "always", "keep", "preserve", "maintain"]):
                return True

        if slot_def.get("type") == "enum":
            for val in slot_def.get("enum_values", []):
                if val in msg_lower:
                    return val

        return None

    # ── Taxonomy loader ───────────────────────────────────────────────────────

    @staticmethod
    def _load_taxonomy() -> dict:
        if not TAXONOMY_PATH.exists():
            raise FileNotFoundError(f"[BST] slot_taxonomy.json not found at {TAXONOMY_PATH}")
        with open(TAXONOMY_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
