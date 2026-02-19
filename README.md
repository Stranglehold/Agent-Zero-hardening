# Agent-Zero Hardening Layer

A drop-in companion repo for [agent-zero](https://github.com/frdel/agent-zero) that compensates for the architectural assumptions agent-zero makes about its underlying model. Built specifically for local model deployment (Qwen3-14B, GLM-4.7 Flash, Devstral Small) where the "brilliant generalist" assumption breaks down.

Nothing here modifies agent-zero's core Python source files. All changes deploy through agent-zero's own extension hook system and prompt override directories. Prompt patches replace specific .md files in /a0/prompts/ (originals are backed up automatically). Extensions add new files to /a0/python/extensions/ subdirectories — no existing extension files are modified or removed.

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
# Agent-Zero Cognitive Architecture
## Military-Doctrine Hardening Layers & Organization Kernel

A modular cognitive architecture that transforms Agent-Zero from a single-agent chat assistant into a role-based, self-supervising organization capable of autonomous task execution with structured escalation, graph-based workflows, and A2A protocol interoperability.

Built for local LLM deployment (Qwen 14B on RTX 3090). Designed to compensate for local model limitations through deterministic scaffolding rather than relying on model reasoning alone.

---

## Architecture Overview

```
User Message
  │
  ▼
┌─────────────────────────────────────────────────────┐
│  EXTENSION PIPELINE (before_main_llm_call)          │
│                                                     │
│  _10_ Belief State Tracker (BST)                    │
│       └─ 18-domain classifier, slot extraction      │
│  _12_ Organization Dispatcher                       │
│       └─ Role selection, PACE monitoring, SALUTE    │
│  _15_ Graph Workflow Engine                         │
│       └─ DAG traversal, branching, retry loops      │
│  _20_ Context Watchdog                              │
│       └─ Token utilization tracking                 │
└─────────────────────────┬───────────────────────────┘
                          │
                          ▼
                   Model Generates Response
                          │
                          ▼
┌─────────────────────────────────────────────────────┐
│  TOOL EXECUTION PIPELINE                            │
│                                                     │
│  _20_ Meta-Reasoning Gate (tool_execute_before)     │
│       └─ Arg validation, auto-correction            │
│  _30_ Tool Fallback Advisor (tool_execute_before)   │
│       └─ Error-pattern advice injection             │
│  _30_ Tool Fallback Logger (tool_execute_after)     │
│       └─ Error classification, failure tracking     │
└─────────────────────────┬───────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────┐
│  POST-EXECUTION PIPELINE (message_loop_end)         │
│                                                     │
│  _10_ History Organization                          │
│  _50_ Supervisor Loop                               │
│       └─ Anomaly detection, steering injection      │
│  _90_ Save Chat                                     │
└─────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────┐
│  EXTERNAL INTERFACES                                │
│                                                     │
│  Agent-Zero Web UI (existing, port 5000)            │
│  A2A Protocol Server (new, port 8200)               │
│       └─ Agent Card, task lifecycle, SSE streaming  │
└─────────────────────────────────────────────────────┘
```

---

## Components

### Layer 0: Foundation — Organization Kernel

The organizational backbone. Implements military command doctrine as a coordination protocol for agent task routing.

**Files:**
- `/a0/python/extensions/before_main_llm_call/_12_org_dispatcher.py`
- `/a0/usr/organizations/` (org definitions, role profiles, reports)

**Concepts:**
- **Role Profiles** — Capability definitions specifying which BST domains, graph workflows, and tools a role can use. Roles have a chain of command (reports_to), authority levels, and PACE failure doctrine.
- **SALUTE Reports** — Standardized status reports (Status, Activity, Location, Unit, Time, Environment) written to disk as JSON. Bridges microcosm (single container) and macrocosm (distributed containers) — same format, different transport.
- **PACE Escalation** — Four-tier failure response: Primary (normal), Alternate (self-recovery via fallback chain), Contingent (escalate to supervisor), Emergency (abort and report). Evaluated on every message loop iteration.
- **Organizations** — Directed hierarchy of roles with defined communication channels. Two templates included: `software_dev` (engineering + research branches) and `sigint_alpha` (intelligence collection).

**Activation:**
```bash
cp /a0/usr/organizations/software_dev.json /a0/usr/organizations/active.json
# Restart agent
```

### Layer 1: Intelligence — Belief State Tracker (BST)

Classifies every incoming message into one of 18 operational domains using fast regex pattern matching. Enriches the model's context with domain-specific slot values.

**File:** `/a0/python/extensions/before_main_llm_call/_10_belief_state_tracker.py`

**Domains:** codegen, refactor, bugfix, git_ops, docker_ops, dependency_mgmt, log_analysis, data_transform, api_integration, config_edit, file_ops, osint, conversational, meta_agent, skill_building, planning, analysis, unknown

**How it works:** Pattern matching against keyword lists per domain. Extracts slot values (file paths, languages, error types) from the message. Stores classification on `agent._bst_store` for downstream extensions. Zero model inference — pure deterministic classification.

### Layer 2: Operations — Graph Workflow Engine

Replaces linear step-sequences with directed graph workflows supporting branching, retry loops, conditional paths, and escalation nodes.

**Files:**
- `/a0/python/extensions/before_main_llm_call/_15_htn_plan_selector.py` (graph-aware replacement)
- `/a0/python/extensions/before_main_llm_call/htn_plan_library.json` (10 graph workflows)

**Node types:** `start`, `task`, `decision`, `escalate`, `exit`, `checkpoint`

**Edge conditions:** `on_success`, `on_fail`, `on_retry`, `on_exhaust`, `always`

**Included workflows:**
| Workflow | Trigger Domains | Key Feature |
|----------|----------------|-------------|
| bugfix_workflow | bugfix | reproduce → gather_context loop, fix → test retry loop |
| codegen_module | codegen | implement → test → fix cycle with bounded retries |
| git_feature_branch | git_ops | Handles dirty working directory gracefully |
| git_merge_pr | git_ops | Conflict detection and resolution branching |
| docker_build_deploy | docker_ops | Build → fix → rebuild loop |
| refactor_safe | refactor | Baseline tests → modify → revert on regression |
| file_backup_restore | file_ops | Verification at each stage |
| api_integration | api_integration | Auth → connect → test → handle failure |
| dependency_update | dependency_mgmt | Backup → update → test → rollback path |
| log_investigation | log_analysis | Collect → analyze → escalate if unresolved |

**Event system:** Every node transition, verification, retry, and escalation emits a typed event stored in the traversal state. The supervisor and SALUTE reporting consume these for operational awareness.

### Layer 3: Quality Control — Meta-Reasoning Gate

Validates tool call arguments before execution. Catches and auto-corrects common local model mistakes (wrong parameter names, missing required args, invalid values).

**File:** `/a0/python/extensions/tool_execute_before/_20_meta_reasoning_gate.py`

**Capabilities:**
- Static parameter validation against known tool schemas
- Alias resolution (e.g., `language` → `runtime` for code execution)
- Default value injection for missing required parameters
- Argument format correction

### Layer 4: Error Recovery — Tool Fallback Chain

Two-part system for classifying tool failures and injecting recovery guidance.

**Files:**
- `/a0/python/extensions/tool_execute_after/_30_tool_fallback_logger.py` (error classifier)
- `/a0/python/extensions/tool_execute_before/_30_tool_fallback_advisor.py` (advice injector)

**Error classifications:** timeout, not_found, permission, syntax, network, resource, dependency, execution

**How it works:** The logger classifies every tool response using regex patterns and tracks consecutive failures per tool. The advisor checks failure history before each tool call and injects specific recovery guidance into the agent's conversation history. Feeds PACE level monitoring — consecutive failures drive escalation.

### Layer 5: Supervision — Supervisor Loop

Post-execution monitor that detects operational anomalies and injects corrective steering.

**File:** `/a0/python/extensions/message_loop_end/_50_supervisor_loop.py`

**Anomaly detectors:**
| Anomaly | Signal | Action |
|---------|--------|--------|
| Stall | turns_since_progress > threshold | "Reassess your approach" |
| Loop | Same tool + same error 3+ times | "Try a different method" |
| Context exhaustion | context_fill > 80% | "Wrap up current task" |
| Cascade failure | 3+ different tools failing | "Verify your environment" |
| PACE escalation | Contingent or emergency | Role-specific PACE guidance |

**Cooldown system:** Each anomaly type has an independent cooldown (default 3 turns) to prevent flooding the model's context with repeated warnings.

### Layer 6: Memory — Working Memory Buffer

Entity extraction and short-term memory with decay. Tracks file paths, function names, error messages, and other entities across conversation turns.

**File:** `/a0/python/extensions/hist_add_before/_10_working_memory.py`

**Features:**
- Automatic entity extraction from messages
- 8-turn decay for temporal relevance
- Persists across role switches within the org kernel

### Layer 7: Identity — Personality Loader (AIEOS)

Loads character personalities from JSON profiles. Orthogonal to roles — personality defines voice and character, roles define operational capability.

**Files:**
- `/a0/usr/personalities/_active.json` (active personality)
- Personality profiles in `/a0/usr/personalities/`

**Active personality:** Major Zero (Metal Gear Solid) — AIEOS v1.2

### Layer 8: External Interface — A2A Compatibility Layer

Exposes the Organization Kernel as a Google Agent2Agent (A2A) protocol-compliant server. Any A2A client can discover capabilities, submit tasks, receive streaming status, and collect artifacts.

**Files:** `/a0/python/a2a_server/`

**Capabilities:**
- Dynamic Agent Card generation from active organization
- Task lifecycle management with SALUTE → A2A state mapping
- SSE streaming of graph workflow progress
- PACE → A2A state translation (contingent → `input-needed`, emergency → `failed`)
- Artifact collection from completed tasks

**Port:** 8200 (configurable)

**The client sees:** A capable agent that accepts work and delivers results. The organizational doctrine, graph workflows, PACE escalation, and SALUTE reporting are completely invisible to the client.

---

## Organization Templates

### software_dev — Software Development
```
CO (Commanding Officer)
├── Engineering XO
│   ├── Codegen Specialist     (codegen, refactor)
│   ├── Bugfix Specialist      (bugfix, log_analysis)
│   └── DevOps Specialist      (docker_ops, git_ops, dependency_mgmt)
└── Research XO
    ├── Analysis Specialist    (analysis, data_transform)
    └── OSINT Specialist       (osint, api_integration)
```

### sigint_alpha — Intelligence Collection
```
CO (Commanding Officer)
├── S2 (Intelligence) XO
│   ├── SIGINT Specialist      (osint, log_analysis)
│   ├── HUMINT Specialist      (analysis, conversational)
│   └── ELINT Specialist       (data_transform, api_integration)
└── Operations XO
    ├── Codegen Specialist     (codegen, skill_building)
    └── Infrastructure Specialist (docker_ops, config_edit)
```

---

## Data Flow

```
User: "fix the bug in auth.py"
  │
  ├─ BST classifies: domain=bugfix, slots={file_path: "auth.py"}
  │
  ├─ Dispatcher: bugfix → Bugfix Specialist role activated
  │    └─ SALUTE emitted, PACE evaluated (primary)
  │
  ├─ Graph Engine: bugfix_workflow matched
  │    └─ Current node: "reproduce" injected into model context
  │
  ├─ Model: reads role context + graph node + BST enrichment → executes tool
  │
  ├─ Meta Gate: validates tool args before execution
  ├─ Tool executes → Fallback Logger classifies result
  │
  ├─ Graph Engine: verification passes → traverse to "isolate" node
  │    └─ Event logged: node_verified, edge_followed
  │
  ├─ Supervisor: checks anomaly detectors → all nominal, no steering needed
  │    └─ SALUTE updated with progress
  │
  └─ A2A Server: polls SALUTE → streams status to any connected client
       └─ "Bugfix Workflow: isolating root cause (step 2/5, 40% complete)"
```

---

## Installation

### Prerequisites
- Agent-Zero v0.9.8+
- Python 3.10+
- Local LLM via LM Studio, Ollama, or compatible OpenAI-format API

### Install All Layers
```bash
chmod +x /a0/usr/install_all.sh
./install_all.sh
```

### Activate an Organization
```bash
cp /a0/usr/organizations/software_dev.json /a0/usr/organizations/active.json
```

### Start A2A Server
```bash
python -m a2a_server.run --config /a0/usr/organizations/a2a_config.json
```

### Verify
```bash
# Check SALUTE reports
for f in /a0/usr/organizations/reports/*_latest.json; do
  echo "=== $(basename $f) ==="
  python3 -m json.tool "$f" | head -15
done

# Check Agent Card
curl http://localhost:8200/.well-known/agent.json | python3 -m json.tool

# Clear extension cache after any changes
find /a0/python/extensions -type d -name __pycache__ -exec rm -rf {} +
```

---

## Design Principles

**Deterministic over probabilistic.** Every routing decision, failure classification, PACE evaluation, and graph traversal is rule-based. The model provides reasoning; the scaffolding provides structure.

**Backward compatible by default.** No `active.json` → no org kernel → no role routing. No graph field → linear plan execution. Every layer degrades gracefully when its prerequisites aren't met.

**Files over databases.** JSON on disk. Readable, editable, version-controllable. SALUTE reports as files bridge single-container and multi-container architectures without refactoring.

**Roles orthogonal to personality.** A SIGINT specialist can speak with any personality's voice. Capability and identity are independent dimensions.

**Military doctrine as coordination protocol.** Chain of command, PACE escalation, SALUTE reporting, and organizational hierarchy aren't aesthetic choices — they're battle-tested solutions to autonomous agent coordination with limited communication bandwidth.

---

## Roadmap

- [x] Belief State Tracker (BST v3)
- [x] Working Memory Buffer
- [x] Personality Loader (AIEOS)
- [x] Tool Fallback Chain
- [x] Meta-Reasoning Gate
- [x] Graph Workflow Engine (Attractor integration)
- [x] Organization Kernel (dispatcher, roles, SALUTE, PACE)
- [x] Supervisor Loop
- [x] A2A Compatibility Layer
- [ ] Model Evaluation Framework (profile failure patterns per model)
- [ ] Multi-container macrocosm (distributed agent coordination)
- [ ] Distributed compute pooling (cross-SSH resource sharing)
- [ ] A2UI integration (rich status displays for A2A clients)

---

## Acknowledgments

Architecture designed through collaborative sessions between a human field engineer and Claude (Anthropic). Implementations built by Claude Code (Sonnet 4.6) using Level 3 specification methodology — intent, schemas, and behavioral requirements provided; all implementation decisions made by the implementing agent.

Inspired by:
- [StrongDM Attractor](https://github.com/strongdm/attractor) — Graph-based workflow orchestration and provider-aligned toolsets
- [Google A2A Protocol](https://a2a-protocol.org) — Agent-to-agent interoperability standard
- [Agent-Zero](https://github.com/frdel/agent-zero) — The foundation framework

Military doctrine references: PACE planning, SALUTE reporting format, hierarchical command structure, and organizational deconfliction principles drawn from US Army field manuals.
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
