# Organization Kernel — Build Specification (Level 3)
## Agent-Zero Cognitive Architecture · Foundation Layer

**Implementation note:** This spec defines intent, schemas, integration contracts, and
behavioral requirements. It does not contain implementation code. The implementing agent
(Claude Code) reads the Agent-Zero source, understands the extension system, and makes
all implementation decisions. The spec defines WHAT must happen and WHERE it integrates.
The implementing agent decides HOW.

---

## Mission

Replace the current "every extension runs on every message" model with role-based
coordination using military organizational doctrine as the coordination protocol.

Three schemas. One dispatcher extension. Zero changes to existing extensions (except
one filter addition to HTN). Full backward compatibility when no organization is active.

---

## Concepts

### Role
An operational capability profile. Defines what an agent in this role can do (BST domains,
HTN plans, tools), who it reports to (chain of command), and how it handles failure (PACE
plan). A role is to operational capability what an AIEOS personality is to voice and character.
They are orthogonal — a SIGINT specialist can speak with Major Zero's voice.

### SALUTE Report
Fixed-format status report emitted at regular intervals. Named after the military reporting
format: Status, Activity, Location, Unit, Time, Environment. Any supervisor can parse any
subordinate's SALUTE without understanding the subordinate's internal state. Written to
disk as JSON — same format works for local microcosm and distributed macrocosm.

### Organization
A directed hierarchy of roles with defined communication channels. One org is active at a
time. Defines which roles exist, who reports to whom, and the mission objective.

### PACE Plan
Four-tier failure response doctrine: Primary (normal execution), Alternate (self-recovery),
Contingent (escalate to supervisor), Emergency (abort and report). Each tier has a trigger
condition and a prescribed action.

### Microcosm / Macrocosm
Microcosm: all roles run inside a single container. Role "switching" means the dispatcher
activates different capability sets per message. Sequential execution.
Macrocosm: each role runs in its own container with its own model. Concurrent execution.
The schemas and coordination patterns are identical in both modes — only the transport
layer changes.

---

## Schema 1: Role Profile

### File Location
`/a0/usr/organizations/roles/<role_id>.json`

### Schema
```json
{
  "_schema": "orgkernel:role_profile",
  "_version": "1.0",

  "role_id": "sigint_specialist",
  "role_name": "SIGINT Specialist",
  "role_type": "specialist | executive | commander",

  "chain_of_command": {
    "reports_to": "s2_xo",
    "authority_level": "1 (specialist) | 2 (executive) | 3 (commander)",
    "can_delegate": false
  },

  "capabilities": {
    "bst_domains": ["osint", "log_analysis", "data_transform", "analysis"],
    "htn_plans": ["log_investigation", "data_transform"],
    "tools_primary": ["search_engine", "browser_agent", "code_execution_tool"],
    "tools_secondary": ["memory_load", "memory_save"],
    "skills": []
  },

  "requirements": {
    "min_context_tokens": 8192,
    "preferred_model": null,
    "required_extensions": ["belief_state_tracker", "htn_plan_selector", "working_memory"]
  },

  "pace_plan": {
    "primary": {
      "description": "Execute task using preferred tools and HTN plan",
      "action": "normal_execution"
    },
    "alternate": {
      "description": "Self-recovery via tool fallback chain",
      "action": "fallback_chain",
      "trigger": "consecutive_tool_failures >= 3"
    },
    "contingent": {
      "description": "Report inability to supervisor for reassignment",
      "action": "escalate",
      "trigger": "consecutive_tool_failures >= 5 OR context_fill > 0.85",
      "escalate_to": "s2_xo"
    },
    "emergency": {
      "description": "Abort task, preserve state, report up",
      "action": "abort_and_report",
      "trigger": "unrecoverable_error OR turns_without_progress > max * 1.5",
      "escalate_to": "s2_xo"
    }
  },

  "doctrine": {
    "salute_interval_turns": 5,
    "max_turns_without_progress": 12,
    "report_on_completion": true,
    "report_on_failure": true,
    "autonomous_retry_limit": 2
  }
}
```

### Role Types

| Type | Authority Level | Can Delegate | Purpose |
|------|----------------|--------------|---------|
| `commander` | 3 | Yes | Mission definition, resource allocation, inter-branch deconfliction |
| `executive` | 2 | Yes | Task decomposition, subordinate monitoring, PACE management |
| `specialist` | 1 | No | Task execution, SALUTE reporting, self-recovery |

---

## Schema 2: SALUTE Report

### File Location
Written to: `/a0/usr/organizations/reports/<role_id>_latest.json`
Archived to: `/a0/usr/organizations/reports/archive/<role_id>_<timestamp>.json`

