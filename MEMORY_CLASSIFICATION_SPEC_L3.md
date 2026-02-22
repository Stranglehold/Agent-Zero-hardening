# Memory Classification System — Level 3 Specification
## Four-Axis Structured Memory with Deterministic Conflict Resolution

---

## Intent

Transform Agent-Zero's existing FAISS memory system from an undifferentiated embedding pool into a classified knowledge store where every memory carries deterministic metadata controlling its epistemic weight, retrieval priority, operational role, and source lineage. The agent does not decide how to treat a memory — the metadata decides for it.

This system extends, not replaces, Agent-Zero's existing memory architecture. FAISS remains the storage and retrieval engine. Classification metadata is layered on top. Conflict resolution is deterministic. Role-aware filtering integrates with the Organization Kernel.

---

## Problem

Agent-Zero's current memory pool treats all memories equally. A user-stated fact ("my project uses Python 3.11") has the same retrieval weight as an agent-inferred assumption ("the project probably uses Python"). A deprecated approach sits alongside its correction. Memories relevant only during bugfix tasks surface during codegen. Conflict resolution defaults to embedding similarity and recency — both wrong heuristics for a reasoning agent.

The result: the model receives a grab-bag of memories with no signal about which ones to trust, which are outdated, or which apply to the current task context.

---

## Architecture Overview

```
Memory Write Path:
  Agent generates memory → Classification Engine tags four axes → Tagged memory stored in FAISS

Memory Read Path:
  Recall extension queries FAISS → Classification Filter applies role relevance + validity → 
  Filtered memories ranked by utility class + source priority → Injected into model context

Conflict Path:
  New memory contradicts existing → Conflict Resolver compares axes → 
  Loser marked deprecated with pointer to winner → Audit trail preserved
```

---

## Component 1: Classification Engine

### Hook Point
Extension in `monologue_end` pipeline, the primary memory storage extension. Stock memorizers (`_50_memorize_fragments.py`, `_51_memorize_solutions.py`) are disabled during installation to prevent unfiltered double-writes.

Suggested filename: `_55_memory_classifier.py`

### Four Axes

Every memory receives a metadata tag structure at write time. These are never inferred by the model at retrieval time.

**Axis 1: Validity**

| Value | Meaning | Assignment Rule |
|-------|---------|-----------------|
| `confirmed` | Verified fact, user-asserted, or high-trust source | User messages containing declarative statements; bookshelf documents (future); explicit corrections |
| `inferred` | Agent-generated during reasoning | Any memory extracted from agent's own output or monologue |
| `deprecated` | Contradicted by newer information | Set by conflict resolver; never set at initial write |

**Axis 2: Relevance**

| Value | Meaning | Assignment Rule |
|-------|---------|-----------------|
| `active` | Surfaces in standard retrieval | Default for all new memories; toggled by role activation |
| `dormant` | Valid but suppressed from ambient retrieval | Set when memory's BST domain doesn't match current role's domain list |

**Axis 3: Utility Class**

| Value | Meaning | Assignment Rule |
|-------|---------|-----------------|
| `load_bearing` | Structural — agent reasoning depends on this | User-stated constraints, architecture decisions, hard requirements. Keyword signals: "must", "always", "never", "requirement", "constraint" |
| `tactical` | Situationally useful reference | Task-specific knowledge, tool outputs, intermediate results |
| `archived` | Lessons learned, historical | Memories older than configurable threshold (default: 50 recall cycles without access) that haven't been accessed |

**Axis 4: Source**

| Value | Meaning | Assignment Rule |
|-------|---------|-----------------|
| `user_asserted` | Directly stated by user | Memory extracted from user message content |
| `agent_inferred` | Generated during agent reasoning | Memory extracted from agent monologue or tool output |
| `bookshelf_document` | From reference library (future) | Reserved for Bookshelf integration. Not implemented v1. |
| `external_retrieved` | From web search or API | Memory containing URL references or timestamped external data |

### Classification Logic

Classification MUST be deterministic. No model inference calls for classification. Rules:

1. **Source detection**: Read the memory's origin from Agent-Zero's existing memorization metadata. Memories from `_50_memorize_fragments` that originated from user messages → `user_asserted`. Memories from agent monologue → `agent_inferred`. Memories from `_51_memorize_solutions` → `agent_inferred` (solutions are agent-generated).

2. **Validity assignment**: `user_asserted` sources default to `confirmed`. `agent_inferred` sources default to `inferred`. Can be promoted to `confirmed` if user explicitly validates.

