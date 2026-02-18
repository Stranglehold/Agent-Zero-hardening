# Tool Fallback Chain — Build Spec for Claude Code

Read ARCHITECTURE_BRIEF.md first. This is Priority 2 in the cognitive architecture roadmap.

## Problem
When a tool call fails, local models often retry with identical arguments, enter
error loops, or pick a random alternative tool. They lack the strategic judgment
to select appropriate fallback actions based on the failure type.

## Solution
A static fallback map that classifies tool failures by error pattern and suggests
deterministic recovery actions. No model reasoning required — pure pattern matching.

## Architecture

### Hook Points (VERIFIED from agent.py lines 905-916)

**tool_execute_after** — fires after every tool execution
- Parameters: `response: Response | None = None, tool_name: str = "", **kwargs`
- Response object: `Response(message: str, break_loop: bool, additional: dict | None)`
- This is where we detect failures and log them

**tool_execute_before** — fires before every tool execution  
- Parameters: `tool_args: dict[str, Any] | None = None, tool_name: str = "", **kwargs`
- This is where we inject fallback suggestions into the context

### Existing Extensions on These Hooks (DO NOT CONFLICT)
- `tool_execute_after/_10_mask_secrets.py` — masks secrets in response
- `tool_execute_after/_20_reset_failure_counter.py` — resets failure tracker on success
- `tool_execute_before/_10_replace_last_tool_output.py` — replaces placeholder tokens
- `tool_execute_before/_10_unmask_secrets.py` — unmasks secrets in args

Use numeric prefix `_30_` for our extensions to run after existing ones.

### Data Flow

```
Tool executes → tool_execute_after fires
  → _30_tool_fallback_logger.py:
    1. Classify response as success/failure using error patterns
    2. If failure: identify error type (timeout, not_found, permission, syntax, etc.)
    3. Store failure record in agent.data["_tool_failures"]
    4. Increment consecutive failure count per tool

Next iteration → model decides to call a tool → tool_execute_before fires  
  → _30_tool_fallback_advisor.py:
    1. Check agent.data["_tool_failures"] for recent failures
    2. If consecutive failures >= threshold for this tool:
       - Look up fallback map for tool_name + error_type
       - Inject fallback hint into a warning message via agent history
    3. If total failures across all tools >= global threshold:
       - Inject "step back and reassess" guidance
```

## Files to Create

### 1. extensions/tool_execute_after/_30_tool_fallback_logger.py

```python
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

    def _classify_response(self, message: str) -> str | None:
        """Classify response message. Returns error type or None for success."""
        if not message:
            return None

        for pattern, error_type in ERROR_PATTERNS:
            if re.search(pattern, message):
                return error_type

        return None
```

### 2. extensions/tool_execute_before/_30_tool_fallback_advisor.py

```python
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
                    f"⚠️ Tool guidance: {full_advice}"
                )
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
```

### 3. scripts/install_tool_fallback.sh

```bash
#!/bin/bash
# Layer: Tool Fallback Chain
# Installs tool failure classification and fallback advisory extensions

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
SOURCE_EXT="$REPO_DIR/extensions"
TARGET_EXT="/a0/python/extensions"

echo "[ToolFallback] Installing tool fallback chain..."

# tool_execute_after — failure logger
AFTER_DIR="$TARGET_EXT/tool_execute_after"
mkdir -p "$AFTER_DIR"
if [ -f "$SOURCE_EXT/tool_execute_after/_30_tool_fallback_logger.py" ]; then
    cp "$SOURCE_EXT/tool_execute_after/_30_tool_fallback_logger.py" "$AFTER_DIR/"
    echo "[ToolFallback] Installed failure logger"
fi

# tool_execute_before — fallback advisor
BEFORE_DIR="$TARGET_EXT/tool_execute_before"
mkdir -p "$BEFORE_DIR"
if [ -f "$SOURCE_EXT/tool_execute_before/_30_tool_fallback_advisor.py" ]; then
    cp "$SOURCE_EXT/tool_execute_before/_30_tool_fallback_advisor.py" "$BEFORE_DIR/"
    echo "[ToolFallback] Installed fallback advisor"
fi

echo "[ToolFallback] Done. Failure classification and fallback advisory active."
```

### 4. Add to install_all.sh

Add after existing install steps:
```bash
bash scripts/install_tool_fallback.sh
```

## Key Design Decisions

1. **Two extensions, not one.** Logger runs AFTER execution (classifies results).
   Advisor runs BEFORE execution (injects guidance). Clean separation of concerns.

2. **Static fallback map.** No model reasoning about what to try next. The map
   is a dict keyed by (tool_name, error_type). Lookup is O(1). Model receives
   plain text advice it can follow.

3. **Threshold before advice.** First failure gets no advice — could be transient.
   Second consecutive failure on the same tool triggers fallback lookup. This
   prevents noise on one-off errors.

4. **Global step-back.** If 5+ recent failures accumulate across any tools,
   inject "stop and reassess" guidance. This catches spiral-of-failure loops.

5. **History capped at 20.** Enough to detect patterns, not enough to bloat
   agent.data.

6. **Graceful degradation.** All exceptions caught and passed through. If the
   fallback system itself fails, tool execution continues normally.

7. **Works with existing failure tracker.** The existing _20_reset_failure_counter.py
   uses TRACKER_KEY = "_failure_tracker". We use FAILURES_KEY = "_tool_failures".
   No collision. Both can coexist — theirs resets on success, ours provides
   advisory guidance.

8. **Advice injected as hist_add_warning.** This puts the guidance directly into
   the conversation history where the model will see it on the next reasoning
   step. Same mechanism agent-zero uses for its own error messages.

## Verification

After deployment, trigger a failure deliberately:
```
run this command: cat /nonexistent/file/path.txt
```
Then immediately:
```
try that again
```

On the second attempt, check logs for:
- `[Fallback]` warning with "not_found" advice
- The advice should mention verifying paths and using find

Then cause 5+ failures rapidly and look for the step-back advice.

## Files Summary
- extensions/tool_execute_after/_30_tool_fallback_logger.py (~80 lines)
- extensions/tool_execute_before/_30_tool_fallback_advisor.py (~120 lines)  
- scripts/install_tool_fallback.sh
- Update install_all.sh

## IMPORTANT
- Read existing extensions on these hooks before writing anything
- Match the exact parameter signatures from the verified hooks:
  - tool_execute_after: response: Response | None = None, **kwargs (tool_name in kwargs)
  - tool_execute_before: tool_args: dict[str, Any] | None = None, tool_name: str = "", **kwargs
- Use numeric prefix _30_ to run after existing extensions
- DO NOT modify any existing extension files
- Follow the Extension base class pattern from python.helpers.extension
