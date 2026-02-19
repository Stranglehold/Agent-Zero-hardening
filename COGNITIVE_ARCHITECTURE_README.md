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
