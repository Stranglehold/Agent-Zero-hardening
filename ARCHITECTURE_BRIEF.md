# Architecture Brief — Agent-Zero Hardening Layer

> **Purpose:** This document is the entry point for any AI development session working on this repo.
> Read it before writing or modifying any code. It contains the full architectural context,
> current repo state, known issues, design principles, and the prioritized build roadmap.

---

## What This Is

A drop-in companion repo for [agent-zero](https://github.com/frdel/agent-zero) that compensates
for the gap between agent-zero's design assumptions (frontier models like GPT-4 / Claude Opus)
and the reality of running local models at the 7–30B parameter scale.

Nothing here forks agent-zero or touches its core Python. All changes deploy through agent-zero's
own extension and prompt override systems, so they survive upstream updates.

**Target runtime:** Kali Linux Docker container running agent-zero.
**Hardware:** RTX 3090 (24GB VRAM).
**Models:** Qwen3-14B (supervisor), Qwen3-8B (utility). Previously GLM-4.7 Flash as utility.
**Inference server:** LM Studio with speculative decoding.

---

## Repo Location and Deployment

```
Source:  /a0/usr/hardening/          (this repo, inside the Docker container)
Deploy:  /a0/prompts/                (layers 1, 3)
         /a0/python/extensions/      (layers 2, 5)
         /a0/skills/                 (layer 4)
```

Install: `bash install_all.sh` — idempotent, backs up originals, safe to re-run.
After docker pull: `bash update.sh` — git pull + conflict check + full reinstall.

---

## Current Layer Architecture

| Layer | Purpose | Deployment Target | Status |
|-------|---------|-------------------|--------|
| 1 | Framework message replacements | `/a0/prompts/fw.*` | ✅ Deployed |
| 2 | Loop architecture extensions | `/a0/python/extensions/` | ✅ Deployed |
| 3 | System prompt patches | `/a0/prompts/agent.system.*` | ✅ Deployed |
| 4 | Reusable skill templates | `/a0/skills/` | ✅ Deployed |
| 5 | Belief State Tracker (BST) | `/a0/python/extensions/before_main_llm_call/` | ✅ Deployed |

### Layer Details

**Layer 1 — fw-replacements:** Rewrites agent-zero's recovery messages (misformat, repeat, nudge,
error, tool_not_found, warning) with explicit imperative language and inline schema reminders.
Each message tells the model exactly one thing wrong and exactly one thing to do next.

**Layer 2 — extensions:**
- `_20_structured_retry.py` (error_format) — appends tool call schema on JSON parse failures
- `_30_failure_tracker.py` (error_format) — consecutive failure budget, reflection prompt at threshold
- `_20_reset_failure_counter.py` (tool_execute_after) — resets failure counter on success
- `_20_context_watchdog.py` (before_main_llm_call) — token budget monitoring at 70%/85%
- `_95_tiered_tool_injection.py` (message_loop_prompts_after) — dynamic tool spec loading
- `_11_working_memory.py` (hist_add_before) — structured entity cache with decay and promotion

**Layer 3 — prompt-patches:**
- `agent.system.main.solving.md` — Step 0 classification gate (conversational vs task)
- `agent.system.main.tips.md` — Local model vocabulary, tool/terminal disambiguation
- `agent.system.tool.response.md` — Tightened response tool schema
- `agent.system.tool.skills.md` — Corrected skills_tool colon syntax documentation

**Layer 4 — skills:**
- `create-skill/SKILL.md` — Meta-skill for building new skills correctly

**Layer 5 — translation-layer (BST):**
- `_11_belief_state_tracker.py` (v3) — Intent classification + slot filling + message enrichment + working memory integration
- `slot_taxonomy.json` (v1.2.0) — 18 intent domains, deterministic resolver chains, `working_memory_lookup` resolver

---

## ✅ Resolved Repo Issues (Session 4)

All three issues from the previous session have been fixed:

1. **Duplicate BST files** — Stale v2 copies removed from `extensions/before_main_llm_call/`
   and `extensions/translation-layer/`. Only the canonical v3 in `translation-layer/` remains.
2. **Debug print statements** — All `print(..., flush=True)` stripped from canonical v3 BST.
   Bare `except:` clauses replaced with `except Exception:`.
3. **Duplicate slot_taxonomy.json** — Stale copies removed. The vestigial
   `extensions/translation-layer/` directory has been emptied.

---

## Design Principles

These are non-negotiable. Every extension, skill, and prosthetic must follow them.

### 1. Deterministic preprocessing beats probabilistic prompt engineering
20ms of regex and keyword matching eliminates entire categories of model confusion.
Never ask the model to do something that string matching or a decision tree can do.

### 2. Prosthetics are model-agnostic
The BST doesn't care what model sits below it. Extensions must work with Qwen, GPT-OSS,
Devstral, or future models. No model-specific assumptions in the processing logic.

