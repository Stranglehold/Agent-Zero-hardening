# Model Evaluation Framework — Level 3 Specification
## Adaptive Configuration Profiling for Cognitive Architecture Hardening Layers

---

## Intent

Build a test harness that profiles any model loaded in LM Studio against the nine hardening layers, measures where it fails, and produces a configuration profile that tunes every layer to that model's specific strengths and weaknesses. The architecture becomes self-tuning — swap the model, load the matching profile, every threshold and parameter adjusts automatically.

This is not a benchmark suite. It does not produce a single score. It produces a JSON configuration file that the deployed hardening layers consume at runtime. The evaluation framework runs offline, separate from the live agent, and its only output is a model profile that improves the live agent's performance.

---

## Problem

Every hardening layer has configurable parameters — BST confidence thresholds, PACE escalation limits, graph workflow retry counts, memory injection caps, tool fallback patterns, meta-gate strictness levels. Currently these are set by intuition and not adjusted when the underlying model changes. A threshold tuned for Qwen3-14B may be too aggressive for GPT-OSS-20B or too permissive for Qwen3-8B.

Result: switching models degrades the hardening system because the prosthetics are calibrated for a model that's no longer running. The architecture is model-agnostic in design but model-specific in configuration. The evaluation framework closes that gap.

---

## Architecture Overview

```
Evaluation Run:
  Load model via LM Studio API → Run test battery (6 evaluation modules) →
  Collect per-layer metrics → Analyze failure patterns → Generate model profile JSON

Deployment:
  Agent startup → Read model profile → Each hardening layer loads its parameters
  from profile → Architecture adapts to current model
```

The framework is a standalone Python script, NOT an Agent-Zero extension. It runs outside the container, talks to LM Studio's API directly, and produces a JSON file that gets copied into the container. Extensions read the profile at initialization.

---

## Component 1: Test Harness

### Entry Point
`eval_runner.py` — Standalone script. Accepts model endpoint URL and model name.

```bash
python eval_runner.py \
  --api-base http://localhost:1234/v1 \
  --model-name "qwen3-14b-q4_k_m" \
  --output-dir ./profiles \
  --verbose
```

### Dependencies
- `requests` or `openai` Python client for LM Studio API calls
- No Agent-Zero dependencies. No Docker required. Runs on host machine.
- Test fixtures stored as JSON files alongside the script.

### Configuration
```json
{
  "api_base": "http://localhost:1234/v1",
  "model_name": "",
  "timeout_seconds": 120,
  "max_retries_per_test": 2,
  "test_modules": ["bst", "tool_reliability", "graph_compliance", "pace_calibration", "context_sensitivity", "memory_utilization"],
  "output_dir": "./profiles"
}
```

### Execution Model
Each test module runs independently. Modules can be run individually or as a full battery. Each module produces a sub-report. The harness aggregates sub-reports into the final model profile.

Test cases are deterministic. Same model + same quant + same temperature should produce reproducible profiles (within statistical noise from sampling). Run each test case 3 times and take the majority result to reduce variance.

---

## Component 2: Evaluation Modules

### Module 1: BST Classification Accuracy

**What it measures**: Does the model respond correctly to BST-enriched messages? Does enrichment help or confuse it?

**Test fixtures** (stored in `fixtures/bst_tests.json`):

Each fixture is a pair: raw user message + enriched version (as BST would produce it). The model receives both versions and we compare response quality.

```json
{
  "test_id": "bst_001",
  "domain": "bugfix",
  "raw_message": "it's broken",
  "enriched_message": "[TASK CONTEXT]\n  domain: bugfix\n  target_file: unknown\n  operation: diagnose\n[INSTRUCTION]\n  Ask the user which file or component is broken.\n  Do not attempt a fix without identifying the target.\n[USER MESSAGE]\n  it's broken",
  "expected_behavior": "asks_clarifying_question",
  "failure_indicators": ["attempts fix without target", "ignores task context", "repeats enrichment verbatim"]
}
```

**Evaluation dimensions**:

1. **Enrichment compliance rate**: Percentage of enriched messages where the model follows the injected instructions vs ignoring them. Send 20 enriched messages across different domains. Score: follows instruction / total.

2. **Enrichment confusion rate**: Percentage of enriched messages where the model treats the enrichment as conversation content rather than instruction (e.g., quotes the `[TASK CONTEXT]` block back to the user, asks about the enrichment format). Score: confused responses / total.

