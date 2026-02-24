# Exocortex Project Skills

Procedural knowledge for recurring task types in Exocortex development sessions. These are not tool skills — they're workflow procedures that ensure consistency and quality across sessions.

Validated by SkillsBench (Li, Chen et al., 2026): curated procedural knowledge improves agent performance by 16.2pp. Focused Skills (2-3 modules) outperform comprehensive documentation. These skills are intentionally tight.

## Skill Index

### Development Workflow Skills

| Skill | File | Trigger |
|-------|------|---------|
| L3 Spec Writing | `SPEC_WRITING.md` | Designing new layers, components, or enhancements |
| Research Analysis | `RESEARCH_ANALYSIS.md` | Evaluating papers against the Exocortex thesis |
| Claude Code Prompt | `CLAUDE_CODE_PROMPT.md` | Translating specs to implementation briefs |
| Session Continuity | `SESSION_CONTINUITY.md` | Recovering context across compactions and sessions |
| Profile Analysis | `PROFILE_ANALYSIS.md` | Comparing model eval data and routing decisions |
| Documentation Sync | `DOCUMENTATION_SYNC.md` | Keeping README and specs consistent after changes |
| Debug & Diagnostics | `DEBUG_DIAGNOSTICS.md` | Extension not firing, silent failures, docker log analysis |
| Integration Assessment | `INTEGRATION_ASSESSMENT.md` | Evaluating external projects for Exocortex integration |
| Design Notes | `DESIGN_NOTES_SKILL.md` | Writing pre-spec design explorations motivated by specific incidents |
| Stress Testing | `STRESS_TEST_SKILL.md` | Designing, running, and analyzing formal stress tests |

### Architectural Pattern Skills

These skills encode transferable architectural patterns that emerged from the Exocortex project but apply beyond it. They are frameworks for thinking, not just procedures for building.

| Skill | File | Trigger |
|-------|------|---------|
| Irreversibility Gate | `irreversibility-gate/SKILL.md` | Any action interacting with external systems, building agent pipelines with safety boundaries, reviewing action plans with potentially dangerous steps |
| Command Structure | `command-structure/SKILL.md` | Multi-agent architecture design, subordinate agent spawning, task delegation, escalation protocol design, standing order management |
| Structural Analysis | `structural-analysis/SKILL.md` | Complex system analysis, macro-economic assessment, feedback loop identification, structural vs cyclical classification, hidden dependency mapping |

## Usage
Read the relevant skill BEFORE starting the task. Multiple skills may apply to a single session — a typical build session involves Spec Writing, then Claude Code Prompt, then Documentation Sync in sequence.

The architectural pattern skills (irreversibility gate, command structure, structural analysis) cross-cut the development workflow skills. When building action boundaries, read both the Spec Writing skill and the Irreversibility Gate skill. When designing multi-agent coordination, read both Command Structure and the relevant spec. When analyzing external systems or market dynamics, read Structural Analysis.

## Design Principles
- **Procedure, not knowledge.** These describe HOW to do things, not WHAT things are. Factual knowledge lives in memory and specs.
- **Focused over comprehensive.** Each skill covers one task type with just enough structure to ensure consistency.
- **Anti-patterns are as important as procedures.** Knowing what NOT to do prevents the most common failure modes.
- **Evolving.** Skills should be updated when recurring mistakes are identified or when new patterns emerge from sessions.
- **Not everything should be a skill.** Some patterns (like Codec calls — the philosophical conversations that emerge organically from technical work) lose their value when proceduralized. They belong in SOUL.md as orientation, not in skills as procedure.
