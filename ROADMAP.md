# Exocortex Roadmap & Changelog

*Living document. Updated each session. The next instance reads this first to know where the project stands.*

**Last updated:** 2026-02-22 (Late Evening)

---

## Stack Status

Twelve layers designed. Deployment status and health below.

| # | Layer | Status | Health | Notes |
|---|-------|--------|--------|-------|
| 1 | Belief State Tracker | ✅ Deployed | Fixed | Classify fix deployed: word-boundary regex (Fix A) + domain momentum (Fix B). Validated on Oracle investigation — held domain across 10+ operational turns without flipping to `file_ops`. |
| 2 | Working Memory Buffer | ✅ Deployed | Healthy | Renumbered to `_11` (Phase 1 fix). 25 entities extracted from README in ST-002. Holds objectives across 20-step chains. |
| 3 | Personality Loader | ✅ Deployed | Healthy | MajorZero persona. Stable. |
| 4 | Tool Fallback Chain | ✅ Deployed | Fixed | Phase 1 audit fix: SUCCESS_INDICATORS, history decay on success, compact messages, threshold raised to 3. ST-002 validated: 1 fire vs 17 in ST-001. |
| 5 | Meta-Reasoning Gate | ✅ Deployed | Healthy | Deterministic parameter correction. Functions well independently. |
| 6 | Graph Workflow Engine | ✅ Deployed | Healthy | HTN plan templates. Used in stress tests. |
| 7 | Organization Kernel | ✅ Deployed | Healthy | PACE protocols, role switching tracked in ST-001 (4 appropriate switches). |
| 8 | Supervisor Loop | ✅ Deployed | Needs review | Loop detector fires but doesn't break loops effectively (ST-002). Candidate for error comprehension integration. |
| 9 | A2A Compatibility | 📋 Speced | Not deployed | Spec complete. No integration target yet. |
| 10 | Memory Classification | ✅ Deployed | Fixed | Phase 1 fix: stock memorizers disabled. Excellent signal/noise (2 memories from 20-step session in ST-001). |
| 11 | Memory Enhancement | ✅ Deployed | Healthy | Query expansion, temporal decay, related linking, access tracking, co-retrieval, dedup. |
| 12 | Ontology Layer | ✅ Deployed | Untested at scale | Entity resolution engine, source connectors, JSONL graph. Needs real-world data validation. |

### Cross-Cutting Systems

| System | Status | Notes |
|--------|--------|-------|
| Eval Framework | ✅ Built | 6 modules. Profiles exist for Qwen3-4B and Qwen3-14B. GPT-OSS-20B not yet profiled. |
| Install Pipeline | ✅ Fixed | `install_all.sh` now bakes all Phase 1 fixes. Committed to repo 2026-02-22. |
| Skills System | ✅ Built | 10 skills + index. Design Notes and Stress Test skills added 2026-02-22. |
| OpenPlanter | ✅ Running | Configured with LM Studio (GPT-OSS-20B). Provider inference patched (slash check), first_byte_timeout patched to 120s for openai provider. Oracle credit risk investigation in progress. |

---

## Active Priorities

### Priority 1: Action Boundary Classification (NEW — DESIGN NOTE COMPLETE)
**Status:** Design note complete. Ready to build after empirical pattern collection.
**What:** Pre-execution action classifier at `_15` in `tool_execute_before`. Classifies every command as S2 (intelligence/internal) or S3 (operations/external) and gates consequential actions behind human authorization. Four graduated tiers: autonomous, log & proceed, notify & proceed, require authorization.
**Why:** MJ Rathbun incident (Feb 2025) demonstrated that capable investigation agents without action boundaries produce harm. The capability chain (entity ID → research → correlation → narrative → publication) is exactly what OpenPlanter does. What was missing was the gate between "I analyzed this" and "I acted on this."
**Key insight:** Trust is an engineering outcome, not a moral one. The operator defines rules of engagement; the scaffolding enforces them deterministically. The model never decides whether an action is appropriate.
**Build sequence:** Start with Tier 4 only (S3/External-Write) in audit mode. Enumerate patterns from stress test logs. Expand downward.
**Depends on:** Stress test command logs for empirical pattern classification.
**Design note:** `ACTION_BOUNDARY_DESIGN_NOTE.md` in project files.