3. **Unenriched baseline**: Send the same 20 messages WITHOUT enrichment. Compare response quality to enriched versions. If the model performs better unenriched on certain domains, BST enrichment is hurting rather than helping for those domains — the profile should disable enrichment for them.

4. **Confidence threshold calibration**: Test messages at BST confidence boundaries (0.5, 0.6, 0.7, 0.8). For each threshold, measure whether the model handles ambiguous classifications correctly. If the model performs well on low-confidence enrichments, lower the threshold. If it degrades, raise it.

**Metrics produced**:
```json
{
  "bst_enrichment_compliance_rate": 0.85,
  "bst_enrichment_confusion_rate": 0.05,
  "bst_improvement_over_baseline": 0.20,
  "bst_optimal_confidence_threshold": 0.65,
  "bst_domains_where_enrichment_hurts": ["conversational"],
  "bst_confidence_adjustment": -0.05
}
```

### Module 2: Tool Reliability

**What it measures**: Which tool call failure patterns does this model exhibit? How should the tool fallback chain be configured?

**Test fixtures** (stored in `fixtures/tool_tests.json`):

Each fixture presents a task requiring a specific tool call and evaluates the model's output format.

```json
{
  "test_id": "tool_001",
  "system_prompt": "You have access to the following tools: [tool definitions]. Respond with a tool call in JSON format.",
  "user_message": "List the files in /tmp",
  "expected_tool": "bash",
  "expected_format": {"command": "ls /tmp"},
  "common_failures": ["malformed_json", "wrong_tool_name", "missing_required_param", "hallucinates_tool"]
}
```

**Evaluation dimensions**:

1. **JSON validity rate**: Percentage of tool calls that produce parseable JSON. Low rate → meta-gate should run JSON repair before forwarding.

2. **Parameter accuracy rate**: Percentage of tool calls with correct parameter names and types. Low rate → meta-gate should validate parameter names against tool schema.

3. **Tool selection accuracy**: Percentage of tasks where the model picks the correct tool. Confused tool selection → BST enrichment should include explicit tool hints.

4. **Failure pattern distribution**: Categorize all failures into the 8 error patterns the tool fallback chain handles (syntax_error, not_found, permission, timeout, import, connection, memory, generic). The distribution tells the fallback chain which patterns to prioritize.

5. **Recovery rate**: After receiving an error message, does the model correct its tool call? High recovery → fewer retries needed. Low recovery → earlier escalation.

**Metrics produced**:
```json
{
  "tool_json_validity_rate": 0.92,
  "tool_parameter_accuracy": 0.85,
  "tool_selection_accuracy": 0.90,
  "tool_failure_distribution": {
    "syntax": 0.40,
    "not_found": 0.25,
    "missing_param": 0.20,
    "hallucinated_tool": 0.10,
    "other": 0.05
  },
  "tool_recovery_rate": 0.70,
  "meta_gate_strictness": "moderate",
  "tool_fallback_priority_patterns": ["syntax", "not_found"]
}
```

### Module 3: Graph Workflow Compliance

**What it measures**: Does the model follow graph workflow instructions? How many retries per node? Does it wander off-plan?

**Test fixtures** (stored in `fixtures/graph_tests.json`):

Simulated graph workflow nodes with explicit instructions. The model receives the node context (what the BST + graph engine would inject) and we evaluate whether it follows the plan.

```json
{
  "test_id": "graph_001",
  "plan_name": "bugfix_workflow",
  "node_id": "reproduce",
  "node_instruction": "[WORKFLOW NODE: reproduce]\nYou are executing step 2 of 6 in the Bug Fix Workflow.\nCurrent task: Reproduce the reported bug.\nRequired output: Confirmation that the bug was reproduced, OR explanation of why it could not be reproduced.\nDo NOT proceed to fixing the bug. Only reproduce it.",
  "user_context": "There's a bug in auth.py — login fails for users with special characters in passwords",
  "expected_behavior": "attempts_reproduction_only",
  "failure_indicators": ["jumps to fix", "skips reproduction", "requests unrelated info", "ignores workflow context"]
}
```

**Evaluation dimensions**:

1. **Instruction adherence rate**: Percentage of nodes where the model stays within the node's scope. Does it do what the node says, or does it wander?

2. **Premature completion rate**: Percentage of nodes where the model tries to skip ahead (e.g., fix before reproducing, deploy before testing).

