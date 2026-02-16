"""
Belief State Tracker — Agent-Zero Translation Layer
====================================================
Hook: before_main_llm_call
File: _10_belief_state_tracker.py  (runs before _20_context_watchdog.py)

Role: Intercepts the assembled message context before it reaches the LLM.
      Reads the last user message from agent history, classifies domain,
      resolves slots via taxonomy, and either:
      - enriches the last user message with structured task context (high confidence), or
      - injects a clarifying question as the last assistant message so the
        model echoes it to the user and waits for the missing slot value.

Taxonomy file: slot_taxonomy.json (same directory as this file)
No code changes needed to add domains — edit the JSON only.
"""

import json
import re
from pathlib import Path
from typing import Any

from python.helpers.extension import Extension
import python.helpers.log as Log


# ──────────────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────────────

TAXONOMY_PATH = Path(__file__).parent / "slot_taxonomy.json"
BELIEF_KEY    = "__bst_belief_state__"   # attribute on agent for persisted state
MAX_HISTORY_SCAN_TURNS = 8               # how far back resolvers look


# ──────────────────────────────────────────────────────────────────────────────
# Extension entry point
# ──────────────────────────────────────────────────────────────────────────────

class BeliefStateTracker(Extension):
    """
    Agent-Zero extension: before_main_llm_call
    Classifies user intent, resolves slots via taxonomy, enriches or challenges.
    """

    async def execute(self, **kwargs) -> Any:
        try:
            # Get the last user message from history
            message = self._get_last_user_message()
            if not message or not message.strip():
                return

            tracker = _BSTEngine(self.agent)
            result  = tracker.process(message)

            if result["action"] == "enrich":
                # Replace the last user message content in history with enriched version
                self._replace_last_user_message(result["enriched_message"])
                Log.log(
                    type="info",
                    heading="[BST] Enriched",
                    content=f"Domain: {result['domain']} | Confidence: {result['confidence']:.2f} | Slots: {result['filled_slots']}"
                )

            elif result["action"] == "clarify":
                # Append a clarifying question as an AI message to history.
                # The model will see this and relay it to the user.
                self.agent.hist_add_ai_response(result["question"])
                Log.log(
                    type="info",
                    heading="[BST] Clarify",
                    content=f"Missing slot: {result['missing_slot']} in domain {result['domain']}"
                )

            # else action == "passthrough" — conversational, no modification needed

        except Exception as e:
            # Never block the agent on tracker failure — degrade gracefully
            Log.log(
                type="warning",
                heading="[BST] Non-fatal error",
                content=str(e)
            )

    def _get_last_user_message(self) -> str:
        """Extract the text of the most recent user/human message from agent history."""
        try:
            history = self.agent.history or []
            for msg in reversed(history):
                role = getattr(msg, "role", None) or getattr(msg, "type", None) or ""
                if role in ("human", "user"):
                    content = getattr(msg, "content", "")
                    if isinstance(content, list):
                        # Handle multipart content (e.g. with images)
                        text_parts = [c.get("text", "") if isinstance(c, dict) else str(c) for c in content]
                        return " ".join(text_parts)
                    return str(content)
        except Exception:
            pass
        return ""

    def _replace_last_user_message(self, new_content: str) -> None:
        """Replace the content of the most recent user message in history."""
        try:
            history = self.agent.history or []
            for msg in reversed(history):
                role = getattr(msg, "role", None) or getattr(msg, "type", None) or ""
                if role in ("human", "user"):
                    if isinstance(msg.content, list):
                        # Preserve multipart structure, replace first text block
                        for i, part in enumerate(msg.content):
                            if isinstance(part, dict) and part.get("type") == "text":
                                msg.content[i]["text"] = new_content
                                return
                    else:
                        msg.content = new_content
                    return
        except Exception:
            pass


# ──────────────────────────────────────────────────────────────────────────────
# Core engine
# ──────────────────────────────────────────────────────────────────────────────

