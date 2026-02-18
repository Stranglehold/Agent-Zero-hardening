import re
from python.helpers.extension import Extension
from python.helpers.tool import Response

FAILURES_KEY = "_tool_failures"
MAX_HISTORY = 20

# Error classification patterns — order matters, first match wins
ERROR_PATTERNS = [
    # Timeouts
    (r"(?i)timeout|timed?\s*out|deadline exceeded|connection.*reset", "timeout"),
    # Not found / doesn't exist
    (r"(?i)not found|no such file|does not exist|404|command not found|unknown tool", "not_found"),
    # Permission / access
    (r"(?i)permission denied|access denied|forbidden|403|unauthorized|401", "permission"),
    # Syntax / argument errors
    (r"(?i)syntax error|invalid argument|unexpected token|parse error|malformed|missing required", "syntax"),
    # Connection / network
    (r"(?i)connection refused|network unreachable|DNS|ECONNREFUSED|could not resolve", "network"),
    # Resource limits
    (r"(?i)out of memory|disk full|no space left|quota exceeded|resource exhausted", "resource"),
    # Import / dependency
    (r"(?i)no module named|import error|ModuleNotFoundError|package.*not installed", "dependency"),
    # Generic execution failure
    (r"(?i)error|exception|failed|traceback", "execution"),
]


class ToolFallbackLogger(Extension):
    """Classifies tool execution results and logs failures for the fallback advisor."""

    async def execute(self, response: Response | None = None, **kwargs):
        try:
            if not response:
                return

            tool_name = kwargs.get("tool_name", "")
            if not tool_name:
                return

            # Classify the response
            error_type = self._classify_response(response.message)

            if not error_type:
                # Success — reset consecutive count for this tool
                failures = self.agent.get_data(FAILURES_KEY) or {}
                if "consecutive" not in failures:
                    failures["consecutive"] = {}
                failures["consecutive"][tool_name] = 0
                self.agent.set_data(FAILURES_KEY, failures)
                return

            # Failure — record it
            failures = self.agent.get_data(FAILURES_KEY) or {}

            # Initialize structure
            if "history" not in failures:
                failures["history"] = []
            if "consecutive" not in failures:
                failures["consecutive"] = {}

            # Log failure
            failures["history"].append({
                "tool": tool_name,
                "error_type": error_type,
                "message_preview": response.message[:150],
            })

            # Trim history
            if len(failures["history"]) > MAX_HISTORY:
                failures["history"] = failures["history"][-MAX_HISTORY:]

            # Increment consecutive failure count
            prev = failures["consecutive"].get(tool_name, 0)
            failures["consecutive"][tool_name] = prev + 1

            self.agent.set_data(FAILURES_KEY, failures)

        except Exception:
            pass

    def _classify_response(self, message: str) -> str | None:
        """Classify response message. Returns error type or None for success."""
        if not message:
            return None

        for pattern, error_type in ERROR_PATTERNS:
            if re.search(pattern, message):
                return error_type

        return None
