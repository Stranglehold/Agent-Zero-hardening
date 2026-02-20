# Skill: Claude Code Prompt Generation

## Trigger
Spec is complete and user is ready to hand off to Claude Code for implementation. Keywords: "build it," "get Claude Code working on this," "implementation prompt," "hand off to Sonnet."

## Inputs Required
- **Completed L3 spec** — must exist as a file, not just conversation context
- **Target model** — usually Sonnet 4.6 for implementation, Opus for design recovery
- **Existing code to reference** — the extension or file that the new build should pattern-match against

## Procedure

### 1. Identify the Pattern Source
Every new extension should pattern-match against an existing one. Find the closest existing extension:
- Same hook directory (e.g., if building in `monologue_end/`, read other `monologue_end/` extensions)
- Same type of operation (if building memory ops, read the memory classifier)
- Name it explicitly: "Read `_55_memory_classifier.py` first to understand..."

### 2. Write the Task Header
One paragraph: what is being built, how many files, what spec to read first.
- Always open with "Read `{SPEC_FILE}` in the repo root first. That is the complete specification."
- State file count and modification count upfront.

### 3. Context Section
Tell the implementation model what to read and why:
- The pattern source file (existing extension to learn from)
- Config files it will modify
- Other extensions in the same hook directory
- Any upstream dependency (e.g., BST domain classification output)

### 4. Files to Create Section
For each file, specify:
- **Full path** including the extension directory
- **Hook name**
- **Responsibilities** — numbered list in execution order
- For each responsibility: one paragraph describing the logic, referencing the spec component by name

If the component involves a utility function (like keyword extraction), include the complete function code inline. Sonnet should not have to design utility functions — give them verbatim.

### 5. Config Modifications
- Show the exact JSON block to add
- State explicitly: "Add these sections to existing config (do not overwrite existing sections)"
- Include all defaults

### 6. Critical Implementation Notes
Numbered list of everything that could trip up the implementation model:
- **Message format** — Agent-Zero's dict format, how to extract content
- **Extension class pattern** — follow whatever pattern exists in the target hook directory
- **Data access** — FAISS index location, how to load/save, what methods to use
- **Upstream data** — how to get BST domain, where context is stored
- **Logging pattern** — instance method, not module-level, with prefix
- **New fields** — initialize missing metadata fields gracefully, never crash on missing field
- **File creation** — create sidecar files at runtime if they don't exist
- **Cache clearing** — command to clear `__pycache__` after deployment
- **Syntax validation** — `python3 -m py_compile` before committing
- **No LLM calls** — restate this explicitly, every time
- **Import requirements** — specific modules needed (math, datetime, re, json)
- **Graceful degradation** — every component reads an `enabled` flag, skip if missing or false

### 7. Execution Flow Reference
Brief ASCII showing the pipeline order. Two lines:
```
_56 pipeline: query_expansion -> temporal_decay -> related_boost -> top_k -> access_tracking -> co_retrieval_log
_57 pipeline: deduplication -> related_linking -> cluster_detection -> dormancy_check
```

### 8. Testing Section
Minimal — compile check, JSON validation, docker log verification, and 3-5 specific functional checks. Sonnet should be able to run these immediately after building.

## Output Format
Single markdown file named `CLAUDE_CODE_PROMPT_{component_name}.md`. Deployable as-is into a Claude Code session.

## Quality Checks
- [ ] Opens with "Read the spec first"
- [ ] Pattern source file identified explicitly
- [ ] Every file has full path with correct hook directory
- [ ] All utility functions provided inline (Sonnet doesn't design, it implements)
- [ ] Config modifications shown as exact JSON with "do not overwrite" instruction
- [ ] Critical implementation notes cover: message format, class pattern, data access, logging, cache clearing, syntax validation, no LLM calls, graceful degradation
- [ ] Execution flow reference present
- [ ] Testing section includes compile check

## Anti-Patterns
- **Letting the implementation model make design decisions.** If the prompt says "decide how to handle X," you've failed. The spec makes all design decisions. The prompt translates them into implementation instructions.
- **Omitting the pattern source.** "Follow Agent-Zero's extension pattern" is useless. "Read `_55_memory_classifier.py` first" gives Sonnet a concrete reference.
- **Assuming the implementation model knows Agent-Zero internals.** It doesn't. Specify message format, FAISS access patterns, logging methods, hook signatures. Every time.
- **Writing a long prompt instead of a clear prompt.** SkillsBench: focused beats comprehensive. The prompt should be scannable. Numbered lists, code blocks, explicit paths. No prose paragraphs explaining philosophy.
