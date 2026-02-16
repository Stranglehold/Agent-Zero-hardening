from python.helpers.extension import Extension
from python.helpers import files
from agent import LoopData
import os
import re
import json

# Marker that identifies the tools block in loop_data.system
TOOLS_BLOCK_MARKER = "## Tools available:"

# Matches ### tool_name headings in tool spec files
TOOL_HEADING_RE = re.compile(r'^###\s+(\w+)', re.MULTILINE)

# Cache key for tool registry stored on agent between iterations
REGISTRY_CACHE_KEY = "_tiered_tools_registry"


def _build_tool_registry(agent) -> tuple[str, dict[str, str]]:
    """
    Reads all agent.system.tool.*.md files and returns:
    - compact_menu: single string, one line per tool (name + first description line)
    - full_specs: dict mapping tool_name -> full file content
    
    Cached on agent.data to avoid re-reading files every iteration.
    """
    cached = agent.get_data(REGISTRY_CACHE_KEY)
    if cached:
        return cached["menu"], cached["specs"]

    from python.helpers import subagents
    dirs = subagents.get_paths(agent, "prompts")

    # Collect all tool spec files across prompt directories
    tool_files = files.get_unique_filenames_in_dirs(dirs, "agent.system.tool.*.md")

    menu_lines = []
    full_specs = {}

    for tool_file in sorted(tool_files):
        try:
            content = files.read_prompt_file(tool_file, _agent=agent)
        except Exception:
            continue

        # Extract all tool names from ### headings in this file
        # Some files (like memory.md) define multiple tools
        headings = TOOL_HEADING_RE.findall(content)
        if not headings:
            continue

        # First non-empty, non-heading line after the first heading = description
        lines = content.splitlines()
        desc = ""
        past_heading = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("###"):
                past_heading = True
                continue
            if past_heading and stripped and not stripped.startswith("#"):
                desc = stripped[:120]  # cap description length
                break

        for tool_name in headings:
            menu_lines.append(f"- **{tool_name}**: {desc}")
            full_specs[tool_name] = content

    compact_menu = "\n".join(menu_lines)

    # Cache for this session
    agent.set_data(REGISTRY_CACHE_KEY, {"menu": compact_menu, "specs": full_specs})

    return compact_menu, full_specs


def _extract_tool_name(last_response: str) -> str | None:
    """
    Extracts tool_name from the previous iteration's LLM response.
    Handles ~~~json fenced blocks and raw JSON.
    Returns None if extraction fails.
    """
    if not last_response:
        return None

    # Strip ~~~ or ``` code fences
    cleaned = re.sub(r'~~~json|~~~|```json|```', '', last_response).strip()

    try:
        parsed = json.loads(cleaned)
        return parsed.get("tool_name")
    except Exception:
        # Fallback: regex extraction for dirty JSON
        match = re.search(r'"tool_name"\s*:\s*"([^"]+)"', last_response)
        return match.group(1) if match else None


class TieredToolInjection(Extension):
    async def execute(self, loop_data: LoopData = LoopData(), **kwargs):
        # Locate the tools block in the assembled system prompt list
        tools_idx = None
        for i, segment in enumerate(loop_data.system):
            if TOOLS_BLOCK_MARKER in segment:
                tools_idx = i
                break

        if tools_idx is None:
            return  # Tools block not found — skip silently

        # Build registry (cached after first call)
        try:
            compact_menu, full_specs = _build_tool_registry(self.agent)
        except Exception:
            return  # Registry build failed — leave tools block untouched

        if not compact_menu or not full_specs:
            return  # Nothing to work with

        # Detect which tool was active in the previous iteration
        active_tool = _extract_tool_name(loop_data.last_response)

        # Build replacement block
        # Always inject: compact menu header + one-liner per tool
        # Conditionally inject: full spec for active tool only
        replacement_parts = [
            TOOLS_BLOCK_MARKER,
            "Select a tool from the list below. Full usage details follow for your current tool.\n",
            compact_menu,
        ]

        if active_tool and active_tool in full_specs:
            replacement_parts.append(
                f"\n---\n**Active tool — full spec:**\n{full_specs[active_tool]}"
            )
        else:
            # First iteration or unknown tool — inject response tool in full
            # so the model always knows how to terminate a task
            response_spec = full_specs.get("response", "")
            if response_spec:
                replacement_parts.append(
                    f"\n---\n**response tool — full spec:**\n{response_spec}"
                )

        loop_data.system[tools_idx] = "\n".join(replacement_parts)
