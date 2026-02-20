# Skill: Session Continuity Management

## Trigger
Start of any session, especially after context compaction. Also triggered when user references past work, says "where were we," "continue from," or asks about decisions made in previous sessions.

## Inputs Available
- **Compaction summary** — if present at top of context, contains structured summary of prior conversation
- **Transcripts** — full conversation logs at `/mnt/transcripts/`, named by datetime
- **Journal** — `/mnt/transcripts/journal.txt`, one-line summaries of every session
- **Memory** — `userMemories` tag in system prompt, background knowledge about the user
- **Past chats tools** — `conversation_search` and `recent_chats` for cross-session retrieval
- **Workflow state** — `/home/claude/.workflow_state.json` if a plan was active

## Procedure

### 1. Assess Context State
At session start, determine what you know:
- Is there a compaction summary? Read it — it contains the structured state of the previous conversation.
- Is the user continuing from a specific topic? Check if there's enough context to proceed or if you need to recover.
- Is there an active workflow plan? Check workflow state.

### 2. Recover Context (if needed)
If the user references something not in your current context:

**For specific topics:** Use `conversation_search` with substantive keywords (nouns, project names, technical terms). Run 2-3 searches with different keyword strategies — the same query expansion principle from MemR3.

**For recent work:** Use `recent_chats` with appropriate time filters. If the user says "yesterday," filter by yesterday's date range.

**For deep history:** Read the journal at `/mnt/transcripts/journal.txt` first — it's a one-line index of every session. Then read specific transcript files for detail. Use `view` with line ranges — don't try to read 400KB transcripts in one call.

**For project state:** Check `/mnt/user-data/outputs/` for the latest versions of specs, prompts, and README. These are the ground truth for current project state.

### 3. Establish Continuity
When referencing past work:
- State the context naturally, as if you remember it. Do not say "according to my records" or "I found in the transcript."
- If you're uncertain about a detail, say so directly rather than fabricating.
- If the user corrects you, update your understanding immediately. Use `memory_user_edits` if the correction is persistent.

### 4. Manage Active Workflows
If a workflow plan exists:
- Run `workflow.py status` to see current position
- Resume from where the plan left off
- If the plan is stale (from a previous session), confirm with the user before continuing

### 5. Handle Compaction Gracefully
When context is compacted mid-session:
- The compaction summary preserves key state. Read it carefully.
- Transcript of the full conversation is available at the path noted in the summary.
- Do NOT re-read the entire transcript unless you need a specific detail. The summary is designed to be sufficient for continuity.
- If you need a detail not in the summary, use targeted `view` with line ranges on the transcript.

## Key Paths
```
/mnt/transcripts/journal.txt          — Session index (read first)
/mnt/transcripts/*.txt                — Full transcripts (read targeted sections)
/mnt/user-data/outputs/               — Current project deliverables
/home/claude/.workflow_state.json      — Active workflow plan
```

## Quality Checks
- [ ] Never claim "I don't have access to previous conversations" without first trying the past chats tools
- [ ] Never read an entire 400KB+ transcript in one call — use journal index, then targeted reads
- [ ] Context references are natural, not meta-commentary about memory systems
- [ ] Active workflows are checked at session start
- [ ] Compaction summaries are treated as authoritative for session state

## Anti-Patterns
- **Reading everything.** The journal exists so you don't have to read every transcript. Index first, detail second.
- **Pretending to remember.** If you don't have the context and can't find it, say so. Don't fabricate continuity.
- **Ignoring the workflow tracker.** If a plan was active, it should be resumed or explicitly closed. Orphaned plans create confusion.
- **Meta-commentary about tools.** "Let me search my past conversations" is unnecessary. Just search and present the information naturally.
- **Re-reading compaction summaries aloud.** The user was there. They don't need a recap unless they ask for one.
