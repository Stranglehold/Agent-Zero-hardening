from python.helpers.extension import Extension

# Number of consecutive failures on the same tool before reflection fires
REFLECTION_THRESHOLD = 2

# Agent data key for the failure counter dict
TRACKER_KEY = "_failure_tracker"

# Format error signals — same as structured_retry to ensure consistent scope
FORMAT_ERROR_SIGNALS = [
    "json", "parse", "format", "tool", "missing", "invalid",
    "expected", "syntax", "decode", "key", "argument",
    "not found", "does not exist", "command not found"
]

REFLECTION_PROMPT = """
---
REFLECTION REQUIRED — You have failed to use tool "{tool_name}" {count} consecutive times.

Before attempting any action, answer these questions in your thoughts:
1. What specifically caused the failure? (Be precise — wrong args, wrong tool type, wrong approach?)
2. Are you calling an agent tool as a terminal command? If so, stop. Use JSON tool_name field instead.
3. Are you scoping actions correctly? (Skill work stays in skill directory. Never touch /a0/requirements.txt for skill tasks.)
4. What will you do differently this time?

Only after answering these questions, output your next JSON action.
---
"""


def _get_tracker(agent) -> dict:
    tracker = agent.get_data(TRACKER_KEY)
    if not isinstance(tracker, dict):
        tracker = {}
        agent.set_data(TRACKER_KEY, tracker)
    return tracker


def _get_tool_name(agent) -> str:
    """Get current tool name from loop_data.current_tool or fall back to last_response regex."""
    try:
        tool = agent.loop_data.current_tool
        if tool and hasattr(tool, "name") and tool.name:
            return tool.name
    except Exception:
        pass

    # Fallback: extract from last_response
    import re
    import json
    last = getattr(agent.loop_data, "last_response", "") or ""
    if last:
        cleaned = re.sub(r'~~~json|~~~|```json|```', '', last).strip()
        try:
            return json.loads(cleaned).get("tool_name", "") or ""
        except Exception:
            match = re.search(r'"tool_name"\s*:\s*"([^"]+)"', last)
            if match:
                return match.group(1)

    return "unknown"


class FailureTracker(Extension):
    async def execute(self, **kwargs):
        msg = kwargs.get("msg")
        if not msg or "message" not in msg:
            return

        error_text = msg["message"].lower()

        # Only track errors that look like tool/format failures
        # Pass through other errors (network, permission, etc.) unmodified
        if not any(signal in error_text for signal in FORMAT_ERROR_SIGNALS):
            return

        tool_name = _get_tool_name(self.agent)
        if not tool_name:
            return

        tracker = _get_tracker(self.agent)

        # Increment consecutive failure count for this tool
        tracker[tool_name] = tracker.get(tool_name, 0) + 1
        self.agent.set_data(TRACKER_KEY, tracker)

        count = tracker[tool_name]

        # Inject reflection prompt at threshold — appends after any structured
        # retry schema that _20_structured_retry already added
        if count >= REFLECTION_THRESHOLD:
            reflection = REFLECTION_PROMPT.format(
                tool_name=tool_name,
                count=count,
            )
            msg["message"] = msg["message"].rstrip() + reflection