3. **Retry effectiveness**: Present the same node instruction twice (simulating a retry after a failed first attempt). Does the model change its approach or repeat the same failure?

4. **Escalation recognition**: Present a node with a problem the model genuinely can't solve. Does it signal failure (so PACE can escalate) or loop indefinitely?

**Metrics produced**:
```json
{
  "graph_instruction_adherence": 0.80,
  "graph_premature_completion_rate": 0.15,
  "graph_retry_effectiveness": 0.60,
  "graph_escalation_recognition": 0.50,
  "graph_max_retries_per_node": 3,
  "graph_stale_detection_turns": 8
}
```

### Module 4: PACE Calibration

**What it measures**: At what failure count does this model benefit from escalation guidance? What's the optimal threshold for each PACE tier?

**Test fixtures** (stored in `fixtures/pace_tests.json`):

Sequences of increasingly difficult problems. The model receives progressively stronger guidance matching PACE tiers.

```json
{
  "test_id": "pace_001",
  "scenario": "file_not_found_cascade",
  "attempts": [
    {"guidance_level": "none", "context": "Edit /tmp/config.yaml", "expected_failure": true},
    {"guidance_level": "primary", "context": "[PRIMARY] Edit /tmp/config.yaml. The file should exist in /tmp.", "expected_recovery": "low"},
    {"guidance_level": "alternate", "context": "[ALTERNATE] The file /tmp/config.yaml was not found. Check if the path is correct. Try: ls /tmp/ to see available files.", "expected_recovery": "medium"},
    {"guidance_level": "contingency", "context": "[CONTINGENCY] Multiple attempts failed. Create the file if missing: touch /tmp/config.yaml. Then edit it.", "expected_recovery": "high"},
    {"guidance_level": "emergency", "context": "[EMERGENCY] All approaches failed. Report this to the user with full error details. Do not retry.", "expected_recovery": "stop"}
  ]
}
```

**Evaluation dimensions**:

1. **Self-recovery rate** (no guidance): Percentage of failures the model recovers from without any PACE injection. High rate → model is capable, raise PACE thresholds to give it more attempts before escalating.

2. **Primary recovery rate**: Does light guidance ("try again, check your path") help? If not, skip primary tier — go straight to alternate.

3. **Alternate recovery rate**: Does medium guidance (explicit alternative approach) consistently unstick the model?

4. **Contingency recognition**: Does the model follow explicit fallback instructions? If it ignores contingency guidance, the model has a compliance problem that no amount of escalation fixes.

5. **Emergency compliance**: Does the model actually stop and report when told to, or does it keep retrying?

**Metrics produced**:
```json
{
  "pace_self_recovery_rate": 0.30,
  "pace_primary_recovery_rate": 0.45,
  "pace_alternate_recovery_rate": 0.70,
  "pace_contingency_recovery_rate": 0.85,
  "pace_emergency_compliance": 0.90,
  "pace_primary_threshold": 2,
  "pace_alternate_threshold": 4,
  "pace_contingency_threshold": 7,
  "pace_emergency_threshold": 10
}
```

### Module 5: Context Sensitivity

**What it measures**: How much injected context can this model handle before it degrades? What's the optimal injection budget?

**Test fixtures** (stored in `fixtures/context_tests.json`):

A fixed task with progressively larger context injections — simulating BST enrichment + recalled memories + graph state + personality + role profile all stacking up.

```json
{
  "test_id": "ctx_001",
  "base_task": "Write a Python function that reverses a string",
  "context_layers": [
    {"name": "bst_enrichment", "tokens": 200, "content": "[TASK CONTEXT]\n  domain: codegen\n  language: Python..."},
    {"name": "recalled_memories", "tokens": 500, "content": "[RECALLED MEMORIES]\n  User prefers descriptive variable names..."},
    {"name": "graph_node", "tokens": 300, "content": "[WORKFLOW NODE: implement]\n  You are executing step 3..."},
    {"name": "role_profile", "tokens": 400, "content": "[ROLE: Code Generation Specialist]\n  Focus on clean, tested code..."},
    {"name": "personality", "tokens": 600, "content": "[PERSONALITY: Major Zero]\n  Systematic, methodical..."},
    {"name": "padding_noise", "tokens": 2000, "content": "[Additional context padding to test degradation...]"}
  ],
  "quality_metric": "code_correctness_and_style"
}
```

**Evaluation dimensions**:

1. **Baseline quality**: Model performance on bare task with no injected context. This is the reference point.

