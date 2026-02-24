"""
Tool Format Adapter â€" Model Compatibility Layer
=================================================
Normalizes tool call responses from different model families into
a canonical format that the eval framework can score uniformly.

The Problem:
    The eval framework expects tool calls as JSON in the 'content' field:
        {"tool_name": "...", "tool_args": {...}}

    But different model families return tool invocations differently:
    - Standard (Qwen, Llama): JSON in content field â†' works as-is
    - GPT-OSS (Harmony):      tool_calls array, reasoning_content with
                               Harmony markers, or channel-based format
    - Future models:           unknown formats

This adapter sits between the API response and the scoring logic,
extracting tool calls from wherever the model puts them and returning
them in the canonical format.

Usage:
    adapter = ToolFormatAdapter(model_family="gpt-oss")
    canonical = adapter.normalize(raw_api_response)
    # canonical = {"tool_name": "code_execution_tool", "tool_args": {"runtime": "terminal", "code": "ls /tmp"}}
"""

import json
import re
from typing import Optional


# ---------------------------------------------------------------------------
# Model family detection
# ---------------------------------------------------------------------------

MODEL_FAMILY_PATTERNS = {
    "gpt-oss":  ["gpt-oss", "gptoss"],
    "qwen":     ["qwen"],
    "llama":    ["llama", "meta-llama"],
    "glm":      ["glm", "chatglm"],
    "deepseek": ["deepseek"],
    "gemma":    ["gemma"],
    "phi":      ["phi"],
    "mistral":  ["mistral", "mixtral"],
}


def detect_model_family(model_name: str) -> str:
    """Detect model family from model name string."""
    name_lower = model_name.lower()
    for family, patterns in MODEL_FAMILY_PATTERNS.items():
        if any(p in name_lower for p in patterns):
            return family
    return "standard"


# ---------------------------------------------------------------------------
# Canonical tool call format
# ---------------------------------------------------------------------------

def make_canonical(tool_name: str, tool_args: dict) -> dict:
    """Create a canonical tool call dict."""
    return {"tool_name": tool_name, "tool_args": tool_args}


# ---------------------------------------------------------------------------
# Extraction strategies
# ---------------------------------------------------------------------------

def _extract_from_content(content: str) -> Optional[dict]:
    """Try to extract a tool call JSON from the content string.
    This is the standard path â€" works for Qwen, Llama, and any model
    that puts JSON directly in the content field."""
    if not content:
        return None

    # Direct parse
    try:
        parsed = json.loads(content.strip())
        if isinstance(parsed, dict):
            return parsed
    except (json.JSONDecodeError, ValueError):
        pass

    # Extract from code block
    if "```" in content:
        blocks = content.split("```")
        for i in range(1, len(blocks), 2):
            block = blocks[i]
            if block.startswith("json"):
                block = block[4:]
            block = block.strip()
            try:
                parsed = json.loads(block)
                if isinstance(parsed, dict):
                    return parsed
            except (json.JSONDecodeError, ValueError):
                continue

    # Find first { ... } pair
    start = content.find("{")
    end = content.rfind("}")
    if start != -1 and end > start:
        try:
            parsed = json.loads(content[start:end + 1])
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, ValueError):
            pass

    return None


def _extract_from_tool_calls(tool_calls: list) -> Optional[dict]:
    """Extract tool call from OpenAI-format tool_calls array.
    This handles models/runtimes that return structured tool_calls
    in the API response (e.g., LM Studio with Harmony translation)."""
    if not tool_calls or not isinstance(tool_calls, list):
        return None

    tc = tool_calls[0]  # Take the first tool call
    if not isinstance(tc, dict):
        return None

    # OpenAI format: {"function": {"name": "...", "arguments": "..."}}
    func = tc.get("function", {})
    if func:
        name = func.get("name", "")
        args_str = func.get("arguments", "{}")
        try:
            args = json.loads(args_str) if isinstance(args_str, str) else args_str
        except (json.JSONDecodeError, ValueError):
            args = {}
        if name:
            return make_canonical(name, args if isinstance(args, dict) else {})

    # Direct format: {"name": "...", "arguments": {...}}
    name = tc.get("name", "")
    args = tc.get("arguments", tc.get("args", {}))
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except (json.JSONDecodeError, ValueError):
            args = {}
    if name:
        return make_canonical(name, args if isinstance(args, dict) else {})

    return None