3. **Utility classification**: Scan memory text for load-bearing keyword signals. Match against configurable keyword list. Default to `tactical` if no strong signals. Memories that haven't been accessed in N recall cycles → automatically demote to `archived`.

4. **Relevance assignment**: All new memories start as `active`. Role-relevance filtering happens at read time, not write time (see Component 3).

### Metadata Storage

Read Agent-Zero's `/a0/python/helpers/memory.py` to understand how FAISS metadata/payloads work. The classification metadata must be stored alongside each memory's existing data.

**Schema (JSON, stored as FAISS metadata payload):**
```json
{
  "classification": {
    "validity": "confirmed|inferred|deprecated",
    "relevance": "active|dormant",
    "utility": "load_bearing|tactical|archived",
    "source": "user_asserted|agent_inferred|bookshelf_document|external_retrieved"
  },
  "lineage": {
    "created_at": "ISO-8601",
    "created_by_role": "role_id or null",
    "supersedes": "memory_id or null",
    "superseded_by": "memory_id or null",
    "access_count": 0,
    "last_accessed": "ISO-8601 or null"
  }
}
```

**Critical integration constraint**: Read the actual FAISS helper to understand whether metadata is stored as part of the embedding payload, as a separate sidecar structure, or in the FAISS index metadata field. The classification system must use whatever mechanism Agent-Zero already provides — do NOT build a parallel storage system. If FAISS metadata is limited (e.g., only string payloads), store classification as a JSON string in that field. If FAISS has no metadata support, maintain a sidecar JSON file at `/a0/usr/memory/default/classifications.json` keyed by memory ID.

---

## Component 2: Conflict Resolution

### Hook Point
Same extension as classification (`_55_memory_classifier.py`). Runs after classification, before the extension returns.

### Trigger
After classifying a new memory, scan existing memories for semantic contradiction. Use FAISS similarity search with the new memory's embedding to find the top-K most similar existing memories (K=5). For each candidate, check if the content contradicts the new memory.

### Contradiction Detection (Deterministic)

Do NOT use model inference to detect contradictions. Use deterministic heuristics:

1. **Entity overlap + value divergence**: Extract simple entity-value pairs from both memories using regex patterns. If same entity has different values → contradiction candidate. Example: "project uses Python 3.11" vs "project uses Python 3.9" → entity "python version", values diverge.

2. **Negation detection**: If new memory contains negation of a phrase in existing memory (or vice versa), flag as contradiction. Pattern: "does not use X" vs "uses X".

3. **Recency of user assertion**: If user says "actually, it's X" or "no, the correct answer is Y" → treat as explicit correction, always supersedes.

If no contradiction detected by heuristics, no action taken. False negatives are acceptable — they result in redundant memories, not incorrect ones. False positives are not acceptable — they would incorrectly deprecate valid memories.

### Resolution Priority Order

When contradiction is confirmed:

1. `user_asserted` ALWAYS wins over all other sources
2. `confirmed` wins over `inferred` within the same source class
3. `load_bearing` wins over `tactical` wins over `archived` within the same validity
4. More recent wins ONLY as a final tiebreaker when all other axes are equal

### Deprecation Mechanics

The losing memory is NOT deleted. It is:
1. `validity` set to `deprecated`
2. `lineage.superseded_by` set to winning memory's ID
3. Winning memory's `lineage.supersedes` set to losing memory's ID

Deprecated memories are excluded from standard retrieval but remain in FAISS for audit trail. They can be queried explicitly if the agent or user asks "what did we previously believe about X?"

---

## Component 3: Role-Aware Relevance Filter

### Hook Point
Extension in `message_loop_prompts_after` pipeline, running AFTER the existing recall extension (`_50_recall_memories.py`). The recall extension retrieves memories from FAISS. The relevance filter post-processes the results.

Suggested filename: `_55_memory_relevance_filter.py`

### Integration with Organization Kernel

Read the current role from `agent._org_active_role` (set by `_12_org_dispatcher.py`). Each role profile defines which BST domains it handles. Use this domain list to filter memories:

1. Read recalled memories from wherever `_50_recall_memories.py` stores them (likely `loop_data.extras_persistent` or similar — verify by reading the source).
2. For each recalled memory, check its classification metadata.
3. Apply filters in order:
   - **Validity filter**: Exclude `deprecated` memories entirely.
   - **Relevance filter**: If a role is active, check if the memory's `created_by_role` domain overlaps with the current role's domain list. Non-overlapping memories are suppressed (not shown to model) unless they are `load_bearing`.
   - **Utility ranking**: Within remaining memories, sort by: `load_bearing` first, then `tactical`, then `archived`. Within each tier, sort by `access_count` descending (frequently accessed = more useful).