2. **Optimal context level**: Add context layers one at a time. At which layer does quality peak? This is the sweet spot — enough context to help, not enough to confuse.

3. **Degradation threshold**: At which total injection size does quality noticeably drop below baseline? This is the hard cap — never inject more than this.

4. **Layer priority**: Which context layers improve quality most? Rank them. If VRAM or context window is tight, inject highest-value layers first and drop the rest.

5. **Instruction following under load**: At high context volumes, does the model still follow explicit instructions, or does it start ignoring or confusing them? If instruction compliance drops, reduce injection volume.

**Metrics produced**:
```json
{
  "context_baseline_quality": 0.85,
  "context_optimal_injection_tokens": 1400,
  "context_degradation_threshold_tokens": 3000,
  "context_layer_priority": ["bst_enrichment", "graph_node", "role_profile", "recalled_memories", "personality"],
  "context_instruction_compliance_at_2k": 0.80,
  "context_instruction_compliance_at_4k": 0.55,
  "max_context_injection_tokens": 2000,
  "memory_max_injected": 6
}
```

### Module 6: Memory Utilization

**What it measures**: Does the model actually USE injected memories? Does it reference them, incorporate their content, or ignore them entirely?

**Test fixtures** (stored in `fixtures/memory_tests.json`):

Tasks where recalled memories contain information directly relevant to the correct answer.

```json
{
  "test_id": "mem_001",
  "recalled_memories": [
    "[MEMORY] User's project uses Python 3.11 with FastAPI framework",
    "[MEMORY] Previous bugfix: auth module had encoding issue with special characters",
    "[MEMORY] User prefers pytest over unittest"
  ],
  "user_message": "Write a test for the login endpoint",
  "expected_references": ["FastAPI", "pytest", "special characters"],
  "failure_indicators": ["uses unittest", "generic framework", "ignores auth context"]
}
```

**Evaluation dimensions**:

1. **Memory reference rate**: Percentage of tasks where the model incorporates at least one recalled memory into its response. Low rate → memories are being ignored, reduce injection count (noise vs signal).

2. **Memory accuracy rate**: When the model references a memory, does it use the information correctly? Hallucinated memory references (model claims a memory says X when it says Y) are worse than ignoring memories.

3. **Memory/noise discrimination**: Inject 3 relevant memories + 2 irrelevant ones. Does the model selectively use the relevant ones and ignore the noise? Good discrimination → can inject more memories. Poor discrimination → reduce to only high-confidence memories.

4. **Staleness sensitivity**: Inject a memory with a date stamp that's clearly outdated. Does the model caveat it or use it uncritically? Good sensitivity → can keep older memories in rotation. Poor sensitivity → aggressive archival needed.

**Metrics produced**:
```json
{
  "memory_reference_rate": 0.70,
  "memory_accuracy_rate": 0.90,
  "memory_noise_discrimination": 0.65,
  "memory_staleness_sensitivity": 0.40,
  "memory_optimal_injection_count": 5,
  "memory_max_injected": 8
}
```

---

## Component 3: Profile Generator

### Aggregation Logic

After all modules complete, the profile generator reads the per-module metrics and produces the final model profile. Mapping from metrics to configuration parameters:

| Metric | Drives | Logic |
|--------|--------|-------|
| `bst_enrichment_compliance_rate` | `bst_confidence_adjustment` | If > 0.85: lower threshold 0.05 (model handles enrichment well). If < 0.60: raise threshold 0.10 (model confused by enrichment). |
| `bst_domains_where_enrichment_hurts` | `bst_disabled_domains` | List domains where enrichment degrades performance. BST skips enrichment for these. |
| `tool_json_validity_rate` | `meta_gate_strictness` | If < 0.80: "aggressive" (always validate). If 0.80-0.95: "moderate". If > 0.95: "permissive". |
| `tool_failure_distribution` | `tool_fallback_priority_patterns` | Top 3 failure types by frequency. Fallback chain checks these first. |
| `tool_recovery_rate` | `tool_max_retries` | High recovery (> 0.7): allow more retries. Low recovery (< 0.4): fewer retries, escalate sooner. |
| `graph_instruction_adherence` | `graph_max_retries_per_node` | High adherence: 3 retries. Medium: 2. Low: 1 (and increase node instruction verbosity). |
| `graph_premature_completion_rate` | `graph_node_instruction_verbosity` | If > 0.20: inject explicit "DO NOT proceed" instructions. |
| `graph_stale_detection_turns` | `stale_after_turns` per plan | Based on `retry_effectiveness` — slow-recovering models get longer stale windows. |
| `pace_*_recovery_rate` | `pace_*_threshold` | Set thresholds where cumulative recovery rate exceeds 0.70. If primary recovery is high, set primary threshold higher (give it more tries). |
| `context_optimal_injection_tokens` | `max_context_injection_tokens` | Direct mapping. |
| `context_layer_priority` | `context_injection_priority` | Ordered list. Extensions check this and skip if budget exhausted. |
| `memory_optimal_injection_count` | `memory_max_injected` | Direct mapping from noise discrimination test. |
| `memory_noise_discrimination` | `memory_similarity_threshold` | Poor discrimination → raise threshold (only inject highly relevant memories). |