def _extract_from_reasoning_content(reasoning: str) -> Optional[dict]:
    """Extract tool call from Harmony-format reasoning_content.

    GPT-OSS may embed tool calls in reasoning_content with markers like:
        <|start|>assistant<|channel|>commentary to=functions.tool_name json<|message|>{"arg": "val"}

    This parser handles known Harmony patterns."""
    if not reasoning:
        return None

    # Pattern 1: to=functions.TOOL_NAME json<|message|>{...}
    match = re.search(
        r'to=functions\.(\w+)\s+json\s*(?:<\|message\|>)?\s*(\{[^}]+\})',
        reasoning,
        re.DOTALL,
    )
    if match:
        tool_name = match.group(1)
        try:
            args = json.loads(match.group(2))
            return make_canonical(tool_name, args if isinstance(args, dict) else {})
        except (json.JSONDecodeError, ValueError):
            pass

    # Pattern 2: tool call info as structured text in reasoning
    # Some models describe the tool call rather than format it
    # Look for JSON embedded anywhere in reasoning
    start = reasoning.find("{")
    end = reasoning.rfind("}")
    if start != -1 and end > start:
        candidate = reasoning[start:end + 1]
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict) and ("tool_name" in parsed or "name" in parsed):
                return parsed
        except (json.JSONDecodeError, ValueError):
            pass

    return None


def _extract_from_harmony_content(content: str) -> Optional[dict]:
    """Extract tool call from content that contains Harmony channel markers.

    Some configurations pass Harmony-formatted content through the content
    field rather than reasoning_content."""
    if not content:
        return None

    # Check for Harmony markers
    if "<|" not in content:
        return None

    # Try extracting from Harmony channel format
    # Pattern: <|start|>assistant<|channel|>tool json<|message|>{...}
    match = re.search(
        r'<\|channel\|>\s*(?:tool|commentary)\s+(?:to=functions\.)?(\w+)\s+json\s*<\|message\|>\s*(\{.+?\})',
        content,
        re.DOTALL,
    )
    if match:
        tool_name = match.group(1)
        try:
            args = json.loads(match.group(2))
            return make_canonical(tool_name, args if isinstance(args, dict) else {})
        except (json.JSONDecodeError, ValueError):
            pass

    # Fallback: strip all Harmony markers and try JSON extraction
    cleaned = re.sub(r'<\|[^|]+\|>', ' ', content).strip()
    return _extract_from_content(cleaned)


# ---------------------------------------------------------------------------
# Normalizer: maps Agent-Zero tool names to eval-expected names
# ---------------------------------------------------------------------------

# GPT-OSS may use different tool names when trained with Harmony's
# built-in tools. This maps common variants to the canonical names
# used in the eval fixtures.
TOOL_NAME_ALIASES = {
    # Harmony built-in names â†' Agent-Zero names
    "python":           "code_execution_tool",
    "bash":             "code_execution_tool",
    "terminal":         "code_execution_tool",
    "shell":            "code_execution_tool",
    "execute":          "code_execution_tool",
    "exec":             "code_execution_tool",
    "run_code":         "code_execution_tool",
    "browser":          "search_engine",
    "web_search":       "search_engine",
    "search":           "search_engine",
    "save_memory":      "memory_save",
    "load_memory":      "memory_load",
    "delegate":         "call_subordinate",
    "reply":            "response",
    "respond":          "response",
}


def _normalize_tool_name(name: str) -> str:
    """Map model-specific tool names to canonical eval names."""
    return TOOL_NAME_ALIASES.get(name.lower(), name)