4. Cap total injected memories at a configurable limit (default: 8). This prevents context bloat.

### Fallback Behavior

If no organization is active (`active.json` doesn't exist or dispatcher isn't loaded), skip role-based filtering entirely. Apply only validity filter (exclude deprecated) and utility ranking. The system degrades to "slightly smarter than raw FAISS recall" rather than breaking.

### Access Tracking

Every time a memory survives filtering and is injected into the model's context, increment its `access_count` and update `last_accessed`. This feeds the automatic archival mechanism — memories that are never accessed eventually demote from `tactical` to `archived`.

---

## Component 4: SALUTE Integration

The existing SALUTE report schema has an `environment` section. Extend it to include memory health metrics.

The `_12_org_dispatcher.py` already emits SALUTE reports. The memory classification system should write summary statistics that the dispatcher can include:

**Memory health metrics (written to agent data store, read by dispatcher):**
```json
{
  "memory_health": {
    "total_memories": 0,
    "by_validity": {"confirmed": 0, "inferred": 0, "deprecated": 0},
    "by_utility": {"load_bearing": 0, "tactical": 0, "archived": 0},
    "by_source": {"user_asserted": 0, "agent_inferred": 0},
    "conflicts_resolved_this_session": 0,
    "last_classification_run": "ISO-8601"
  }
}
```

Store on `agent._memory_health` or equivalent agent data attribute. The dispatcher reads this and includes it in the SALUTE `environment` section. The supervisor can then detect memory degradation (e.g., ratio of deprecated to confirmed memories exceeding a threshold).

---

## Component 5: Automatic Maintenance