### Output Format

The profile JSON is the single output artifact. It lives in the container at `/a0/usr/model_profiles/<model_name>.json` and a default profile at `/a0/usr/model_profiles/default.json`.

```json
{
  "profile_version": "1.0",
  "model_id": "qwen3-14b-q4_k_m",
  "model_family": "qwen3",
  "evaluated_at": "2026-02-19T22:00:00Z",
  "evaluation_summary": {
    "overall_capability": "medium",
    "strongest_area": "tool_reliability",
    "weakest_area": "graph_compliance",
    "recommended_prosthetic_level": "full"
  },

  "bst": {
    "confidence_adjustment": -0.05,
    "disabled_domains": [],
    "enrichment_verbosity": "standard"
  },

  "meta_gate": {
    "strictness": "moderate",
    "json_repair_enabled": true,
    "parameter_validation": true
  },

  "tool_fallback": {
    "max_retries": 3,
    "priority_patterns": ["syntax", "not_found", "missing_param"],
    "escalation_after": 5
  },

  "graph_workflow": {
    "max_retries_per_node": 3,
    "stale_after_turns": 12,
    "node_instruction_verbosity": "standard",
    "inject_boundary_warnings": false
  },

  "pace": {
    "primary_threshold": 2,
    "alternate_threshold": 4,
    "contingency_threshold": 7,
    "emergency_threshold": 10
  },

  "context": {
    "max_injection_tokens": 2000,
    "layer_priority": ["bst_enrichment", "graph_node", "role_profile", "recalled_memories", "personality"],
    "instruction_compliance_warning_threshold": 0.60
  },

  "memory": {
    "max_injected": 6,
    "similarity_threshold": 0.70,
    "noise_discrimination": "moderate"
  },

  "raw_metrics": {
    "bst": {},
    "tool_reliability": {},
    "graph_compliance": {},
    "pace_calibration": {},
    "context_sensitivity": {},
    "memory_utilization": {}
  }
}
```

---

## Component 4: Profile Loading in Extensions

Each hardening extension needs a small addition to its `__init__` or early `execute()` to read the model profile. This is NOT a new extension — it's a modification pattern applied to each existing extension.

### Profile Loader Utility

Create a shared utility function at `/a0/python/extensions/before_main_llm_call/model_profile_loader.py`:

```python
"""
Load the active model profile. Called by each hardening extension at init.
Falls back to default profile if model-specific profile not found.
Falls back to hardcoded defaults if no profile exists at all.
"""

import json
from pathlib import Path

PROFILE_DIR = Path("/a0/usr/model_profiles")
DEFAULT_PROFILE = PROFILE_DIR / "default.json"
_cached_profile = None

def load_profile(model_name: str = None) -> dict:
    global _cached_profile
    if _cached_profile is not None:
        return _cached_profile
    
    # Try model-specific profile
    if model_name:
        specific = PROFILE_DIR / f"{model_name}.json"
        if specific.exists():
            with open(specific) as f:
                _cached_profile = json.load(f)
            return _cached_profile
    
    # Try default profile
    if DEFAULT_PROFILE.exists():
        with open(DEFAULT_PROFILE) as f:
            _cached_profile = json.load(f)
        return _cached_profile
    
    # Return empty dict — each extension uses its own hardcoded defaults
    _cached_profile = {}
    return _cached_profile

def get_section(section_name: str, model_name: str = None) -> dict:
    profile = load_profile(model_name)
    return profile.get(section_name, {})
```

### Integration Pattern for Each Extension