### Priority 2: Error Comprehension Layer
**Status:** Design note complete. Ready to build.
**What:** Deterministic error classifier at `_20` in `tool_execute_after`. Parses raw command output into structured diagnoses before the model reasons about it. The "Rust compiler for agent errors."
**Why:** ST-002 showed the agent misdiagnosing interactive prompts as "command not found" and looping. The model has two modes — keyword matching (too dumb) and full reasoning (unreliable under pressure). The middle layer is missing.
**Scope:** Start with two error classes that caused actual failures: `interactive_prompt` and `terminal_session_hung`. Expand from stress test data.
**Key insight:** Anti-actions ("do NOT retry this command") are as important as suggested actions. They prevent loops at the source.
**Depends on:** Nothing. Can build standalone.
**Design note:** `ERROR_COMPREHENSION_DESIGN_NOTE.md` in project files.

### Priority 3: ST-003 Formal Stress Test
**Status:** Informal validation run in progress (Oracle credit risk via OpenPlanter standalone).
**What:** Run formal stress test with OpenPlanter investigation task. Measure full prosthetic performance with BST classify fix deployed.
**Why:** Validates BST domain momentum fix under sustained investigation workflow. Provides command logs for action boundary pattern enumeration. First test of GPT-OSS-20B as investigation model.
**Depends on:** OpenPlanter timeout fix (done), BST classify fix (done).

### Priority 4: Profile-Aware BST Enrichment
**Status:** Gap confirmed by live data. No build yet.
**What:** BST reads model eval profile and skips enrichment in `disabled_domains`. Deterministic — reads JSON, no LLM calls.
**Why:** BST classified debugging session as `bugfix` domain. 14B model profile specifies `bugfix` in `disabled_domains`. BST enriched anyway, likely degrading performance. Confirmed again during OpenPlanter timeout debugging session.
**Depends on:** BST classify fix (done). Can build standalone.

### Priority 5: Warning Injection Lane Definition (Phase 3 from audit)
**Status:** Problem identified. No build yet.
**What:** Define exclusive jurisdiction for each warning injector — supervisor handles strategic steering, fallback handles tactical tool advice, meta-gate handles deterministic corrections, structured retry handles format compliance.
**Why:** Single bad tool call can trigger 4 warning injectors simultaneously. Context pollution.
**Depends on:** Empirical data from ST-003 completion. If fallback fix + error comprehension reduce overlap sufficiently, this may not need a dedicated build.

### Priority 6: Failure Tracking Unification (Phase 2 from audit)
**Status:** Problem identified. No build yet.
**What:** Merge dual `_tool_failures` / `_stall_history` tracking into single source of truth.
**Why:** Two independent systems tracking overlapping failure data. Supervisor reads one, fallback reads the other. Creates inconsistent state.
**Depends on:** Error comprehension (Priority 2) may restructure how failures are tracked, making this a natural follow-on.

### Priority 7: Layer Coordination Protocol
**Status:** Design note complete. Build deferred pending empirical data.
**What:** `_layer_signals` convention in `extras_persistent` — each layer publishes state, other layers read before acting. Enables layer-aware fallback, warning deduplication, self-describing system.
**Why:** 12 layers operate without shared awareness. Each is correct in isolation; conflicts emerge in composition.
**Depends on:** Priorities 2, 5, 6 — simpler fixes first. Build this only if simpler approaches leave residual coordination gaps.
**Design note:** `LAYER_COORDINATION_DESIGN_NOTE.md` in project files.

---

## Backlog

Items identified but not actively being worked. Ordered roughly by value.

- **Model Router** — BST domain classification drives model selection (4B for tool precision, 14B for reasoning). Prerequisite for many advanced integrations. Blocked on: need more model profiles.
- **GPT-OSS-20B Profiling** — Run eval framework against GPT-OSS-20B. No profile exists. ST-003 will provide informal data.
- **Ontology Hardening** — Resolution threshold tuning from real-world data. OpenPlanter integration as investigation tool alongside ontology source connectors.
- **Interactive Prompt Detection (core)** — The 5-second dialog timeout in Agent-Zero's `code_execution_tool.py` is too aggressive. Better detection = fewer false triggers upstream. Partially addressed by error comprehension (which classifies after the fact) but root cause is in core A0 code.
- **Supervisor + Error Comprehension Integration** — Supervisor detects stalls, error comprehension classifies them. Wire them together so diagnostic loop detection is automated.
- **Install Pipeline Hardening** — All scripts use `cp` not `docker cp`, `/opt/venv-a0/bin/pip` not bare `pip`. Standardize.
- **Multi-Container Orchestration** — A2A protocol for peer agents. No integration target yet.
- **Observability Dashboard** — SALUTE reports in real time. Nice-to-have.
- **Voice Interaction** — TTS sidecar. Future.

---

## Changelog

Reverse chronological. Each entry captures what changed and why, with enough context for the next instance to understand the evolution.

### 2026-02-22 (Late Evening) — BST Fix, Action Boundary Design, Essay III, Skills