### Archival Promotion
Run periodically (every N message loops, configurable, default 25):
- Memories with `utility: tactical` and `access_count: 0` and age > configurable threshold → promote to `archived`
- `archived` memories with `access_count > 3` in recent window → demote back to `tactical` (they're being used again)

### Deprecation Cleanup
Memories with `validity: deprecated` older than configurable retention period (default: 100 recall cycles) can be optionally purged from FAISS to reclaim index space. This is aggressive and should be off by default. Provide a configuration flag.

### Statistics Refresh
Update `agent._memory_health` statistics after every classification run. This is cheap — iterate the classification sidecar/metadata and count.

---

## Files to Read Before Implementation

1. `/a0/python/helpers/memory.py` — FAISS integration, how memories are stored, retrieved, and structured. This is the most critical file. Understand the Memory class, its methods for add/search/delete, and how metadata is attached to embeddings.

2. `/a0/python/extensions/monologue_end/_50_memorize_fragments.py` — How memories are extracted from conversation. Understand what data is available at memorization time (the full monologue, user messages, tool outputs).

3. `/a0/python/extensions/monologue_end/_51_memorize_solutions.py` — How solution memories differ from fragment memories.

4. `/a0/python/extensions/message_loop_prompts_after/_50_recall_memories.py` — How memories are recalled and injected. Understand where recalled memories are placed (likely `loop_data.extras_persistent` or `extras_temporary`) and what format they use.

5. `/a0/python/extensions/before_main_llm_call/_12_org_dispatcher.py` — Role activation, SALUTE emission, `agent._org_active_role` structure.

6. `/a0/usr/organizations/roles/*.json` — Role profile schema, specifically the `bst_domains` field that drives relevance filtering.

7. `/a0/python/helpers/extension.py` — Extension base class, how `execute()` works, what `LoopData` provides.

---

## Integration Contracts

### Attributes Read (do NOT write to these)
- `agent._org_active_role` — Current role profile dict (from org dispatcher)
- `agent._bst_store` — Current BST belief state (from BST extension)
- `loop_data.extras_persistent` — Where recalled memories are stored (verify by reading recall extension)

### Attributes Written
- `agent._memory_classifications` — Dict mapping memory IDs to classification metadata. Or, if FAISS supports inline metadata, stored directly in FAISS.
- `agent._memory_health` — Summary statistics dict for SALUTE integration.
- `agent._memory_conflict_log` — List of recent conflict resolutions (last 20) for supervisor observability.

### Files Written
- `/a0/usr/memory/default/classifications.json` — Persistent classification metadata (if sidecar approach needed). Loaded at agent startup, written after each classification run.
- Or, if FAISS metadata supports it, classifications stored inline (preferred — single source of truth).

### Configuration
Stored in a JSON file alongside the extension, consistent with other hardening layer configs:

```json
{
  "load_bearing_keywords": ["must", "always", "never", "requirement", "constraint", "critical", "essential", "mandatory", "do not", "required"],
  "archival_threshold_cycles": 50,
  "deprecation_retention_cycles": 100,
  "max_injected_memories": 8,
  "maintenance_interval_loops": 25,
  "conflict_top_k": 5,
  "enable_purge": false
}
```

---

## Testing Criteria

### Classification Accuracy
1. Send user message "My project uses Python 3.11" → memory stored → verify classification: `source: user_asserted`, `validity: confirmed`, `utility: load_bearing` (contains "must" equivalent — user stated as fact)
2. Agent infers "the file is probably in /tmp" → memory stored → verify: `source: agent_inferred`, `validity: inferred`, `utility: tactical`
3. Verify all four axes populated on every new memory (no nulls, no missing fields)

### Conflict Resolution
4. Store "project uses Python 3.9" (user_asserted) → then store "project uses Python 3.11" (user_asserted, newer) → verify first memory marked `deprecated` with `superseded_by` pointing to second
5. Store "the API uses REST" (agent_inferred) → then user says "actually the API uses GraphQL" (user_asserted) → verify agent_inferred memory deprecated regardless of recency
6. Verify deprecated memories do NOT appear in standard recall results

### Role-Aware Filtering
7. Activate bugfix_specialist role → recall memories → verify memories tagged with codegen/docker domains are suppressed (unless load_bearing)
8. Switch to codegen_specialist → verify previously suppressed codegen memories now appear
9. Verify load_bearing memories always surface regardless of role

### SALUTE Integration
10. Check SALUTE report `environment` section contains `memory_health` statistics
11. Verify `conflicts_resolved_this_session` increments after a conflict resolution

### Graceful Degradation
12. Delete `active.json` (no org) → verify memory system still works (classification + conflict resolution, minus role filtering)
13. Corrupt classifications.json → verify system recreates it from FAISS metadata or starts fresh without crashing
14. Verify all exceptions are caught and logged, never block the agent

### Access Tracking & Maintenance
15. Recall a memory 5 times → verify `access_count` is 5
16. Create tactical memory, never access it for 50+ cycles → verify automatic archival promotion
17. Access an archived memory 3+ times → verify demotion back to tactical

---

## Design Decisions Left to Implementer

- Whether FAISS metadata supports inline classification or requires sidecar file — determine by reading `memory.py`
- Exact regex patterns for entity-value extraction in conflict detection — use patterns consistent with BST's existing resolver chain
- How to obtain memory IDs for cross-referencing in lineage pointers — use whatever ID scheme FAISS/Agent-Zero already provides
- Whether classification runs synchronously or asynchronously — choose based on Agent-Zero's extension execution model
- Exact format of recalled memories in `loop_data` — determine by reading recall extension source

---

## What This Does NOT Do (Deferred)

- Bookshelf integration (document ingestion, synopsis generation, confidence-threshold retrieval) — deferred to next phase
- Model-based contradiction detection (too expensive, too unreliable for local models)
- Cross-agent memory sharing (macrocosm concern — same SALUTE-as-bridge pattern applies when ready)
- Memory visualization UI (useful but not architectural)
- Adaptive classification (learning from user corrections to improve keyword lists) — future enhancement

---

## Relationship to Existing Architecture

| Existing Component | Interaction |
|---|---|
| BST (Layer 1) | Classification reads BST domain from `_bst_store` to understand operational context at write time |
| Organization Kernel (Layer 0) | Relevance filter reads active role to determine which memories to surface |
| Graph Workflow Engine (Layer 2) | Graph node type could influence retrieval depth (deferred — not implemented v1) |
| Supervisor Loop (Layer 5) | Reads `_memory_health` from SALUTE to detect memory degradation |
| SALUTE Reports | Memory health metrics included in environment section |
| Tool Fallback Chain (Layer 4) | No direct interaction |
| Working Memory Buffer (Layer 6) | Complementary — working memory is 8-turn decay for entities, classification is persistent FAISS metadata. No overlap. |
| A2A Layer (Layer 8) | Memory health visible in A2A task status via SALUTE passthrough |

---

*Specification developed in Opus 4.6 architectural session, 2026-02-19. Implementation by Sonnet 4.6 via Claude Code using Level 3 methodology.*