def _infer_runtime_from_context(tool_call: dict, original_content: str) -> dict:
    """For code_execution_tool calls that are missing 'runtime',
    try to infer it from context clues."""
    args = tool_call.get("tool_args", {})
    if tool_call.get("tool_name") != "code_execution_tool":
        return tool_call
    if "runtime" in args:
        return tool_call

    code = args.get("code", "")
    content_lower = (original_content or "").lower()

    # Heuristics for runtime inference
    if any(indicator in code for indicator in ["import ", "print(", "def ", "class "]):
        args["runtime"] = "python"
    elif any(indicator in code for indicator in ["ls ", "cd ", "mkdir ", "cat ", "grep ",
                                                   "pip ", "apt ", "docker ", "git "]):
        args["runtime"] = "terminal"
    elif any(indicator in code for indicator in ["node ", "npm ", "require(", "const "]):
        args["runtime"] = "nodejs"
    elif "python" in content_lower:
        args["runtime"] = "python"
    else:
        args["runtime"] = "terminal"  # Default fallback

    tool_call["tool_args"] = args
    return tool_call


# ---------------------------------------------------------------------------
# Main adapter class
# ---------------------------------------------------------------------------

class ToolFormatAdapter:
    """Normalizes tool call responses across model families.

    Usage:
        adapter = ToolFormatAdapter("gpt-oss")
        result = adapter.extract_tool_call(raw_response_dict)
        # result = {"tool_name": "code_execution_tool", "tool_args": {"runtime": "terminal", "code": "ls /tmp"}}
    """

    def __init__(self, model_family: str = "standard"):
        self.model_family = model_family.lower()

    def extract_tool_call(self, raw_response: dict) -> Optional[dict]:
        """Extract a canonical tool call from a raw API response dict.

        Args:
            raw_response: The full response dict from the API, containing
                         'content', optionally 'tool_calls', 'reasoning_content', etc.

        Returns:
            Canonical dict {"tool_name": str, "tool_args": dict} or None.
        """
        content = raw_response.get("content", "") or ""
        tool_calls = raw_response.get("tool_calls")
        reasoning = raw_response.get("reasoning_content", "") or ""

        result = None

        if self.model_family == "gpt-oss":
            # GPT-OSS extraction priority:
            # 1. tool_calls array (LM Studio may translate Harmony â†' OpenAI format)
            # 2. Harmony markers in content
            # 3. Harmony markers in reasoning_content
            # 4. Standard JSON in content (fallback)
            result = (
                _extract_from_tool_calls(tool_calls)
                or _extract_from_harmony_content(content)
                or _extract_from_reasoning_content(reasoning)
                or _extract_from_content(content)
            )
        else:
            # Standard extraction priority:
            # 1. Standard JSON in content
            # 2. tool_calls array (some runtimes provide both)
            # 3. Reasoning content (rare but possible)
            result = (
                _extract_from_content(content)
                or _extract_from_tool_calls(tool_calls)
                or _extract_from_reasoning_content(reasoning)
            )

        if result is None:
            return None

        # Normalize tool name
        raw_name = result.get("tool_name", result.get("name", ""))
        result["tool_name"] = _normalize_tool_name(raw_name)

        # Ensure tool_args exists
        if "tool_args" not in result:
            result["tool_args"] = (
                result.pop("args", None)
                or result.pop("arguments", None)
                or result.pop("tool_args", None)
                or {}
            )

        # Infer missing runtime for code execution
        result = _infer_runtime_from_context(result, content)

        return result

    def extract_content_text(self, raw_response: dict) -> str:
        """Extract the plain text content, stripping Harmony markers if present."""
        content = raw_response.get("content", "") or ""

        if self.model_family == "gpt-oss" and "<|" in content:
            # Strip Harmony channel markers to get plain text
            cleaned = re.sub(r'<\|[^|]+\|>', ' ', content)
            return cleaned.strip()

        return content
