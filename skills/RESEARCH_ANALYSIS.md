# Skill: Research Analysis Against Thesis

## Trigger
User shares a paper, asks about academic research, or says "is there anything useful in X?" Keywords: "paper," "arXiv," "research," "what can we use from," "any insight from."

## Inputs Required
- **The paper or source** — arXiv link, PDF, or user description
- **Current Exocortex state** — which layers exist, what eval data is available
- If the paper isn't provided directly, search for it. If it's behind a paywall, work from the abstract and any available summaries.

## Procedure

### 1. Extract Core Findings
Read the paper with one question: **what specific model weakness does this identify?**

Do not summarize the paper comprehensively. Extract only:
- The problem they measured
- The metric or benchmark they used
- The magnitude of improvement their approach achieved
- The mechanism that produced the improvement

### 2. Map to Exocortex Weaknesses
For each core finding, ask: **does this map to a weakness we've already measured in our eval profiles?**

Check against known weaknesses:
- `memory_noise_discrimination: 0.5` (both 4B and 14B)
- `memory_reference_rate: 1.0` (model uses everything it's given)
- BST enrichment hurts 14B in technical domains
- 14B tool reliability collapse (73.3% JSON, 46.7% params)
- 4B tool reliability perfect but limited reasoning
- Context sensitivity degradation at 4k tokens

If the finding maps to a measured weakness, it's high priority. If it maps to a theoretical weakness we haven't measured, note it but rank lower.

### 3. Evaluate the Mechanism
For each finding that maps to a weakness, ask: **can we build a deterministic prosthetic for this?**

Decision framework:
- **Their approach uses model-in-the-loop** → Can we achieve similar effect with heuristics, rules, or preprocessing? If yes, design the deterministic version. If no, note the limitation.
- **Their approach is deterministic already** → Can we adopt it directly? Check license, dependencies, integration complexity.
- **Their approach requires training** → This is the RL/fine-tuning path Exocortex deliberately avoids. Note it as "represents approach we deliberately avoid" and extract any insights that can inform deterministic alternatives.
- **Their approach requires infrastructure we don't have** → Note as future direction with specific prerequisites.

### 4. Design the Concrete Prosthetic
For each viable mechanism, write:
- **What it does** — one sentence
- **Where it lives** — which extension, which hook, which pipeline position
- **What it costs** — latency, compute, complexity
- **What it replaces or enhances** — which existing component benefits
- **Configuration** — what knobs it needs

### 5. Position Relative to Existing Work
State explicitly:
- What this adds that we don't already have
- What this validates that we already built
- What this contradicts in our current approach (if anything)

SkillsBench validated our design philosophy at scale. New papers should be positioned relative to that validation — do they further support it, extend it to new domains, or challenge specific assumptions?

## Output Format
Conversational analysis, not a spec. The output is a prioritized assessment that informs whether to build, not the build itself. If a build is warranted, the output should include enough detail to feed into the Spec Writing skill.

Structure:
- Per-paper analysis (findings → weakness mapping → mechanism evaluation → concrete prosthetic)
- Priority ranking across all papers analyzed
- Recommendation: build now, build later, observe only, or not applicable

## Quality Checks
- [ ] Every finding links to a specific eval metric or observed behavior, not general claims
- [ ] Deterministic alternatives are proposed for every model-in-the-loop mechanism
- [ ] Cost (latency, compute) is estimated for each proposed prosthetic
- [ ] Existing Exocortex components that address similar problems are identified
- [ ] Papers that validate existing design decisions are explicitly called out

## Anti-Patterns
- **Summarizing instead of analyzing.** The user doesn't need a paper summary. They need to know what they can build with the findings.
- **Accepting the paper's approach uncritically.** Most papers use fine-tuning, RL, or model-in-the-loop approaches. The question is always "what's the deterministic version?"
- **Missing the validation angle.** Papers that confirm what we already built are as valuable as papers that suggest new builds. SkillsBench didn't give us new code — it gave us empirical confidence in existing code.
- **Proposing builds without cost estimates.** "We could add iterative retrieval" is incomplete. "We could add iterative retrieval at the cost of 2 extra FAISS queries per turn (sub-millisecond)" is actionable.
