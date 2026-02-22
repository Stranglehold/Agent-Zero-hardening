from python.helpers.extension import Extension
from typing import Any

FAILURES_KEY = "_tool_failures"

TOOL_THRESHOLD = 3
GLOBAL_THRESHOLD = 5

FALLBACK_MAP = {
    ("code_execution_tool", "syntax"): "Syntax error. Check for typos, missing quotes, or indentation.",
    ("code_execution_tool", "dependency"): "Missing package. Install with pip/npm first, then retry.",
    ("code_execution_tool", "timeout"): "Command timed out. Break into smaller steps or check for hanging process.",
    ("code_execution_tool", "permission"): "Permission denied. Try sudo or check file ownership with ls -la.",
    ("code_execution_tool", "not_found"): "Command or file not found. Verify path and spelling.",
    ("code_execution_tool", "network"): "Network error. Check host reachability with ping or curl -v.",
    ("code_execution_tool", "resource"): "Resource limit hit. Check disk (df -h) or memory (free -m).",
    ("knowledge_tool", "not_found"): "No results. Broaden search terms or try alternative phrasing.",
    ("knowledge_tool", "any"): "Knowledge tool failed. Try filesystem search or ask user.",
    ("call_subordinate", "timeout"): "Subordinate timed out. Simplify the delegated task or handle directly.",
    ("call_subordinate", "any"): "Subordinate failed. Handle the task directly.",
    ("any", "timeout"): "Operation timed out. Break into smaller steps.",
    ("any", "permission"): "Access denied. Check permissions.",
    ("any", "not_found"): "Not found. Verify names and paths.",
    ("any", "syntax"): "Invalid syntax. Review command format.",
    ("any", "network"): "Network issue. Check connectivity.",
    ("any", "dependency"): "Missing dependency. Install first.",
    ("any", "execution"): "Execution error. Review error message and adjust.",
}

STEP_BACK_ADVICE = (
    "Multiple consecutive failures without success. "
    "Consider a different approach or ask the user for guidance."
)


class ToolFallbackAdvisor(Extension):
    """Injects compact fallback guidance on consecutive tool failures."""

    async def execute(self, tool_args: dict[str, Any] | None = None,
                      tool_name: str = "", **kwargs):
        try:
            failures = self.agent.get_data(FAILURES_KEY)
            if not failures:
                return

            consecutive = failures.get("consecutive", {})
            history = failures.get("history", [])

            advice_parts = []

            tool_count = consecutive.get(tool_name, 0)
            if tool_count >= TOOL_THRESHOLD:
                recent_error = None
                for entry in reversed(history):
                    if entry["tool"] == tool_name:
                        recent_error = entry["error_type"]
                        break

                if recent_error:
                    advice = self._lookup_fallback(tool_name, recent_error)
                    if advice:
                        advice_parts.append(advice)

            if len(history) >= GLOBAL_THRESHOLD:
                advice_parts.append(STEP_BACK_ADVICE)

            if advice_parts:
                full_advice = " | ".join(advice_parts)
                try:
                    self.agent.context.log.log(
                        type="warning",
                        content=f"[Fallback] {full_advice}"
                    )
                    self.agent.hist_add_warning(full_advice)
                except Exception:
                    pass

        except Exception:
            pass

    def _lookup_fallback(self, tool_name: str, error_type: str) -> str | None:
        key = (tool_name, error_type)
        if key in FALLBACK_MAP:
            return FALLBACK_MAP[key]

        key = (tool_name, "any")
        if key in FALLBACK_MAP:
            return FALLBACK_MAP[key]

        key = ("any", error_type)
        if key in FALLBACK_MAP:
            return FALLBACK_MAP[key]

        return None