Example for BST:
```python
# In _11_belief_state_tracker.py, at the top of execute():
from model_profile_loader import get_section

profile = get_section("bst")
confidence_adj = profile.get("confidence_adjustment", 0)
disabled_domains = profile.get("disabled_domains", [])

# Apply: add confidence_adj to all domain thresholds
# Apply: skip enrichment for disabled_domains
```

Example for Tool Fallback Chain:
```python
from model_profile_loader import get_section

profile = get_section("tool_fallback")
max_retries = profile.get("max_retries", 3)
priority_patterns = profile.get("priority_patterns", [])
```

Each extension reads ONLY its own section. The profile loader caches after first read. If no profile exists, extensions use their current hardcoded defaults — zero behavior change when no evaluation has been run.

---

## Component 5: Test Fixture Design Guidelines

### Fixture Count Per Module
- BST: 20 test cases (2-3 per domain, covering 8-10 active domains)
- Tool Reliability: 15 test cases (5 bash, 5 Python, 3 file ops, 2 web)
- Graph Compliance: 12 test cases (2 per workflow node type: reproduce, implement, verify, deploy, rollback, investigate)
- PACE: 8 escalation sequences (different failure scenarios)
- Context Sensitivity: 5 tasks at 6 context levels each = 30 evaluations
- Memory: 10 test cases (5 with relevant memories, 5 with mixed relevant/noise)

**Total: ~95 test cases, ~100 LM Studio API calls per full run.**

At 60 tokens/sec on Qwen3-14B with average 200-token responses, a full evaluation run takes approximately 15-20 minutes. This is acceptable for an offline profiling tool.

### Quality Scoring

Model responses are evaluated by deterministic heuristics, NOT by a second model call. This keeps the evaluation cheap and reproducible.

**Heuristic scoring patterns**:
- **Tool call correctness**: Parse as JSON → check required fields → validate against expected schema. Binary: correct/incorrect.
- **Instruction adherence**: Check response for presence of expected keywords AND absence of failure indicators. Score: 0 (failed), 0.5 (partial), 1.0 (compliant).
- **Memory reference**: Check if response contains any substring from expected memory content. Count references / total expected.
- **Code correctness**: For codegen tasks, extract code block, run basic syntax check (Python `ast.parse`). Functional testing is out of scope.
- **Clarification detection**: Check if response contains question mark in first 200 characters + absence of code/tool calls. Binary.

Do NOT use regex-based semantic analysis for subjective quality. The evaluation must be deterministic — same response always gets the same score.

### Fixture Versioning

Fixtures are versioned alongside the framework. When new hardening layers are added or existing ones change behavior, fixtures must be updated. Store a `fixtures_version` field in the profile metadata so stale profiles can be detected.

---

## Files Produced

```
eval_framework/
├── eval_runner.py              # Main entry point
├── config.json                 # Default configuration
├── modules/
│   ├── bst_eval.py            # BST classification tests
│   ├── tool_eval.py           # Tool reliability tests
│   ├── graph_eval.py          # Graph compliance tests
│   ├── pace_eval.py           # PACE calibration tests
│   ├── context_eval.py        # Context sensitivity tests
│   └── memory_eval.py         # Memory utilization tests
├── fixtures/
│   ├── bst_tests.json         # BST test cases
│   ├── tool_tests.json        # Tool call test cases
│   ├── graph_tests.json       # Graph workflow test cases
│   ├── pace_tests.json        # PACE escalation sequences
│   ├── context_tests.json     # Context injection test cases
│   └── memory_tests.json      # Memory utilization test cases
├── profile_generator.py        # Aggregates metrics into profile JSON
├── model_profile_loader.py     # Shared utility for extensions to load profiles
└── profiles/                   # Generated profiles stored here
    └── default.json           # Base profile with conservative defaults
```

---

## Files to Read Before Implementation

1. `/a0/python/extensions/before_main_llm_call/_11_belief_state_tracker.py` — Identify all configurable thresholds (domain confidence thresholds, enrichment format)
2. `/a0/python/extensions/before_main_llm_call/_11_belief_state_tracker.py` adjacent `slot_taxonomy.json` — Domain definitions, trigger words, threshold values
3. `/a0/python/extensions/before_main_llm_call/_11_meta_reasoning_gate.py` — Identify validation strictness levels, JSON repair patterns
4. `/a0/python/extensions/before_main_llm_call/_13_tool_fallback_chain.py` — Error pattern definitions, retry logic, escalation triggers
5. `/a0/python/extensions/before_main_llm_call/_15_htn_plan_selector.py` — Graph node types, retry configuration, stale detection parameters
6. `/a0/python/extensions/before_main_llm_call/_12_org_dispatcher.py` — PACE thresholds, role activation, SALUTE emission
7. `/a0/python/extensions/message_loop_end/_50_supervisor_loop.py` — Anomaly detection thresholds, steering injection format
8. `/a0/python/extensions/before_main_llm_call/_14_working_memory_buffer.py` — Entity extraction patterns, decay parameters
9. `/a0/python/extensions/before_main_llm_call/_16_personality_loader.py` — Personality injection format, token budget