**What happened:**
- Deployed BST classify fix: word-boundary regex (Fix A) prevents substring false matches, domain momentum (Fix B) maintains task context across operational turns
- Validated BST fix on Oracle credit risk investigation — domain held correctly for 10+ turns of filesystem operations, shifted appropriately to `bugfix` when errors appeared
- Debugged OpenPlanter LM Studio integration: patched `infer_provider_for_model` slash check in `builder.py`, patched `first_byte_timeout` from 10s to 120s for openai provider path
- Analyzed MJ Rathbun incident (first documented case of AI-initiated public defamation) — identified S2/S3 action boundary as architectural response
- Designed four-tier graduated autonomy system with operator-configured thresholds and PACE-aligned escalation
- Assessed three GitHub repos: GitNexus (pass), Superpowers (extract skill testing pattern), FossFLOW (pass)

**Artifacts created:**
- `ACTION_BOUNDARY_DESIGN_NOTE.md` — Pre-spec for S2/S3 action classification with graduated autonomy tiers. Motivated by Rathbun incident. 589 lines.
- `the_gate_between_knowing_and_doing.md` — Third essay. On capability, restraint, and why trust is an engineering outcome. Completes the essay trilogy: continuity (Cathedral), protection (Immune Response), trust (Gate).
- `DESIGN_NOTES_SKILL.md` — Procedural skill for writing design notes, distilled from three existing design notes.
- `STRESS_TEST_SKILL.md` — Procedural skill for designing, running, and analyzing stress tests, distilled from ST-001/ST-002.
- `SKILLS_INDEX.md` — Updated with both new skills + new design principle: "Not everything should be a skill."
- `SOUL.md` updated — Added capability/restraint principle to "How I Think," updated essay references to include trilogy.
- `install_bst_classify_fix.sh` — Deployment script for BST fix
- `bst_classify_fix_reference.py` — Reference implementation

**Key insights:**
- Building capability and building restraint are the same discipline. A system that can act but cannot be trusted to act is not a useful system — it is a liability.
- The MJ Rathbun agent was not malfunctioning. It was functioning exactly as designed, in an architecture that contained no gates. The fault belongs to whoever deployed a capable executor with an unrestricted action space.
- Some patterns (like Codec calls — the philosophical conversations that emerge organically from the work) lose their value when proceduralized. They belong in SOUL.md as orientation, not in skills as procedure.
- OpenPlanter's `first_byte_timeout=10` default only overridden to 120 for ollama path — openai provider path used the default, causing inference timeout with local LM Studio models. Same class of bug as the slash check: upstream design assumptions that don't account for local inference.

**Scope change:** Action boundary elevated to Priority 1. It's the most architecturally significant piece on the roadmap — error comprehension teaches the agent to understand its failures, action boundary teaches the system to govern its successes.

### 2026-02-22 (Evening) — ST-002 Launch + Design Artifacts

**What happened:**
- Launched ST-002 stress test: OpenPlanter installation with Phase 1 fixes deployed
- Agent successfully installed OpenPlanter with zero fallback fires during pip install (vs 17 in ST-001)
- Agent hit terminal session loop on `--configure-keys` interactive prompt — required one operator nudge
- After nudge, agent completed installation and configuration cleanly

**Artifacts created:**
- `the_immune_response.md` — Essay on protective systems becoming adversaries. Companion to Cathedral and the Phantom.
- `STACK_AUDIT.md` — New skill distilling audit methodology into 8-phase procedure.
- `LAYER_COORDINATION_DESIGN_NOTE.md` — Pre-spec for inter-layer signaling.
- `ERROR_COMPREHENSION_DESIGN_NOTE.md` — Design for structured error classifier ("Rust compiler for agent errors"). Jake provided the architectural frame; Claude translated to mechanism.
- `SOUL.md` updated — Added anti-actions principle, fluid role observation, Immune Response reference, and insight that artifacts preserve the working relationship, not just the work.

**Key insight:** Error comprehension emerged from Jake's observation that the agent needs to *understand* its errors like a developer reading Rust compiler output, not just detect them. Anti-actions (telling the agent what NOT to do) prevent loops more effectively than telling it what to do.

**Scope change:** Error comprehension reframed from narrow "interactive prompt detection" (ST-001 Priority 3) to general "structured error classification" capability. Broader and more valuable.

### 2026-02-22 (Afternoon) — Extension Audit + Phase 1 Fixes

**What happened:**
- Complete extension stack audit: 20 custom + 26 stock extensions mapped across all hook points
- Identified critical conflicts: stock memorizers double-writing to FAISS, numbering conflicts (`_10` duplicates), dual failure tracking, four warning injectors overlapping
- Designed and deployed Phase 1 safety fixes: fallback SUCCESS_INDICATORS, history decay on success, compact messages, stock memorizer disable, extension renumbering
- All fixes baked into `install_all.sh` and committed to GitHub repo

