import re
from python.helpers.extension import Extension
from python.helpers.tool import Response

FAILURES_KEY = "_tool_failures"
MAX_HISTORY = 20

SUCCESS_INDICATORS = [
    r"(?i)successfully installed",
    r"(?i)successfully built",
    r"(?i)requirement already satisfied",
    r"(?i)already installed",
    r"(?i)is up to date",
    r"(?i)install complete",
    r"(?i)done\.\s*$",
    r"(?i)^ok\b",
    r"(?i)setting up \S+",
    r"(?i)unpacking \S+",
    r"(?i)processing triggers",
    r"(?i)created wheel for",
    r"(?i)stored in directory:",
]

ERROR_PATTERNS = [
    (r"(?i)timeout|timed?\s*out|deadline exceeded|connection.*reset", "timeout"),
    (r"(?i)not found|no such file|does not exist|404|command not found|unknown tool", "not_found"),
    (r"(?i)permission denied|access denied|forbidden|403|unauthorized|401", "permission"),
    (r"(?i)syntax error|invalid argument|unexpected token|parse error|malformed|missing required", "syntax"),
    (r"(?i)connection refused|network unreachable|DNS|ECONNREFUSED|could not resolve", "network"),
    (r"(?i)out of memory|disk full|no space left|quota exceeded|resource exhausted", "resource"),
    (r"(?i)no module named|import error|ModuleNotFoundError|package.*not installed", "dependency"),
    (r"(?i)^ERROR:|^error:|Traceback \(most recent|raise \w+Error|FATAL|CRITICAL", "execution"),
]


class ToolFallbackLogger(Extension):
    """Classifies tool execution results and logs failures for the fallback advisor.

    Key change from original: history is cleared on success, providing
    natural decay so the fallback advisor doesn't fire indefinitely
    after a sequence of resolved errors.
    """

    async def execute(self, response: Response | None = None, **kwargs):
        try:
            if not response:
                return

            tool_name = kwargs.get("tool_name", "")
            if not tool_name:
                return

            error_type = self._classify_response(response.message)

            failures = self.agent.get_data(FAILURES_KEY) or {}
            if "history" not in failures:
                failures["history"] = []
            if "consecutive" not in failures:
                failures["consecutive"] = {}

            if not error_type:
                failures["consecutive"][tool_name] = 0
                failures["history"] = []
                self.agent.set_data(FAILURES_KEY, failures)
                return

            failures["history"].append({
                "tool": tool_name,
                "error_type": error_type,
                "message_preview": response.message[:150],
            })

            if len(failures["history"]) > MAX_HISTORY:
                failures["history"] = failures["history"][-MAX_HISTORY:]

            prev = failures["consecutive"].get(tool_name, 0)
            failures["consecutive"][tool_name] = prev + 1

            self.agent.set_data(FAILURES_KEY, failures)

        except Exception:
            pass

    def _classify_response(self, message: str) -> str | None:
        if not message:
            return None

        for pattern in SUCCESS_INDICATORS:
            if re.search(pattern, message):
                return None

        for pattern, error_type in ERROR_PATTERNS:
            if re.search(pattern, message):
                return error_type

        return None