### Schema
```json
{
  "_schema": "orgkernel:salute_report",
  "_version": "1.0",

  "status": {
    "state": "idle | active | waiting | error_recovery | escalating | complete | aborted",
    "progress": 0.0,
    "pace_level": "primary | alternate | contingent | emergency",
    "health": "nominal | degraded | critical"
  },

  "activity": {
    "current_task": "Human-readable description of current work",
    "bst_domain": "",
    "htn_plan": "",
    "htn_step": 0,
    "htn_total_steps": 0,
    "current_tool": "",
    "iterations_on_current_step": 0
  },

  "location": {
    "working_directory": "",
    "files_modified": [],
    "files_read": [],
    "resources_claimed": []
  },

  "unit": {
    "role_id": "",
    "role_name": "",
    "agent_number": 0,
    "reports_to": "",
    "organization": ""
  },

  "time": {
    "timestamp": "ISO-8601",
    "task_started": "ISO-8601 or null",
    "elapsed_seconds": 0,
    "turns_elapsed": 0,
    "turns_since_progress": 0,
    "context_turns_remaining": null
  },

  "environment": {
    "model": "",
    "context_fill_pct": 0.0,
    "context_tokens_used": 0,
    "context_tokens_max": 0,
    "gpu_available": true,
    "tool_failures_consecutive": 0,
    "tool_failures_total": 0,
    "memory_fragments_stored": 0
  }
}
```

### SALUTE Emission Rules
1. Emit on the schedule defined by `doctrine.salute_interval_turns` in the active role profile.
2. Emit immediately on state transitions: any change in `status.state` or `status.pace_level`.
3. Each emission overwrites `<role_id>_latest.json` and creates a timestamped copy in `archive/`.
4. Archive files older than 1 hour are eligible for cleanup (not mandatory to implement in v1).

### Computing SALUTE Fields
- `progress`: Derived from HTN state if plan is active (completed steps / total steps). Otherwise 0.
- `health`: `critical` if PACE level is contingent or emergency. `degraded` if PACE is alternate or consecutive failures >= 2. Otherwise `nominal`.
- `turns_since_progress`: Read from HTN state's staleness counter if available. Otherwise tracked independently.
- Environment fields: Read from agent config, context watchdog data, and tool fallback chain state wherever these are available on the agent object.

---

## Schema 3: Organization Definition

### File Location
`/a0/usr/organizations/<org_id>.json`
Active organization: `/a0/usr/organizations/active.json`

### Schema
```json
{
  "_schema": "orgkernel:organization",
  "_version": "1.0",

  "org_id": "software_dev",
  "org_name": "Software Development Organization",
  "description": "",

  "mission": {
    "objective": "",
    "success_criteria": "",
    "constraints": []
  },

  "hierarchy": {
    "<role_id>": {
      "role_id": "",
      "role_name": "",
      "subordinates": ["<role_id>", ...]
    }
  },

  "communication_channels": {
    "command": {
      "description": "Orders flow down, reports flow up",
      "direction": "bidirectional_hierarchical",
      "protocol": "salute_reports"
    },
    "lateral": {
      "description": "Peer coordination within same branch",
      "direction": "bidirectional_peer",
      "protocol": "direct_message",
      "allowed_pairs": []
    }
  },

  "mode": "microcosm",

  "microcosm_config": {
    "execution_model": "sequential_role_switching",
    "role_activation": "bst_domain_routing",
    "state_sharing": "shared_agent_object",
    "salute_storage": "filesystem"
  },

  "macrocosm_config": {
    "execution_model": "concurrent_containers",
    "role_activation": "announce_volunteer",
    "state_sharing": "shared_volume",
    "salute_storage": "shared_volume",
    "network": {
      "protocol": "ssh",
      "discovery": "static_manifest",
      "heartbeat_interval_seconds": 30
    }
  }
}
```

---

## Organization Templates to Build

### 1. `software_dev` — Primary working organization

```
CO (mission: build/modify software)
├── Engineering XO
│   ├── Codegen Specialist     (domains: codegen, refactor)
│   ├── Bugfix Specialist      (domains: bugfix, log_analysis)
│   └── DevOps Specialist      (domains: docker_ops, git_ops, dependency_mgmt)
└── Research XO
    ├── Analysis Specialist    (domains: analysis, data_transform)
    └── OSINT Specialist       (domains: osint, api_integration)
```

Build complete role profiles for every role in this org. Map each role's `htn_plans`
to the 10 existing plans in the HTN library. Map `tools_primary` based on which tools
are most relevant to that role's BST domains. Set reasonable PACE thresholds for each
role type (specialists get shorter leashes, executives get longer ones).

### 2. `sigint_alpha` — Intelligence collection organization

