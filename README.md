# Agent-Zero Hardening Layer

A drop-in companion repo for [agent-zero](https://github.com/frdel/agent-zero) that compensates for the architectural assumptions agent-zero makes about its underlying model. Built specifically for local model deployment (Qwen3-14B, GLM-4.7 Flash, Devstral Small) where the "brilliant generalist" assumption breaks down.

Nothing here forks agent-zero or touches its core Python. All changes deploy through agent-zero's own extension and prompt override systems, so they survive upstream updates with minimal maintenance.

---

## The problem this solves

Agent-zero was designed around frontier models (GPT-4, Claude Opus) that handle ambiguity, repair malformed output, manage token budgets, and infer intent reliably. Local models at the 7–30B scale violate these assumptions in predictable ways:

- Tool call JSON frequently malforms, triggering DirtyJSON repair that leaves loop state dirty
- Recovery prompts written for GPT-4 use vocabulary and syntax local models don't map correctly
- Ambiguous user input ("fix it", "clean that up") causes intent drift — the model guesses rather than asks
- Context window fills silently with no internal pressure-relief mechanism
- Repeated tool failures accumulate without a failure budget enforcing escalation

Each layer in this repo targets one of these failure modes.

---

## Repository structure

```
/a0/usr/hardening/
├── install_all.sh                  Master installer — run this
├── update.sh                       Pull repo + reinstall after docker update
├── setup_github.sh                 First-time git configuration
├── check_skills_upstream.sh        Check skills for upstream conflicts
│
├── fw-replacements/                Layer 1 — Recovery message hardening
│   ├── fw.error.md
│   ├── fw.msg_misformat.md
│   ├── fw.msg_nudge.md
│   ├── fw.msg_repeat.md
│   ├── fw.tool_not_found.md
│   ├── fw.warning.md
│   ├── install_fw_replacements.sh
│   └── check_fw_upstream.sh
│
├── extensions/                     Layer 2 — Loop architecture extensions
│   ├── before_main_llm_call/
│   │   └── _20_context_watchdog.py
│   ├── error_format/
│   │   ├── _20_structured_retry.py
│   │   └── _30_failure_tracker.py
│   ├── message_loop_prompts_after/
│   │   └── _95_tiered_tool_injection.py
│   ├── tool_execute_after/
│   │   └── _20_reset_failure_counter.py
│   ├── install_extensions.sh
│   ├── install_failure_tracker.sh
│   └── check_extensions_upstream.sh
│
├── prompt-patches/                 Layer 3 — System prompt improvements
│   ├── agent.system.main.solving.md
│   ├── agent.system.main.tips.md
│   ├── agent.system.tool.response.md
│   ├── install_prompt_patches.sh
│   └── check_prompt_patches_upstream.sh
│
├── skills/                         Layer 4 — Reusable skill templates
│   └── create-skill/
│       └── SKILL.md
│
└── translation-layer/              Layer 5 — Belief state tracker (BST)
    ├── belief_state_tracker.py
    ├── slot_taxonomy.json
    ├── install_translation_layer.sh
    └── README.md
```

---

## Quick start

```bash
# First time only
cd /a0/usr/hardening
bash setup_github.sh
bash install_all.sh

# After any docker pull / agent-zero update
bash update.sh
```

After install, start a fresh agent chat. Prompt files and extensions load at runtime — no container restart needed, but a new chat context is required for the system prompt changes to take effect.

---

## Maintenance commands

```bash
# Check whether upstream agent-zero changed any files we've overridden
bash install_all.sh --check-only

# Reinstall only one layer (e.g. after editing translation-layer files)
bash install_all.sh --layer=5

# Pull latest hardening repo changes and reinstall everything
bash update.sh

# Commit new work
git add .
git commit -m "describe what changed"
git push
```

---

## Layer 1 — Framework message replacements

**Deployment target:** `/a0/prompts/`
**Install:** `fw-replacements/install_fw_replacements.sh`

Agent-zero's recovery messages were written for models with strong instruction-following and large vocabularies. When a local model misformats a tool call or enters a loop, the originals don't give it enough structured guidance to self-correct — they use phrasing the model may not map to the right behavior.

These replacements rewrite each recovery message with explicit, imperative language and inline schema reminders so the model has everything it needs in one place without backtracking to the system prompt.

| File | When it fires |
|------|--------------|
| `fw.msg_misformat.md` | Tool call JSON was unparseable |
| `fw.msg_repeat.md` | Agent is repeating the same action |
| `fw.msg_nudge.md` | Agent stalled without producing output |
| `fw.error.md` | General runtime error during tool execution |
| `fw.tool_not_found.md` | Named tool doesn't exist in the registry |
| `fw.warning.md` | Non-fatal warning from tool execution |

**Design principle:** Each message tells the model exactly one thing it did wrong and exactly one thing to do next. No ambiguity, no multi-step explanation, no assumptions about prior context retention.

---

## Layer 2 — Loop architecture extensions

**Deployment target:** `/a0/python/extensions/`
**Install:** `extensions/install_extensions.sh` + `extensions/install_failure_tracker.sh`

Extensions hook into specific points in agent-zero's message loop. Files within each hook directory execute alphabetically — numeric prefixes control order.

### `_20_structured_retry.py` — Schema-aware error formatting
**Hook:** `error_format`

When `process_tools` raises a `RepairableException` (malformed JSON, parse failure), this intercepts the error message and appends the expected tool call schema inline. The model's next turn sees both the failure reason and the exact structure it needs to produce — without re-reading the system prompt. Reduces secondary loops after misformat events.

### `_30_failure_tracker.py` — Failure budget enforcement
**Hook:** `error_format`

Tracks consecutive failures per agent turn using a counter in agent context. If failures exceed the threshold (default: 3), it escalates by injecting a hard stop that forces the model to report the problem to the user rather than continuing to retry. Prevents infinite degradation loops where the model keeps attempting the same broken approach.

### `_20_reset_failure_counter.py` — Budget reset on success
**Hook:** `tool_execute_after`

Paired with the failure tracker. Resets the consecutive failure counter whenever a tool call succeeds, so the budget is per-streak rather than per-session.

### `_20_context_watchdog.py` — Token budget visibility
**Hook:** `before_main_llm_call`

Counts tokens across all prompt components before each LLM call using agent-zero's own `approximate_tokens()`. Logs warnings at 70% and 85% of the configured context window. Stores the count in `loop_data.params_temporary["context_token_count"]` as a hook point for future summarizer extensions. Default window: 100k tokens, overridable per-agent.

### `_95_tiered_tool_injection.py` — Dynamic tool loading
**Hook:** `message_loop_prompts_after`

Agent-zero's default behavior includes all tool definitions in every system prompt. For local models with limited context windows this is unnecessary token burn on tools the current task won't use. This extension implements tiered loading: all tools stay registered, but full specifications are only injected for tools relevant to the current task type.

---

## Layer 3 — Prompt patches

**Deployment target:** `/a0/prompts/`
**Install:** `prompt-patches/install_prompt_patches.sh`

Targeted rewrites of specific agent-zero system prompt sections. These don't replace entire prompt files — they replace sections that produce consistently worse output on local models.

| File | What it patches |
|------|----------------|
| `agent.system.main.solving.md` | Problem-solving strategy — adds explicit state declarations and step verification requirements before tool calls |
| `agent.system.main.tips.md` | Behavioral tips — rewritten for local model vocabulary; removes references to capabilities these models lack |
| `agent.system.tool.response.md` | Tool response format — tightens the JSON schema description with worked examples |

**Upstream compatibility:** `check_prompt_patches_upstream.sh` diffs your installed versions against the originals backed up at install time. Run it before any `docker pull` to know whether upstream changed a file you've patched.

---

## Layer 4 — Skills

**Deployment target:** `/a0/skills/`
**Install:** `install_skills.sh`

Agent-zero's skill system injects structured guidance (SKILL.md files) at the point of need — they're only loaded when a task triggers the relevant skill, keeping them out of the base context window.

### `create-skill/SKILL.md` — Skill construction template

A meta-skill that guides the agent through building new skills correctly: proper SKILL.md format, trigger definition, structured content layout, and verification steps. Without it, local models often produce malformed skill files or skip required sections.

**Adding new skills:** Create a new folder under `skills/` containing a `SKILL.md`. The install script picks it up automatically on next run.

---

## Layer 5 — Translation layer (Belief State Tracker)

**Deployment target:** `/a0/python/extensions/before_main_llm_call/`
**Install:** `translation-layer/install_translation_layer.sh`
**Detailed docs:** `translation-layer/README.md`

The root cause of most "it didn't understand what I meant" failures is unresolved ambiguity entering the model. Local models don't silently resolve underspecified input the way frontier models do — they either hallucinate a plausible interpretation or produce a generic response that misses the actual task.

The Belief State Tracker implements a [Task-Oriented Dialogue (TOD)](https://en.wikipedia.org/wiki/Dialogue_system) pipeline in front of the model. Every user message passes through three stages before the LLM sees it.

### Stage 1 — Domain classification

Trigger-keyword matching against a taxonomy of known intent domains defined in `slot_taxonomy.json`:

| Domain | Examples |
|--------|---------|
| `codegen` | "write a function", "generate a script" |
| `refactor` | "clean up", "restructure", "reorganize" |
| `bugfix` | "fix the error", "it's broken", "debug" |
| `agentic` | "run", "execute", "do this automatically" |
| `file_ops` | "move", "copy", "delete", "rename" |
| `analysis` | "explain", "summarize", "what does this do" |
| `osint` | "find", "look up", "research", "investigate" |
| `skill_building` | "create a skill", "build a tool" |
| `conversational` | everything else — always passes through |

Returns a domain name and a raw confidence score (0.0–1.0).

### Stage 2 — Slot resolution

For each required and optional slot in the matched domain, a resolver chain attempts to fill the value from available context. Resolvers run in order; first non-null result wins:

| Resolver | Method |
|----------|--------|
| `keyword_map` | Maps surface trigger words to canonical values |
| `file_extension_inference` | Derives language from `.py`, `.js` etc. in context |
| `last_mentioned_file` | Regex scan for `filename.ext` patterns in recent messages |
| `last_mentioned_path` | Regex scan for `/path/to/file` patterns |
| `last_mentioned_entity` | Last backtick-quoted or parenthetical entity |
| `history_scan` | Scan last 8 messages for slot-relevant content |
| `context_inference` | Lightweight keyword matching on current message |

### Stage 3 — Confidence scoring and branching

Final score = (trigger confidence × 0.4) + (slot fill rate × 0.6)

**Below threshold + missing required slots:**
Injects one targeted clarifying question as an AI message. The user's answer re-enters the pipeline next turn and fills the missing slot. Max one question per turn (`max_clarification_questions: 2` globally).

**At or above threshold:**
Replaces the original user message with an enriched version:
```
[TASK CONTEXT]    resolved slot key-value pairs
[INSTRUCTION]     domain-specific preamble from taxonomy
[USER MESSAGE]    original message verbatim
```

### Belief state persistence

Resolved slot state persists across turns (TTL: 6 turns, configurable in `slot_taxonomy.json` under `global.belief_state_ttl_turns`). Enables multi-turn slot filling:

```
Turn 1:  "refactor the auth module"
         → domain: refactor | target_file: None → asks: "Which file?"

Turn 2:  "agent/auth.py"
         → fills target_file → enriched message sent to model
```

Follow-up messages ("fix it", "do that again") detect the underspecified pattern and re-attach the prior turn's belief state rather than starting classification fresh.

### Extending the taxonomy

The entire behavior is driven by `slot_taxonomy.json`. Adding a new domain requires zero Python changes — add an entry to the JSON with triggers, slots, resolvers, threshold, and preamble. The tracker engine reads the taxonomy at init.

### Execution order

Installed as `_10_belief_state_tracker.py` — runs before the existing `_20_context_watchdog.py` in the same hook. No manual renaming required.

---

## Upgrade workflow after `docker pull`

Agent-zero updates can overwrite files in `/a0/prompts/` and `/a0/python/extensions/`. The check scripts diff your installed versions against originals backed up at install time.

```bash
cd /a0/usr/hardening

# 1. Check what upstream changed
bash install_all.sh --check-only

# 2. Review any diffs — if upstream improved something we've patched,
#    incorporate the change into the hardening version before reinstalling

# 3. Push hardening versions back
bash install_all.sh
```

`update.sh` wraps this entire sequence: `git pull` → conflict check → full reinstall.

---

## Architecture notes

**Why not fork agent-zero?**
Forks require manual merge work on every upstream update. Agent-zero's extension and prompt override systems are deliberately designed for this kind of injection. The hardening layer uses that design rather than fighting it.

**Why local models specifically need this:**
Frontier models handle ambiguity resolution, output self-correction, and tool schema compliance at inference time — they do implicit belief state tracking as part of generation. Local models at the 7–30B scale lack the capacity to do this reliably in addition to the actual task. Moving those responsibilities into deterministic preprocessing code removes cognitive load from inference where it doesn't belong.

**Graceful degradation throughout:**
Every extension wraps its logic in try/except and degrades to passthrough on any failure. The hardening layer never blocks agent-zero from operating — it either improves behavior or gets silently out of the way.

---

## Hardware

Developed and tested on RTX 3090 (24GB VRAM).
Primary models: Qwen3-14B-Instruct (supervisor), GLM-4.7 Flash (utility/parallel calls).
LM Studio with speculative decoding for throughput.