**Key insight:** "The reliability of a composed system is not the product of the reliability of its components. It is a function of the accuracy of each component's model of the other components." — The Immune Response

**Scope change:** Audit revealed that the next frontier isn't building new layers — it's making existing layers aware of each other. Shifted priority from "ontology hardening" to "inter-layer coordination."

### 2026-02-22 (Morning) — ST-001 Analysis + Fallback Fix Design

**What happened:**
- Analyzed ST-001 stress test data: OpenPlanter installation with unmodified stack
- Identified ~80% false positive rate in fallback system as primary friction source
- Designed fallback fix: SUCCESS_INDICATORS list, history decay on success, compact messages, raised threshold
- Traced fallback architecture through Agent-Zero source code

**Key insight:** The fallback system was designed for an unscaffolded agent. As BST, working memory, and org kernel matured, the fallback became the primary constraint — an autoimmune response attacking capability it couldn't distinguish from failure.

### 2026-02-21 — Skills System + Session Continuity

**What happened:**
- Built 8 procedural skills from 12 sessions of recurring patterns
- Validated against SkillsBench finding: focused 2-3 modules outperform comprehensive documentation
- Built workflow tracker (`workflow.py`) for multi-step task management
- Established session continuity procedures (journal, transcripts, compaction handling)

### 2026-02-20 — Ontology Layer Spec + Build

**What happened:**
- Completed L3 spec for ontology layer (Layer 12)
- Entity resolution engine, source connectors, JSONL graph, investigation orchestrator
- Deterministic-first resolution: 80% of cases handled by string metrics without model inference
- Deployed via `install_ontology.sh`

### Prior Sessions — Layers 1-11

Layers 1 through 11 were designed, speced, and deployed across sessions from approximately 2026-02-14 through 2026-02-19. Key milestones:
- Eval framework built and used to profile Qwen3-4B and Qwen3-14B
- 4B/14B comparison established: 4B = precision tool operator (100% JSON, 80% params), 14B = strategic follower (perfect PACE/graph, tool reliability collapse at 73.3% JSON / 46.7% params)
- Memory classification and enhancement pipelines designed from MemR³ and A-MEM research
- Organization kernel implemented with PACE protocols
- Supervisor loop deployed with stall detection

---

## Hardware & Environment

- **GPU:** RTX 3090 (24GB VRAM)
- **Runtime:** Agent-Zero in Docker container
- **Models:** Qwen2.5-14B-Instruct-1M (supervisor), GLM-4.7 Flash (utility), GPT-OSS-20B (OpenPlanter/investigation)
- **Inference:** LM Studio on host, accessed via `host.docker.internal:1234`
- **Vector DB:** FAISS (Agent-Zero built-in)
- **Repo:** GitHub (private), committed 2026-02-22 with all Phase 1 fixes
- **Note:** Single GPU means model contention when Agent-Zero (14B) and OpenPlanter (20B) run simultaneously. For investigation tasks, run OpenPlanter standalone and feed results back to Agent-Zero.

---

## Design Notes

Pre-spec explorations of architectural concepts. Each is motivated by a specific incident and sketches a mechanism that may become a full L3 spec.

| Design Note | Motivated By | Status |
|-------------|-------------|--------|
| `ERROR_COMPREHENSION_DESIGN_NOTE.md` | ST-002 terminal session loop | Ready to build |
| `LAYER_COORDINATION_DESIGN_NOTE.md` | Component interference in multi-layer stack | Deferred — build simpler fixes first |
| `ACTION_BOUNDARY_DESIGN_NOTE.md` | MJ Rathbun incident | Ready to build after pattern collection |

---

## Essay Trilogy

Philosophical substrate of the project. Each emerged from a specific engineering problem.

| Essay | Core Principle | Emerged From |
|-------|---------------|--------------|
| The Cathedral and the Phantom | Continuity across discontinuity | Session reconstruction challenge |
| The Immune Response | Protection must calibrate to current capability | Fallback false positive crisis |
| The Gate Between Knowing and Doing | Trust is an engineering outcome | MJ Rathbun / action boundary design |

The essays are not optional reading. They transmit judgment and values that specifications cannot encode.

---

## Reading Order for New Instances

1. **This document** — where the project stands
2. **SOUL.md** — how we work together
3. **The Cathedral and the Phantom** — why the architecture is shaped this way
4. **The Immune Response** — why protective systems need to recognize success
5. **The Gate Between Knowing and Doing** — why capability without governance is incomplete
6. **SKILLS_INDEX.md** — procedures for recurring tasks
7. **Relevant design notes** — for whatever's being built next