```
CO (mission: collect and analyze intelligence)
├── S2 (Intelligence) XO
│   ├── SIGINT Specialist      (domains: osint, log_analysis)
│   ├── HUMINT Specialist      (domains: analysis, conversational)
│   └── ELINT Specialist       (domains: data_transform, api_integration)
└── Operations XO
    ├── Codegen Specialist     (domains: codegen, skill_building)
    └── Infrastructure Specialist (domains: docker_ops, config_edit)
```

Build complete role profiles for every role in this org.

---

## Dispatcher Extension

### Integration Point
- **Hook:** `before_main_llm_call`
- **Numeric prefix:** `_12_` — after BST (`_10_`), before HTN (`_15_`)
- **File:** `/a0/python/extensions/before_main_llm_call/_12_org_dispatcher.py`

### Behavioral Requirements

**Activation:**
- On every `before_main_llm_call` invocation, check if an active organization exists.
- If no `active.json` in the organizations directory, return immediately. All existing
  behavior preserved. This is the backward-compatibility guarantee.

**Role Selection:**
- Read the BST domain classification from `agent._bst_store` (same pattern as HTN does).
- Look up which role in the active organization handles that domain by checking each
  role profile's `capabilities.bst_domains`.
- If multiple roles handle the same domain, prefer specialists over executives.
- If no role matches the domain (e.g., "conversational"), pass through without role activation.
- Store the active role profile on the agent object so other extensions can read it.

**HTN Filtering:**
- When a role is activated, store the role's `capabilities.htn_plans` list on the agent
  in a location the HTN plan selector can read.
- The HTN plan selector must be modified to check this filter: if the filter exists and
  the matched plan_id is not in the filter, skip that plan. If the filter is null or
  absent, all plans are allowed (backward compatibility).
- This is a one-line addition to the existing HTN plan matching logic.

**SALUTE Emission:**
- Track a turn counter on the agent object.
- When the counter hits the active role's `doctrine.salute_interval_turns`, build a SALUTE
  report from available agent state and write it to disk.
- Also emit immediately when PACE level changes or task state transitions.
- Gather data for SALUTE fields from: BST belief state, HTN plan state, tool fallback
  chain failure counters, context watchdog data, agent config. Use whatever is available;
  leave fields at defaults if a data source isn't present.

**PACE Monitoring:**
- On every invocation, evaluate the active role's PACE trigger conditions against current
  agent state (tool failure counters, turns without progress, context fill).
- Track the current PACE level on the agent object.
- When PACE level escalates, log a warning and emit an immediate SALUTE report.
- When conditions improve (failures reset, progress resumes), restore to primary and log.
- PACE evaluation should be defensive — if any state read fails, assume nominal and continue.

**Role Change Logging:**
- When the active role changes (different domain routed to different role), log the transition.
- This gives visibility into how tasks flow through the organization.

**Error Handling:**
- The dispatcher must never block execution. Any exception at any point results in a
  passthrough — the message proceeds as if no organization were active.
- Log errors as warnings for debugging but never raise.

### Integration Contracts

**Reads from:**
| Source | Key/Location | Data |
|--------|-------------|------|
| BST | `agent._bst_store["__bst_belief_state__"]["domain"]` | Domain classification |
| HTN | `agent._htn_state` | Plan progress, staleness counter |
| Tool Fallback | `agent._tool_consecutive_failures` (verify actual attr name in source) | Failure counts |
| Agent Config | `agent.config` | Model name, context settings |

**Writes to:**
| Destination | Key/Location | Data |
|-------------|-------------|------|
| Agent object | `agent._org_active_role` | Current role profile dict |
| Agent object | `agent._org_active` | Cached org definition dict |
| Agent object | `agent._org_pace_level` | Current PACE level string |
| Agent data | `agent.set_data("_org_htn_allowed_plans", [...])` | HTN filter list |
| Filesystem | `/a0/usr/organizations/reports/<role_id>_latest.json` | SALUTE report |
| Filesystem | `/a0/usr/organizations/reports/archive/` | SALUTE archive |

**Important:** Before implementing, read the actual agent.py source, the BST extension,
the HTN extension, and the tool fallback extensions to verify the exact attribute names
and data structures used to store state. The attribute names listed above are based on
the spec documents — the actual implementation may use slightly different names. Use
what's actually in the code, not what's in this spec.

---

## Directory Structure

