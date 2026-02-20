# Exocortex Project Skills

Procedural knowledge for recurring task types in Exocortex development sessions. These are not tool skills — they're workflow procedures that ensure consistency and quality across sessions.

Validated by SkillsBench (Li, Chen et al., 2026): curated procedural knowledge improves agent performance by 16.2pp. Focused Skills (2-3 modules) outperform comprehensive documentation. These skills are intentionally tight.

## Skill Index

| Skill | File | Trigger |
|-------|------|---------|
| L3 Spec Writing | `SPEC_WRITING.md` | Designing new layers, components, or enhancements |
| Research Analysis | `RESEARCH_ANALYSIS.md` | Evaluating papers against the Exocortex thesis |
| Claude Code Prompt | `CLAUDE_CODE_PROMPT.md` | Translating specs to implementation briefs |
| Session Continuity | `SESSION_CONTINUITY.md` | Recovering context across compactions and sessions |
| Profile Analysis | `PROFILE_ANALYSIS.md` | Comparing model eval data and routing decisions |
| Documentation Sync | `DOCUMENTATION_SYNC.md` | Keeping README and specs consistent after changes |

## Usage
Read the relevant skill BEFORE starting the task. Multiple skills may apply to a single session — a typical build session involves Spec Writing, then Claude Code Prompt, then Documentation Sync in sequence.

## Design Principles
- **Procedure, not knowledge.** These describe HOW to do things, not WHAT things are. Factual knowledge lives in memory and specs.
- **Focused over comprehensive.** Each skill covers one task type with just enough structure to ensure consistency.
- **Anti-patterns are as important as procedures.** Knowing what NOT to do prevents the most common failure modes.
- **Evolving.** Skills should be updated when recurring mistakes are identified or when new patterns emerge from sessions.