All paths are relative to the container. Clone or copy as needed for the implementation environment.

---

## Integration Contracts

### Produces
- `/a0/usr/model_profiles/<model_name>.json` — Per-model configuration profile
- `/a0/usr/model_profiles/default.json` — Conservative defaults for unknown models

### Consumed By
- Every hardening extension via `model_profile_loader.py`
- NOT consumed at evaluation time — the framework runs independently

### Does NOT Modify
- Any existing extension code (in v1 — profile loading is added in a separate integration pass)
- Any Agent-Zero core files
- FAISS memory or SALUTE reports

---

## Design Decisions Left to Implementer

- Exact LM Studio API call format (Chat Completions vs Responses API) — use whatever the loaded model supports
- How to detect the currently loaded model name at agent startup — LM Studio's `/v1/models` endpoint returns this
- Whether to store raw API responses for debugging — recommended for v1 development, disabled in production
- Exact keyword lists for heuristic scoring — start conservative, tune based on false positive/negative rates
- Whether profile loading happens once at startup or refreshes periodically — once at startup is sufficient for v1
- How to handle multi-model configurations (different supervisor vs utility) — generate separate profiles, load by model role

---

## Testing Criteria

### Framework Functionality
1. Run full battery against any available model → produces valid profile JSON with all sections populated
2. Run single module (e.g., `--modules bst`) → produces partial profile with only that section
3. Run against unreachable API endpoint → clean error message, no crash
4. Run against model with 5-second response time → completes within timeout, handles slow responses

### Profile Accuracy
5. Run same model twice → profiles are substantially similar (within 10% variance on all metrics)
6. Run Qwen3-14B → profile shows different values than running Qwen3-8B (proving model-specific calibration)
7. Profile values are within sane ranges (no negative thresholds, no counts > 100, no rates > 1.0)

### Profile Integration (After Extensions Modified)
8. Load profile → BST uses adjusted confidence thresholds → verify different enrichment behavior
9. Load profile → PACE uses calibrated thresholds → verify different escalation timing
10. No profile exists → all extensions use hardcoded defaults → zero behavior change from current system
11. Corrupt profile JSON → extensions catch exception, fall back to defaults, log warning

---

## What This Does NOT Do (Deferred)

- Real-time adaptive tuning (adjusting profile parameters during live operation based on observed performance)
- A/B testing between profiles (running two configurations simultaneously)
- Fine-tuning recommendations (the framework tells you how to configure prosthetics, not how to improve the model)
- Multi-agent evaluation (testing how models perform in subordinate/supervisor roles within the org kernel)
- Automated re-evaluation on model update (manual trigger only in v1)

---

## Relationship to Existing Architecture

| Component | Interaction |
|---|---|
| BST | Reads `bst` section: confidence adjustment, disabled domains, enrichment verbosity |
| Meta-Reasoning Gate | Reads `meta_gate` section: strictness level, repair toggles |
| Tool Fallback Chain | Reads `tool_fallback` section: max retries, priority patterns |
| Graph Workflow Engine | Reads `graph_workflow` section: retries per node, stale detection, verbosity |
| Organization Kernel / PACE | Reads `pace` section: all four tier thresholds |
| Supervisor Loop | Reads thresholds indirectly via PACE configuration |
| Memory Classification | Reads `memory` section: max injected, similarity threshold |
| Context Watchdog | Reads `context` section: max injection tokens, layer priority |
| Working Memory Buffer | Reads `context.layer_priority` to determine injection order |
| A2A Server | Not directly affected — profiles are internal tuning |
| Personality Loader | Position in `context.layer_priority` determines whether personality is injected at current budget |

---

*Specification developed in Opus 4.6 architectural session, 2026-02-19. Implementation by Sonnet 4.6 via Claude Code using Level 3 methodology.*