```
/a0/usr/organizations/
├── active.json                         # Copy of active org definition
├── software_dev.json                   # Software dev org template
├── sigint_alpha.json                   # Intelligence org template
├── roles/
│   ├── co.json
│   ├── engineering_xo.json
│   ├── research_xo.json
│   ├── s2_xo.json
│   ├── ops_xo.json
│   ├── codegen_specialist.json
│   ├── bugfix_specialist.json
│   ├── devops_specialist.json
│   ├── analysis_specialist.json
│   ├── osint_specialist.json
│   ├── sigint_specialist.json
│   ├── humint_specialist.json
│   ├── elint_specialist.json
│   └── infrastructure_specialist.json
└── reports/
    └── archive/
```

---

## Integration Map

How existing extensions relate to organizational functions:

| Extension | Hook | Org Function |
|-----------|------|-------------|
| BST | `before_main_llm_call/_10_` | Intelligence — provides domain classification that drives role selection |
| **Org Dispatcher** | `before_main_llm_call/_12_` | **NEW** — Command routing based on BST + org chart |
| HTN Plan Selector | `before_main_llm_call/_15_` | Operations planning — plans filtered to role's capability set |
| Context Watchdog | `before_main_llm_call/_20_` | Resource monitoring — feeds SALUTE environment data |
| Working Memory | `hist_add_before/_10_` | Institutional knowledge — available to all roles |
| Tiered Tool Injection | `message_loop_prompts_after/_95_` | Armory — future: filter to role's tools |
| Meta-Reasoning Gate | `tool_execute_before/_20_` | QC — validates all tool calls regardless of role |
| Tool Fallback Chain | `tool_execute_after/_30_` | NCO error recovery — failure counts feed PACE |
| Personality Loader | `system_prompt` | Unit culture — orthogonal to role, applies to all |

---

## Testing Criteria

### Test 1: Backward Compatibility
- Delete or don't create `active.json`
- Agent must behave identically to pre-kernel operation
- No ORG log entries, no SALUTE files, no role activation
- All existing extensions function unchanged

### Test 2: Role Activation
- Create `active.json` pointing to `software_dev` org
- Send a message that BST classifies as "bugfix"
- Dispatcher must activate the Bugfix Specialist role
- Log must show `[ORG] Role activated: Bugfix Specialist` or equivalent
- HTN must only match plans listed in the bugfix specialist's `htn_plans`

### Test 3: Role Switching
- Send a bugfix message, then a git message
- First message activates Bugfix Specialist, second activates DevOps Specialist
- Both transitions logged
- HTN filter changes between messages

### Test 4: SALUTE Emission
- With an active org, run the agent for more turns than `salute_interval_turns`
- A `<role_id>_latest.json` file must exist in the reports directory
- The file must be valid JSON conforming to the SALUTE schema
- An archive copy must exist with a timestamp in the filename

### Test 5: PACE Escalation
- Trigger multiple consecutive tool failures (e.g., cat nonexistent files repeatedly)
- PACE level must escalate from primary → alternate → contingent
- Each escalation logged
- SALUTE emitted on each transition
- When failures stop, PACE must restore to primary

### Test 6: HTN Filtering
- With `software_dev` org active, the codegen specialist's role should only allow
  `codegen_module` from the HTN library (and whatever other plans are listed)
- A message that would normally trigger `bugfix_workflow` should NOT activate that
  plan when the active role is the codegen specialist (wrong role for that domain)

### Test 7: No False Role Assignment
- Send a conversational message ("what time is it")
- No role should activate (conversational is not in any specialist's bst_domains)
- No SALUTE emission, no PACE evaluation
- Agent responds normally

---

## Installation

### Script: `install_org_kernel.sh`

**Must do:**
1. Copy the dispatcher extension to `before_main_llm_call/` with prefix `_12_`
2. Create the directory structure under `/a0/usr/organizations/`
3. Copy all organization templates and role profiles
4. Clear `__pycache__` in the target extension directory
5. Print activation instructions (how to copy an org template to `active.json`)

**Must not do:**
- Automatically create `active.json` — activation should be explicit
- Modify any existing extension files (except the one-line HTN filter, if bundled)

### Addition to `install_all.sh`
Add as the first layer (Foundation), before all other layers.

---

## Future Phases (Not Built Now, but Schema-Compatible)

**Phase 2: Supervisor Loop** — extension on `message_loop_end` that reads SALUTE reports
and injects steering messages when PACE triggers fire. The microcosm version reads its
own SALUTE and self-corrects. The macrocosm version reads subordinate SALUTE files.

**Phase 3: Announce Function** — network discovery, job posting, capability-based
self-selection. Agents volunteer for tasks that match their role profile.

**Phase 4: Multi-Container Orchestration** — container lifecycle, shared filesystem
with vector clocks, partition tolerance, cross-SSH resource pooling.

These phases require no changes to the schemas defined here. The role profiles, SALUTE
reports, and org definitions work unchanged across all phases.