### 3. Graceful degradation always
Every extension wraps its logic in try/except and degrades to passthrough on failure.
The hardening layer never blocks agent-zero from operating.

### 4. Read-merge-write on config files
**Never overwrite.** Agent-zero's `/a0/usr/settings.json` is a partial override layer.
Always read the existing file, merge changes, write back. `cat >` destroyed the config
in a previous session and broke the agent.

### 5. Local models execute reliably, not reason reliably
Build decision trees, not reasoning chains. Template libraries, not dynamic planners.
The model's job is to follow the rails, not lay them.

### 6. Extension patterns
- Base class: `python.helpers.extension.Extension`
- Method: `async execute(self, loop_data: LoopData = LoopData(), **kwargs)`
- Numeric prefix controls execution order within hook directory (lower = earlier)
- Store persistent state in `self.agent.data` dict or custom attributes on `self.agent`
- Store per-iteration state in `loop_data.params_temporary`
- Log via `self.agent.context.log.log(type="info"|"warning", content="...")`

---

## Agent-Zero Extension Hook Points

| Hook Directory | When It Fires | Key Extensions |
|----------------|---------------|----------------|
| `before_main_llm_call` | After prompt assembly, before LLM call | BST (_10), Watchdog (_20) |
| `message_loop_prompts_after` | After system prompt segments assembled | Tiered tools (_95) |
| `error_format` | On RepairableException during tool processing | Structured retry (_20), Failure tracker (_30) |
| `tool_execute_after` | After successful tool execution | Reset failure counter (_20) |
| `tool_execute_before` | Before tool execution (unused by us, available) | — |
| `hist_add_before` | Before message added to history (content_data, ai) | Working Memory (_10) |
| `response_stream_after` | After response stream completes (available) | — |

---

## Agent-Zero Message Format

**IMPORTANT:** Agent-zero uses a **dict-based** message format internally, NOT LangChain objects.

```python
# User message
{"ai": False, "content": "refactor agent.py"}

# AI message
{"ai": True, "content": {"thoughts": "...", "tool_name": "...", "tool_args": {...}}}

# User message with structured content
{"ai": False, "content": {"user_message": "fix the bug", "attachments": [...]}}
```

`loop_data.history_output` is a list of these dicts. To find the last user message:
```python
for msg in reversed(history_output):
    if isinstance(msg, dict) and not msg.get('ai', True):
        # This is a user message
```

The v1/v2 BST used LangChain `HumanMessage` objects — that's why they broke.
The v3 BST correctly uses dict access. **All new extensions must use dict format.**

---

## Cognitive Architecture Roadmap

Prioritized build list. Each item is a standalone extension that composes with existing layers.

### ✅ Priority 1: Working Memory Buffer (DONE — Session 4)
**File:** `extensions/hist_add_before/_11_working_memory.py` (~250 lines)
**BST integration:** `working_memory_lookup` resolver wired into 17 slot definitions across all domains.
**Taxonomy:** `slot_taxonomy.json` updated to v1.2.0.

Extracts structured entities (file paths, URLs, IPs, container/image names, ports, branches,
packages, config keys, services) from every message via regex. Entities decay after 8 turns.
Entities mentioned 3+ times promote to persistent (never-decay) store. BST checks working
memory before falling back to `history_scan`, giving faster and more reliable slot resolution.

### Priority 2: Tool Fallback Chain
**Problem:** Tool failures cause loops. Model retries the same broken approach.

**Solution:** Static fallback map (not dynamic reasoning) + failure pattern logging.

**Implementation:**
- **Hook:** `tool_execute_after` with error classification
- **Fallback map:** Hardcoded per-tool-per-error remediation
  ```
  code_execution + "permission denied" → sudo prefix
  code_execution + "timeout" → retry smaller input
  web_search + "connection error" → cached results
  file_write + "path not found" → mkdir -p parent, retry
  ```
- **Failure logging:** SQLite table: `{tool, error_class, input_summary, resolution, timestamp}`
- **Extension size:** ~150 lines
- **Why #2:** Prevents workflow breaks, builds empirical failure data over time.

### Priority 3: Meta-Reasoning Gate (Parameter Validation)
**Problem:** Model fires tool calls with empty, pronoun-only, or placeholder parameters.
Wasted tool calls that always fail.

**Solution:** Deterministic parameter completeness check before tool execution.

**Implementation:**
- **Hook:** `tool_execute_before`
- **Validation per tool:**
  ```
  web_search: query not empty, not pronoun-only, not placeholder
  code_execution: code field not empty, runtime field valid
  file operations: path not empty, path looks like a real path
  ```
- **On failure:** Block execution, inject clarification request
- **Extension size:** ~120 lines
- **Why #3:** Cheap, deterministic, prevents wasted cycles.

