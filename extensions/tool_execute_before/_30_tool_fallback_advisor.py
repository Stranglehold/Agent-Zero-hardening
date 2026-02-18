from python.helpers.extension import Extension
from typing import Any

FAILURES_KEY = "_tool_failures"

# Consecutive failures before injecting advice
TOOL_THRESHOLD = 2
# Total recent failures before "step back" advice
GLOBAL_THRESHOLD = 5

# Static fallback map: (tool_name, error_type) -> advice string
# "any" as tool_name matches all tools for that error type
# "any" as error_type matches all errors for that tool
FALLBACK_MAP = {
    # code_execution_tool fallbacks
    ("code_execution_tool", "syntax"): (
        "The code has syntax errors. Review the code for typos, missing quotes, "
        "unmatched brackets, or incorrect indentation before retrying."
    ),
    ("code_execution_tool", "dependency"): (
        "A required package is missing. Install it first using: "
        "pip install <package> (for Python) or npm install <package> (for Node.js), "
        "then retry the original command."
    ),
    ("code_execution_tool", "timeout"): (
        "The command timed out. Consider: break it into smaller steps, "
        "add a timeout flag, or check if a process is hanging."
    ),
    ("code_execution_tool", "permission"): (
        "Permission denied. Try: run with sudo, check file ownership with ls -la, "
        "or verify you are operating in the correct directory."
    ),
    ("code_execution_tool", "not_found"): (
        "Command or file not found. Verify: correct path, correct spelling, "
        "command is installed. Use 'which <cmd>' or 'find / -name <file>' to locate."
    ),
    ("code_execution_tool", "network"): (
        "Network error. Check: is the target host reachable? Is a proxy required? "
        "Try 'ping <host>' or 'curl -v <url>' to diagnose."
    ),
    ("code_execution_tool", "resource"): (
        "System resource limit hit. Check: disk space with 'df -h', "
        "memory with 'free -m'. Clean up or free resources before retrying."
    ),

    # Web/knowledge tool fallbacks
    ("knowledge_tool", "not_found"): (
        "No relevant knowledge found. Try: broaden your search terms, "
        "use fewer keywords, or try alternative phrasing."
    ),
    ("knowledge_tool", "any"): (
        "Knowledge tool failed. Consider: use code_execution_tool to search "
        "the filesystem directly, or ask the user for clarification."
    ),

    # Call subordinate fallbacks
    ("call_subordinate", "timeout"): (
        "Subordinate agent timed out. Consider: simplify the delegated task, "
        "break it into smaller subtasks, or handle it directly."
    ),
    ("call_subordinate", "any"): (
        "Subordinate failed. Consider: handle the task directly instead of "
        "delegating, or rephrase the instruction more precisely."
    ),

    # Generic fallbacks for any tool
    ("any", "timeout"): (
        "Operation timed out. Break the task into smaller steps and retry."
    ),
    ("any", "permission"): (
        "Access denied. Check permissions and paths before retrying."
    ),
    ("any", "not_found"): (
        "Target not found. Verify names, paths, and spelling."
    ),
    ("any", "syntax"): (
        "Invalid syntax or arguments. Review the command format and retry."
    ),
    ("any", "network"): (
        "Network issue detected. Verify connectivity before retrying."
    ),
    ("any", "dependency"): (
        "Missing dependency. Install required packages first."
    ),
    ("any", "execution"): (
        "Execution error. Review the error message carefully, "
        "identify the root cause, and adjust your approach."
    ),
}

# Step-back advice when total failures accumulate
STEP_BACK_ADVICE = (
    "Multiple tool failures detected. Stop and reassess your approach. "
    "Consider: (1) Is there a simpler way to accomplish this task? "
    "(2) Are you missing information you should ask the user about? "
    "(3) Would a different tool or method work better?"
)


class ToolFallbackAdvisor(Extension):
    """Injects fallback guidance when consecutive tool failures are detected."""

    async def execute(self, tool_args: dict[str, Any] | None = None,
                      tool_name: str = "", **kwargs):
        try:
            failures = self.agent.get_data(FAILURES_KEY)
            if not failures:
                return

            consecutive = failures.get("consecutive", {})
            history = failures.get("history", [])

            advice_parts = []

            # Check consecutive failures for this specific tool
            tool_count = consecutive.get(tool_name, 0)
            if tool_count >= TOOL_THRESHOLD:
                # Find the most recent error type for this tool
                recent_error = None
                for entry in reversed(history):
                    if entry["tool"] == tool_name:
                        recent_error = entry["error_type"]
                        break

                if recent_error:
                    advice = self._lookup_fallback(tool_name, recent_error)
                    if advice:
                        advice_parts.append(advice)

            # Check global failure accumulation
            recent_total = sum(
                1 for entry in history[-GLOBAL_THRESHOLD:]
            )
            if recent_total >= GLOBAL_THRESHOLD:
                advice_parts.append(STEP_BACK_ADVICE)

            # Inject advice as a warning in agent history
            if advice_parts:
                full_advice = "\n".join(advice_parts)
                try:
                    self.agent.context.log.log(
                        type="warning",
                        content=f"[Fallback] {full_advice}"
                    )
                    # Add to history so the model sees it
                    self.agent.hist_add_warning(
                        f"Tool guidance: {full_advice}"
                    )
                except Exception:
                    pass

        except Exception:
            pass

    def _lookup_fallback(self, tool_name: str, error_type: str) -> str | None:
        """Look up fallback advice. Tries specific match, then wildcards."""
        # Exact match
        key = (tool_name, error_type)
        if key in FALLBACK_MAP:
            return FALLBACK_MAP[key]

        # Tool-specific, any error
        key = (tool_name, "any")
        if key in FALLBACK_MAP:
            return FALLBACK_MAP[key]

        # Any tool, specific error
        key = ("any", error_type)
        if key in FALLBACK_MAP:
            return FALLBACK_MAP[key]

        return None
