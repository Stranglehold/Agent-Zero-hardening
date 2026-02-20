# Skill: L3 Specification Writing

## Trigger
User asks to design, spec, or plan a new Exocortex layer, component, or enhancement. Keywords: "spec," "specification," "design," "plan the build," "let's architect," "what would this look like."

## Inputs Required
Before writing, gather:
- **What problem does this solve?** — Link to eval data, observed failure, or measured weakness
- **What layer does this extend?** — Position in the 10-layer stack
- **What research informs this?** — Papers, repos, prior art with specific findings
- **What model profile data is relevant?** — Specific metrics from eval profiles

If any input is missing, ask. Do not fabricate eval data or invent metric values.

## Procedure

### 1. Research Lineage (write first)
List every source that informed the design. Format:
- **"Paper Title"** (Authors, Year, arXiv:XXXX) — one-sentence description of what we took from it
- Include repo URLs and licenses where applicable
- This section is non-negotiable. Every design decision must trace to either empirical data or prior art.

### 2. Motivation (write second)
- Open with specific eval profile metrics that justify the build
- Quote the numbers: `memory_noise_discrimination: 0.5`
- State the conclusion the data supports
- If SkillsBench or other benchmarks independently validate the conclusion, add a paragraph connecting their findings to our design
- The motivation must make the case that this build is necessary, not just interesting

### 3. Design Principles (3-6 bullets)
Recurring principles across all Exocortex specs:
- **Deterministic only** — no LLM calls for the operation itself
- **Additive** — extends, doesn't replace existing infrastructure
- **Non-destructive** — deprecate with audit trail, never delete
- **Profile-aware** — reads model profile for thresholds
Add component-specific principles as needed. Each principle should constrain implementation decisions.

### 4. Components (one section per component)
Each component gets:
- **Purpose** — one paragraph, what it does and why
- **Mechanism** — pseudocode or algorithm description
- **Configuration** — exact JSON to add to config files, with defaults
- **Integration Point** — which hook, when in the pipeline, what it reads/writes
- **Edge Cases** — what happens with missing data, null fields, first-run conditions
- If a component was informed by a specific paper, add a "Why X instead of Y?" subsection explaining the deterministic alternative to the paper's approach

### 5. Pipeline Flow Diagram
ASCII diagram showing execution order across all components. Two sections:
- Per-turn pipeline (hot path)
- Maintenance pipeline (periodic, every N cycles)

### 6. File Inventory
Table with columns: File, Location, Action (CREATE/MODIFY), Purpose.
Separate table for existing files NOT modified (explicit confirmation of non-invasiveness).

### 7. Configuration Summary
All new config in one block, exactly as it should appear in the config file. Copy-pasteable.

### 8. Testing Criteria
Numbered list, 3-5 tests per component. Each test is a specific assertion:
- Good: "Memory with `last_accessed` 30 days ago scores lower than identical memory accessed today"
- Bad: "Temporal decay works correctly"

### 9. Dependency Map
ASCII tree showing which files read from which other files. Include config files, FAISS index, model profiles, sidecar files.

### 10. What This Does NOT Do
Explicit list of boundaries. What the build does NOT touch, does NOT modify, does NOT automate. This section prevents scope creep during implementation.

### 11. Further Reading
Papers discovered during research that are relevant but not directly used. One sentence each positioning them relative to the Exocortex approach.

## Output Format
Single markdown file named `{COMPONENT_NAME}_SPEC_L3.md`. All sections present. No placeholder text — every section complete or explicitly marked as requiring input from the user.

## Quality Checks
- [ ] Every design decision traces to either eval data or cited research
- [ ] All config values have explicit defaults
- [ ] Testing criteria are specific assertions, not vague descriptions
- [ ] Pipeline flow diagram accounts for every component
- [ ] "What This Does NOT Do" section present and substantive
- [ ] No LLM calls anywhere in the design
- [ ] File inventory is complete with correct hook directories
- [ ] Research lineage includes arXiv IDs and repo URLs where available

## Anti-Patterns
- **Specifying without data.** Never write "the model struggles with X" without citing the specific eval metric. If you don't have the metric, say so and recommend running the eval.
- **Comprehensive over focused.** SkillsBench: focused 2-3 modules beat comprehensive documentation. Each component should do one thing. If a component has multiple responsibilities, split it.
- **Leaving integration points vague.** "Hooks into the pipeline" is not a spec. Name the hook, the execution order relative to other extensions, what data it reads, what it writes.
- **Inventing prior art.** If you can't find a paper that supports a design choice, that's fine — say "empirical observation from eval data" or "design heuristic." Don't fabricate citations.