### Priority 4: HTN Plan Templates
**Problem:** Complex multi-step tasks cause the model to attempt everything at once or lose
track of progress.

**Solution:** Template library of common workflows. Model selects a plan, doesn't generate one.

**Implementation:**
- **Hook:** BST domain classification triggers plan selection
- **Template format:**
  ```json
  {
    "trigger": "migrate database",
    "steps": [
      {"action": "backup", "tool": "bash", "verify": "file_exists"},
      {"action": "export", "tool": "code_execution", "verify": "non_empty"},
      {"action": "import", "depends_on": "export"},
      {"action": "verify", "depends_on": "import"}
    ]
  }
  ```
- **Each step has verification; failures route to tool fallback chain.**
- **Extension size:** ~200 lines + plan template JSON
- **Why #4:** Structured execution for complex tasks without runtime planning.

### NOT Building (and why)
- **Uncertainty Quantification:** Local models are miscalibrated. Confidence scores would
  give false signal worse than no signal. Build verification into tool fallback chain instead.
- **Reflection/Critique Layer:** This is CI/CD (run `ruff`/`shellcheck`), not cognitive
  architecture. A 30-line post-execution lint hook covers it.

---

## Development Rules for This Repo

### File Creation
1. All new extensions go in the appropriate subdirectory under `extensions/`
2. Mirror the extension in the corresponding `translation-layer/` or layer directory
3. Add install logic to the relevant `install_*.sh` script
4. Update `install_all.sh` layer registry if adding a new layer

### Testing
1. Code is written HERE (the repo). Code RUNS inside the Docker container.
2. Do not execute agent-zero commands — write files that deploy into the container.
3. After writing an extension, document how to verify it works (log grep patterns, test inputs).

### Config File Safety
```python
# CORRECT: read-merge-write
import json
with open("/a0/usr/settings.json") as f:
    settings = json.load(f)
settings["new_key"] = "new_value"
with open("/a0/usr/settings.json", "w") as f:
    json.dump(settings, f, indent=2)

# WRONG: overwrite
# cat > /a0/usr/settings.json << 'EOF'
# This destroyed the config in a previous session.
```

### Commit Convention
```
feat: implement [extension name]
fix: correct [what was broken]
refactor: clean up [what changed]
docs: update [which document]
```

---

## Reference Files to Read Before Building

Before writing any new extension, read these files to understand the patterns:

| File | Why |
|------|-----|
| `translation-layer/_11_belief_state_tracker.py` | Canonical BST v3 — dict message handling, slot resolution, enrichment, working memory integration |
| `extensions/hist_add_before/_11_working_memory.py` | Working Memory Buffer — entity extraction, decay, promotion, BST integration |
| `extensions/before_main_llm_call/_20_context_watchdog.py` | Clean minimal extension — how to read agent state, log properly |
| `extensions/error_format/_30_failure_tracker.py` | How to track state across iterations using `agent.data` |
| `extensions/message_loop_prompts_after/_95_tiered_tool_injection.py` | How to read/modify `loop_data.system` prompt segments |
| `translation-layer/slot_taxonomy.json` | The 18-domain taxonomy driving BST classification (v1.2.0) |

For agent-zero internals:
| File | Why |
|------|-----|
| `/a0/python/helpers/extension.py` | Extension base class and lifecycle |
| `/a0/agent.py` | Core agent loop, `prepare_prompt()`, `LoopData` structure |
| `/a0/python/extensions/message_loop_prompts_after/_50_recall_memories.py` | Memory recall system — how utility model calls work |

---

## Session History

This repo was built across multiple sessions:

1. **Sonnet 4.5 session (~6 hours):** Built BST v1→v2→v3, all 5 layers, 18-domain taxonomy,
   prompt patches, fw replacements, full install/update/check infrastructure. Debugged
   the LangChain→dict message format transition. Accidentally destroyed settings.json
   with `cat >` overwrite.

2. **Opus 4.6 session #1:** Fixed memory recall loop (single-model collision when both
   supervisor and utility pointed at same Qwen3-14B). Separated models: Qwen3-14B supervisor,
   Qwen3-8B utility. Identified stale BST copies, debug print statements, and repo cleanup
   needs. Revised Sonnet's cognitive architecture roadmap with honest assessment of what
   works and what's a trap for local models. Established Claude Code + API development workflow.

3. **Opus 4.6 session #2:** Wrote this architecture brief, prepared roadmap.

4. **Opus 4.6 session #3 (current):** Resolved all three known repo issues (stale BST
   copies, debug prints, duplicate taxonomy). Built Working Memory Buffer (`_11_working_memory.py`,
   ~250 lines) at `hist_add_before` hook. Integrated with BST via `working_memory_lookup`
   resolver across 17 slot definitions. Updated taxonomy to v1.2.0. Next: Priority 2
   (Tool Fallback Chain).
