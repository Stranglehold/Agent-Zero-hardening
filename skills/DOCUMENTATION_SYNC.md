# Skill: Documentation Sync

## Trigger
After any spec is created or updated, after new research is integrated, or when the user asks to update docs. Also triggered when a new layer is added to the stack or a component changes scope.

## Inputs Required
- **The change that was made** — new spec, updated spec, new research citation, new component
- **Current README** — at `/mnt/user-data/outputs/README.md`
- **Current specs** — check which specs exist and their current scope

## Procedure

### 1. Identify What Changed
Map the change to README sections that need updating:
- New layer or component → update "The Stack" section
- New spec → update "Specifications" list
- New research citation → update "Acknowledgments"
- Scope change → update layer description, roadmap, project structure
- New file or directory → update "Project Structure"

### 2. Update Layer Descriptions
When a component's scope changes (e.g., memory enhancement going from 4 components to 6):
- Rewrite the layer description to reflect the full current scope
- Include the mechanism briefly — what it does and how, not just that it exists
- If informed by specific research, name it: "(informed by MemR3's finding that...)"

### 3. Update Spec List
The spec list format is: `- {FILENAME} — {short description of scope}`
Scope descriptions should match the current spec version, not the original version.

### 4. Update Acknowledgments
When new research directly informs a build (not just "further reading"):
- Add to acknowledgments with author, year, and one-sentence description of what we took from it
- Position after existing entries in logical order (foundational sources first, validation sources last)

### 5. Update Roadmap
If the change moves something from "roadmap" to "built":
- Remove from future items
- Add to current items if still in progress, or remove entirely if complete

### 6. Update Project Structure
If new directories or file categories are added:
- Update the ASCII tree
- Include brief comments explaining what lives in each directory

## Quality Checks
- [ ] Layer descriptions in README match current spec scope (not outdated)
- [ ] Spec list includes all specs with current scope descriptions
- [ ] Acknowledgments include all research that directly informed builds
- [ ] Roadmap reflects current state (nothing listed as "future" that's already built)
- [ ] Project structure matches actual directory layout

## Anti-Patterns
- **Updating the README without checking the spec.** The spec is ground truth. The README summarizes the spec. Never update the README description independently of the spec.
- **Leaving stale scope descriptions.** If the memory enhancement spec went from "temporal decay, access tracking, deduplication" to also include "query expansion, related memory links," every reference must update.
- **Over-documenting in the README.** The README is a summary. Layer descriptions should be 3-5 sentences. Details live in the spec.
- **Forgetting the project structure.** It's the first thing a new reader sees. If it's wrong, they'll be confused before they start.