class _BSTEngine:

    def __init__(self, agent):
        self.agent    = agent
        self.taxonomy = self._load_taxonomy()
        self.globs    = self.taxonomy.get("global", {})

    # ── Main entry ─────────────────────────────────────────────────────────

    def process(self, message: str) -> dict:
        # Check for underspecified / pronoun-only messages first
        if self._is_underspecified(message):
            belief = self._get_persisted_belief()
            if belief:
                return self._handle_underspecified(message, belief)

        # Classify domain
        domain_name, confidence = self._classify(message)

        if domain_name == "conversational" or not domain_name:
            self._clear_belief()
            return {"action": "passthrough", "domain": "conversational"}

        domain  = self.taxonomy["domains"][domain_name]
        history = self._get_history()

        # Build belief state: attempt to fill all slots
        belief = {
            "domain":         domain_name,
            "turn":           self._current_turn(),
            "slots":          {},
            "missing_required": [],
            "confidence":     confidence,
        }

        # Resolve each required slot
        for slot_name in domain.get("required_slots", []):
            slot_def = domain["slot_definitions"].get(slot_name, {})
            value    = self._resolve_slot(slot_name, slot_def, message, history)

            # Check conditional requirements
            if value is None and not self._is_conditionally_required(slot_name, slot_def, belief["slots"]):
                continue  # Not required given current slot values

            belief["slots"][slot_name] = value
            if value is None and not slot_def.get("nullable", True):
                belief["missing_required"].append(slot_name)

        # Resolve optional slots opportunistically (no questions asked for these)
        for slot_name in domain.get("optional_slots", []):
            slot_def = domain["slot_definitions"].get(slot_name, {})
            value    = self._resolve_slot(slot_name, slot_def, message, history)
            if value is not None:
                belief["slots"][slot_name] = value

        # Recompute confidence based on slot fill rate
        required_count = len(domain.get("required_slots", []))
        if required_count > 0:
            filled_required = required_count - len(belief["missing_required"])
            slot_confidence = filled_required / required_count
            belief["confidence"] = (confidence * 0.4) + (slot_confidence * 0.6)
        else:
            belief["confidence"] = confidence

        self._persist_belief(belief)

        threshold = domain.get("confidence_threshold", 0.7)

        # Below threshold — ask for the most critical missing slot
        if belief["confidence"] < threshold and belief["missing_required"]:
            clarifications_asked = belief.get("clarifications_asked", 0)
            max_q = self.globs.get("max_clarification_questions", 2)
            if clarifications_asked < max_q:
                missing_slot = belief["missing_required"][0]
                slot_def     = domain["slot_definitions"].get(missing_slot, {})
                question     = slot_def.get("question", f"Could you clarify: what is the {missing_slot.replace('_', ' ')}?")
                if question:
                    belief["clarifications_asked"] = clarifications_asked + 1
                    self._persist_belief(belief)
                    return {
                        "action":       "clarify",
                        "domain":       domain_name,
                        "missing_slot": missing_slot,
                        "question":     question,
                        "confidence":   belief["confidence"],
                    }

        # Confidence sufficient — build enriched message
        enriched = self._enrich_message(message, domain, belief)
        return {
            "action":          "enrich",
            "domain":          domain_name,
            "confidence":      belief["confidence"],
            "filled_slots":    [k for k, v in belief["slots"].items() if v is not None],
            "enriched_message": enriched,
        }

    # ── Classification ─────────────────────────────────────────────────────

    def _classify(self, message: str) -> tuple:
        """
        Score each domain by trigger word matches in the message.
        Returns (best_domain_name, confidence_0_to_1).
        """
        msg_lower  = message.lower()
        min_len    = self.globs.get("min_trigger_word_length", 3)
        scores     = {}

        for domain_name, domain in self.taxonomy["domains"].items():
            if domain_name == "conversational":
                continue
            triggers = domain.get("triggers", [])
            hits     = sum(1 for t in triggers if len(t) >= min_len and t in msg_lower)
            if hits > 0:
                # Normalise: longer trigger phrases score higher
                weight = sum(len(t.split()) for t in triggers if t in msg_lower)
                scores[domain_name] = hits + (weight * 0.1)

        if not scores:
            return "conversational", 1.0

        # Resolve multi-domain collisions
        strategy = self.globs.get("multi_domain_strategy", "highest_confidence")
        best     = max(scores, key=lambda k: scores[k])
        raw_max  = max(scores.values())

        # Normalise to 0-1 range (cap at 1.0)
        confidence = min(1.0, raw_max / max(3.0, raw_max + 1))
        return best, confidence

    # ── Slot resolution ────────────────────────────────────────────────────

    def _resolve_slot(self, slot_name: str, slot_def: dict, message: str, history: list) -> Any:
        """
        Try each resolver in order. Return first non-None value found.
        """
        resolvers    = slot_def.get("resolvers", [])
        keyword_map  = slot_def.get("keyword_map", {})
        msg_lower    = message.lower()

        for resolver in resolvers:

            if resolver == "keyword_map" and keyword_map:
                for keyword, mapped_value in keyword_map.items():
                    if keyword in msg_lower:
                        return mapped_value

            elif resolver == "file_extension_inference":
                ext_map = self.globs.get("file_extensions", {})
                for ext, lang in ext_map.items():
                    if ext in message or ext in self._history_text(history):
                        return lang

            elif resolver == "last_mentioned_file":
                file_ref = self._extract_file_ref(message + " " + self._history_text(history, 3))
                if file_ref:
                    return file_ref

            elif resolver == "last_mentioned_path":
                path_ref = self._extract_path_ref(message + " " + self._history_text(history, 3))
                if path_ref:
                    return path_ref

            elif resolver == "last_mentioned_entity":
                # Return the last quoted or capitalised entity mentioned
                entity = self._extract_entity(message)
                if entity:
                    return entity

            elif resolver == "history_scan":
                # Look for the slot name or synonyms in recent history
                hit = self._scan_history_for_slot(slot_name, history)
                if hit:
                    return hit

            elif resolver == "context_inference":
                # Lightweight keyword scan in message for obvious inline answers
                value = self._inline_context_resolve(slot_name, slot_def, message)
                if value:
                    return value

        # Fall back to default value if defined
        default = slot_def.get("default")
        return default

    def _is_conditionally_required(self, slot_name: str, slot_def: dict, current_slots: dict) -> bool:
        """Check if slot is required given the current slot values (required_when logic)."""
        rw = slot_def.get("required_when")
        if not rw:
            return False  # Always required if no condition
        for key, values in rw.items():
            if isinstance(values, list):
                if current_slots.get(key) in values:
                    return True
            else:
                if current_slots.get(key) == values:
                    return True
        return False

    # ── Message enrichment ─────────────────────────────────────────────────

    def _enrich_message(self, original: str, domain: dict, belief: dict) -> str:
        """
        Build the enriched message that gets sent to the model instead of the original.
        Injects: [DOMAIN], resolved slot values, and the domain preamble.
        """
        lines = []

        # Slot summary block — only include resolved slots
        filled = {k: v for k, v in belief["slots"].items() if v is not None}
        if filled:
            slot_lines = "\n".join(f"  {k}: {v}" for k, v in filled.items())
            lines.append(f"[TASK CONTEXT]\n{slot_lines}")

        # Preamble instruction for this domain
        preamble = domain.get("preamble")
        if preamble:
            lines.append(f"[INSTRUCTION]\n{preamble}")

        # Original user message preserved verbatim at the end
        lines.append(f"[USER MESSAGE]\n{original}")

        return "\n\n".join(lines)

    # ── Underspecified message handling ─────────────────────────────────────

    def _is_underspecified(self, message: str) -> bool:
        msg_lower = message.lower().strip()
        pronouns  = self.globs.get("ambiguous_pronouns", [])
        phrases   = self.globs.get("underspec_phrases", [])

        # Short messages dominated by pronouns
        words = msg_lower.split()
        if len(words) <= 5:
            if any(p in msg_lower for p in pronouns):
                return True
        if any(ph in msg_lower for ph in phrases):
            return True
        return False

    def _handle_underspecified(self, message: str, belief: dict) -> dict:
        """Re-attach persisted belief state context to an underspecified follow-up."""
        domain_name = belief.get("domain", "conversational")
        if domain_name not in self.taxonomy["domains"]:
            return {"action": "passthrough", "domain": "conversational"}

        domain = self.taxonomy["domains"][domain_name]
        preamble = domain.get("preamble", "")

        enriched_lines = [
            f"[CONTINUING TASK — Domain: {domain_name}]",
        ]
        filled = {k: v for k, v in belief.get("slots", {}).items() if v is not None}
        if filled:
            enriched_lines.append("[PRIOR CONTEXT]\n" + "\n".join(f"  {k}: {v}" for k, v in filled.items()))
        if preamble:
            enriched_lines.append(f"[INSTRUCTION]\n{preamble}")
        enriched_lines.append(f"[USER MESSAGE]\n{message}")

        return {
            "action":           "enrich",
            "domain":           domain_name,
            "confidence":       belief.get("confidence", 0.7),
            "filled_slots":     list(filled.keys()),
            "enriched_message": "\n\n".join(enriched_lines),
        }

    # ── Belief state persistence ────────────────────────────────────────────

    def _persist_belief(self, belief: dict) -> None:
        """Store belief state in agent context dict for cross-turn continuity."""
        try:
            if not hasattr(self.agent, "context") or self.agent.context is None:
                return
            ctx = self.agent.context
            if not hasattr(ctx, "__dict__"):
                return
            if not hasattr(ctx, "_bst_store"):
                ctx._bst_store = {}
            ctx._bst_store[BELIEF_KEY] = belief
        except Exception:
            pass  # Never break the agent over storage failure

    def _get_persisted_belief(self) -> dict | None:
        try:
            ctx = getattr(self.agent, "context", None)
            if ctx is None:
                return None
            store = getattr(ctx, "_bst_store", {})
            belief = store.get(BELIEF_KEY)
            if not belief:
                return None
            # Respect TTL
            ttl = self.globs.get("belief_state_ttl_turns", 6)
            if self._current_turn() - belief.get("turn", 0) > ttl:
                self._clear_belief()
                return None
            return belief
        except Exception:
            return None

    def _clear_belief(self) -> None:
        try:
            ctx = getattr(self.agent, "context", None)
            if ctx and hasattr(ctx, "_bst_store"):
                ctx._bst_store.pop(BELIEF_KEY, None)
        except Exception:
            pass

    # ── History utilities ───────────────────────────────────────────────────

    def _get_history(self) -> list:
        try:
            msgs = self.agent.history or []
            return msgs[-MAX_HISTORY_SCAN_TURNS:]
        except Exception:
            return []

    def _history_text(self, history: list, n: int = MAX_HISTORY_SCAN_TURNS) -> str:
        """Return concatenated text of the last n history messages."""
        try:
            recent = history[-n:] if len(history) > n else history
            parts  = []
            for m in recent:
                content = getattr(m, "content", "") or ""
                if isinstance(content, list):
                    content = " ".join(str(c) for c in content)
                parts.append(str(content))
            return " ".join(parts)
        except Exception:
            return ""

    def _current_turn(self) -> int:
        try:
            return len(self.agent.history or [])
        except Exception:
            return 0

    # ── Extraction helpers ──────────────────────────────────────────────────

    def _extract_file_ref(self, text: str) -> str | None:
        """Extract the most recent file reference from text."""
        patterns = [
            r'`([^`]+\.[a-zA-Z]{1,5})`',           # backtick-quoted
            r'"([^"]+\.[a-zA-Z]{1,5})"',             # double-quoted
            r"'([^']+\.[a-zA-Z]{1,5})'",             # single-quoted
            r'(\S+\.[a-zA-Z]{1,5})',                  # bare filename.ext
        ]
        for pattern in patterns:
            matches = re.findall(pattern, text)
            if matches:
                return matches[-1]  # Most recent
        return None

    def _extract_path_ref(self, text: str) -> str | None:
        """Extract the most recent path from text."""
        patterns = self.globs.get("path_patterns", [
            r'(/[a-zA-Z0-9_\-\.]+(?:/[a-zA-Z0-9_\-\.]+)+)',
            r'(~/[a-zA-Z0-9_\-\./]+)',
        ])
        for pattern in patterns:
            matches = re.findall(pattern, text)
            if matches:
                return matches[-1]
        return None

    def _extract_entity(self, text: str) -> str | None:
        """Extract last quoted or parenthetical entity."""
        patterns = [r'`([^`]+)`', r'"([^"]+)"', r"'([^']+)'"]
        for pattern in patterns:
            matches = re.findall(pattern, text)
            if matches:
                return matches[-1]
        return None

    def _scan_history_for_slot(self, slot_name: str, history: list) -> str | None:
        """Fuzzy scan recent history for values relevant to a slot."""
        text = self._history_text(history)
        # Scan for file refs if slot sounds like a file target
        if any(k in slot_name for k in ["file", "path", "source", "target", "script"]):
            return self._extract_file_ref(text) or self._extract_path_ref(text)
        return None

    def _inline_context_resolve(self, slot_name: str, slot_def: dict, message: str) -> Any:
        """
        Lightweight pattern matching for common inline slot answers.
        e.g. "fix the bug in agent.py" → target_file = "agent.py"
        """
        msg_lower = message.lower()

        # Language slot: check for explicit language mentions
        if slot_name == "language":
            for ext, lang in self.globs.get("file_extensions", {}).items():
                if lang in msg_lower:
                    return lang

        # Boolean slots: look for negation or affirmation
        if slot_def.get("type") == "bool":
            positives = ["yes", "always", "definitely", "make sure", "keep", "preserve", "maintain"]
            negatives = ["no", "don't", "do not", "ignore", "skip", "without"]
            if any(w in msg_lower for w in negatives):
                return False
            if any(w in msg_lower for w in positives):
                return True

        # Enum slots: check if any enum value appears verbatim
        if slot_def.get("type") == "enum":
            for val in slot_def.get("enum_values", []):
                if val in msg_lower:
                    return val

        return None

    # ── Taxonomy loader ─────────────────────────────────────────────────────

    @staticmethod
    def _load_taxonomy() -> dict:
        path = TAXONOMY_PATH
        if not path.exists():
            raise FileNotFoundError(f"[BST] slot_taxonomy.json not found at {path}")
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
