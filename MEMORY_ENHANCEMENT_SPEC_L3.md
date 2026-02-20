# Memory Enhancement System — Level 3 Specification
## Temporal Decay, Access Tracking, Query Expansion, Co-Retrieval Logging, Related Memory Links, and Deduplication

**Version:** 2.0
**Date:** 2026-02-20
**Status:** Active Build
**Layer:** 10b (Memory Enhancement — extends Layer 10 Memory Classification)

### Research Lineage
- **OwlCore.AI.Exocortex** (Arlodotexe, MIT License) — memory decay curves, recollection-as-memory, clustering and consolidation architecture
- **"Generative Agents: Interactive Simulacra of Human Behavior"** (Park et al., 2023) — recency x importance x relevance scoring for memory retrieval
- **"Recursively Summarizing Enables Long-Term Dialogue Memory in Large Language Models"** (Wang et al., 2023) — recursive summarization for long-term memory consolidation
- **"SkillsBench: Benchmarking How Well Agent Skills Work Across Diverse Tasks"** (Li, Chen et al., 2026, arXiv:2602.12670) — empirical validation that curated procedural knowledge improves agent performance by 16.2pp, focused injection (2-3 modules) outperforms comprehensive documentation, smaller models with Skills match larger models without them, and 16/84 tasks show negative deltas from Skills injection — validating profile-driven gating and injection volume control
- **"MemR3: Memory Retrieval via Reflective Reasoning for LLM Agents"** (Dec 2025, arXiv:2512.20237) — iterative retrieval with evidence-gap tracking improves LoCoMo by 7.29% through control logic, not better databases — informing deterministic query expansion
- **"A-MEM: Agentic Memory for LLM Agents"** (Xu et al., NeurIPS 2025, arXiv:2502.12110) — retroactive cross-linking of related memories at write time creates emergent graph structure — informing related memory links via tag overlap
- **openclaw/openclaw Issue #5547** — practical time-decay weighting formula with pinned path exemptions

---

## Motivation

The model evaluation profile for Qwen3-14B reveals:
- `memory_noise_discrimination: 0.5` — the model cannot distinguish relevant from irrelevant injected memories
- `memory_reference_rate: 1.0` — the model uses whatever it's given without filtering
- `memory_accuracy_rate: 0.95` — when given good memories, the model uses them well

The Qwen3-4B utility model shows identical weaknesses:
- `memory_noise_discrimination: 0.5` — same filtering blind spot regardless of model scale

**Conclusion:** Memory quality at injection time is the bottleneck, not model capability. The prosthetics must be smarter about what they inject because the model won't be smart about what it ignores.

This conclusion is independently validated by SkillsBench (Li, Chen et al., 2026), which found across 7,308 agent trajectories that:
- Curated procedural knowledge raises pass rates by 16.2pp — but **focused Skills with 2-3 modules outperform comprehensive documentation**. Injecting less, higher-quality context beats injecting more.
- **16 of 84 tasks show negative deltas** from Skills injection — validating the need for profile-driven gating (our `disabled_domains` mechanism).
- **Smaller models with Skills match larger models without them** (Haiku 4.5 with Skills beats Opus 4.5 without) — validating that deterministic scaffolding can substitute for model scale.
- **Self-generated Skills provide -1.3pp** — models cannot author their own procedural knowledge, confirming that the scaffolding must be externally curated and deterministic.

MemR3 further identifies that retrieval failures are primarily a **control logic problem**, not a database quality problem. Single-shot retrieval with one query is fragile. Their iterative approach uses model-in-the-loop reflection, which violates our deterministic principle. But the insight stands: retrieval quality improves when you query from multiple angles. Our query expansion module implements this deterministically.

Current memory classification (Layer 10) provides four-axis metadata but no temporal dimension. A memory classified as `active` and `tactical` today is weighted identically whether it was created two hours ago or two months ago. The `access_count` and `last_accessed` fields exist in lineage metadata but are unused.

---

## Design Principles

1. **Deterministic only** — No LLM calls for any memory operation. All scoring, tracking, clustering, and deduplication use heuristic rules and mathematical functions.
2. **Additive** — Extends existing classification infrastructure. Does not replace or modify the classification system.
3. **Non-destructive** — Never deletes memories. Deprecates with full audit trail via existing `superseded_by` lineage pointers.
4. **Profile-aware** — Reads `memory` section from active model profile for thresholds and injection counts.
5. **Multi-angle retrieval** — Queries from multiple perspectives to compensate for single-query fragility (informed by MemR3).
6. **Emergent structure** — Builds graph-like relationships from existing metadata rather than imposing external schema (informed by A-MEM).

---

## Component 1: Query Expansion on Retrieval

### Purpose
Compensate for single-query retrieval fragility by generating multiple query variants deterministically from the BST domain classification, then merging results before scoring. This addresses the 0.5 noise discrimination finding by improving what enters the candidate pool before temporal decay and top-k selection.

### Mechanism
```
Input: user_message, bst_domain (from BST classification)

1. original_query = user_message (or extracted content from message dict)
2. keyword_query = extract_keywords(original_query)
3. domain_query = f"{bst_domain}: {keyword_query}"

4. results_original = FAISS.similarity_search(original_query, k=retrieval_k)
5. results_keyword = FAISS.similarity_search(keyword_query, k=retrieval_k)
6. results_domain = FAISS.similarity_search(domain_query, k=retrieval_k)

7. merged = union(results_original, results_keyword, results_domain) by memory ID
8. For duplicates: keep highest similarity score across variants
9. Apply temporal decay scoring to merged set
10. Select top-k from merged, decayed set for injection
```

### Keyword Extraction (Deterministic)
```python
import re

STOPWORDS = {'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been',
             'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will',
             'would', 'could', 'should', 'may', 'might', 'shall', 'can',
             'to', 'of', 'in', 'for', 'on', 'with', 'at', 'by', 'from',
             'it', 'this', 'that', 'these', 'those', 'i', 'you', 'he',
             'she', 'we', 'they', 'me', 'him', 'her', 'us', 'them',
             'my', 'your', 'his', 'its', 'our', 'their', 'and', 'or',
             'but', 'not', 'no', 'if', 'then', 'so', 'just', 'about',
             'up', 'out', 'how', 'what', 'when', 'where', 'who', 'which',
             'there', 'here', 'all', 'each', 'some', 'any', 'into', 'as'}

def extract_keywords(text: str) -> str:
    words = re.findall(r'\b\w+\b', text.lower())
    keywords = [w for w in words if w not in STOPWORDS and len(w) > 2]
    return ' '.join(keywords[:12])  # cap at 12 keywords
```

### Configuration
Added to `/a0/usr/memory/classification_config.json`:
```json
{
  "query_expansion": {
    "enabled": true,
    "retrieval_k_per_variant": 8,
    "use_domain_scoping": true,
    "use_keyword_extraction": true,
    "max_keywords": 12
  }
}
```

### Integration Point
**Hook:** `message_loop_prompts_after`
**Execution:** Before temporal decay — generates query variants, performs 3x FAISS retrieval, merges results
**Dependency:** Requires BST domain classification to be available (runs after BST in hook chain)
**Cost:** 2 additional FAISS queries per turn (sub-millisecond on 100-1000 documents)

### Why Not Model-in-the-Loop?
MemR3 uses model reflection to refine queries iteratively. We use deterministic expansion because:
- No model calls = no latency penalty and no token cost
- Keyword extraction and domain scoping are reliable heuristics that don't degrade with model quality
- The model's 0.5 noise discrimination means it can't reliably judge what's missing
- Three parallel queries capture most of the benefit of iterative refinement for simple memory stores

---

## Component 2: Temporal Decay on Retrieval

### Purpose
Multiply FAISS similarity scores by a recency factor so stale memories rank lower during retrieval, unless they carry structural importance.

### Formula
```
recency_score = exp(-decay_rate * age_in_hours)
decay_rate = ln(2) / half_life_hours
final_score = (1 - decay_weight) * similarity_score + decay_weight * recency_score
```

### Configuration
```json
{
  "temporal_decay": {
    "enabled": true,
    "decay_weight": 0.15,
    "half_life_hours": 168,
    "exempt_utilities": ["load_bearing"],
    "exempt_sources": ["user_asserted"],
    "exempt_validities": ["confirmed"],
    "min_recency_score": 0.1
  }
}
```

### Exemptions
- `load_bearing` utility: always `recency_score = 1.0`
- `user_asserted` source: always `recency_score = 1.0`
- `confirmed` validity: always `recency_score = 1.0`

### Integration Point
**Hook:** `message_loop_prompts_after`
**Execution:** After query expansion returns merged FAISS results, before related memory boost and top-k selection

---

## Component 3: Access Tracking

### Purpose
Record when and how often each memory is actually used, providing empirical data for decay calculations and dormancy detection.

### Fields (already exist in lineage metadata)
```json
{
  "lineage": {
    "access_count": 0,
    "last_accessed": null
  }
}
```

### Behavior
- **On injection:** `access_count += 1`, `last_accessed = utcnow()`
- **Temporal decay source:** `last_accessed` feeds the recency calculation (fallback to `created_at`)
- **Dormancy signal:** Memories never accessed after `archival_threshold_cycles` become `dormant` candidates

### Integration Point
**Hook:** `message_loop_prompts_after`
**Execution:** After memory selection for injection, before prompt assembly

### Edge Cases
- `access_count: 0` and `last_accessed: null` — decay uses `created_at` as fallback
- Batch injection updates each memory independently
- Access tracking is write-only during inference — no reads on hot path

---

## Component 4: Co-Retrieval Logging

### Purpose
Track which memories are retrieved together to identify natural clusters over time.

### Storage
Lightweight JSON sidecar: `/a0/usr/memory/co_retrieval_log.json`

### Structure
```json
{
  "max_entries": 500,
  "entries": [
    {
      "timestamp": "2026-02-20T05:00:00Z",
      "query_domain": "codegen",
      "memory_ids": ["abc123", "def456", "ghi789"],
      "cycle": 42
    }
  ],
  "cluster_candidates": [
    {
      "memory_ids": ["abc123", "def456"],
      "co_retrieval_count": 7,
      "first_seen": "2026-02-18T00:00:00Z",
      "last_seen": "2026-02-20T05:00:00Z"
    }
  ]
}
```

### Entry Lifecycle
1. Each retrieval appends to `entries` (capped at `max_entries`, FIFO eviction)
2. During maintenance: scan for memory ID pairs co-occurring > `cluster_threshold` (default: 5)
3. Qualifying pairs promoted to `cluster_candidates`
4. Cluster candidates are informational — no automatic action taken

### Integration Point
**Hook:** `message_loop_prompts_after` (writes entries)
**Maintenance:** `monologue_end` during 25-cycle maintenance pass (reads entries, writes candidates)

---

## Component 5: Related Memory Links

### Purpose
Build emergent graph-like structure from classification metadata by cross-referencing memories that share significant tag overlap. During retrieval, linked memories receive a small score boost.

### Write-Time Mechanism (during maintenance)
```
For each memory M processed during maintenance:
    tags_M = set(M.metadata.classification.tags)
    For each other active memory N:
        tags_N = set(N.metadata.classification.tags)
        overlap = tags_M & tags_N
        If len(overlap) >= tag_overlap_threshold:
            Add N.id to M.lineage.related_memory_ids (if not present)
            Add M.id to N.lineage.related_memory_ids (if not present)
```

### Read-Time Mechanism (during retrieval scoring)
```
After temporal decay scoring produces candidate pool:
    For each selected memory S in top-k:
        For each related_id in S.lineage.related_memory_ids:
            If related_id in broader candidate pool but below cutoff:
                Boost related memory's final_score by related_boost
                Re-sort candidate pool
    Final top-k uses boosted scores
```

### New Metadata Field
```json
{
  "lineage": {
    "access_count": 0,
    "last_accessed": null,
    "related_memory_ids": []
  }
}
```

### Configuration
```json
{
  "related_memories": {
    "enabled": true,
    "tag_overlap_threshold": 3,
    "related_boost": 0.08,
    "max_related_per_memory": 10,
    "rebuild_interval_cycles": 25
  }
}
```

### Why Tag Overlap Instead of Embedding Similarity?
- Embedding similarity is already captured by FAISS — boosting by it would just amplify existing rankings
- Tag overlap captures categorical relationships (domain, utility, topic) that embeddings may miss
- Tags are discrete, deterministic, already computed during classification — no additional cost
- A-MEM uses LLM-generated descriptions for linking; we use classification tags for the same effect without model calls

### Integration Point
**Write-time:** `monologue_end`, during maintenance (in `_57_memory_maintenance.py`)
**Read-time:** `message_loop_prompts_after`, after temporal decay, before final top-k (in `_56_memory_enhancement.py`)

---

## Component 6: Deduplication

### Purpose
Identify and resolve redundant memories with very high semantic similarity.

### Algorithm
```
For each memory M in the pool:
    candidates = FAISS.similarity_search(M.content, k=5)
    For each candidate C where similarity > dedup_threshold:
        If M.id == C.id: skip
        If pair already processed: skip
        Apply resolution:
            Both agent_inferred -> deprecate older, superseded_by newer
            One user_asserted -> keep user_asserted, deprecate other
            Both user_asserted -> flag for review, no action
            One confirmed -> keep confirmed, deprecate other
        Log action
```

### Configuration
```json
{
  "deduplication": {
    "enabled": true,
    "similarity_threshold": 0.90,
    "auto_deprecate_agent_inferred": true,
    "max_pairs_per_cycle": 20,
    "log_all_candidates": true
  }
}
```

### Resolution Priority
1. `confirmed` > `user_asserted` > `inferred` > `deprecated`
2. Within same tier: newer supersedes older
3. `load_bearing` utility never auto-deprecated

### Integration Point
**Hook:** `monologue_end`, during maintenance cycle (every 25 loops)

---

## Pipeline Flow (per turn)

```
User Message
    |
    v
BST Domain Classification (existing Layer 3)
    |
    v
+--- _56_memory_enhancement.py ----------------------------+
|                                                           |
|  1. QUERY EXPANSION                                       |
|     original_query -> keyword_query -> domain_query       |
|     3x FAISS retrieval -> merge by ID -> keep max scores  |
|                                                           |
|  2. TEMPORAL DECAY                                        |
|     For each candidate in merged pool:                    |
|       age = now - last_accessed (or created_at)           |
|       recency = exp(-decay_rate * age_hours)              |
|       final = (1-weight) * similarity + weight * recency  |
|       (exempt: load_bearing, user_asserted, confirmed)    |
|                                                           |
|  3. RELATED MEMORY BOOST (read-time)                      |
|     For top-k candidates:                                 |
|       check related_memory_ids                            |
|       boost related memories in candidate pool            |
|       re-sort                                             |
|                                                           |
|  4. TOP-K SELECTION                                       |
|     Select final memories for injection                   |
|                                                           |
|  5. ACCESS TRACKING                                       |
|     For each injected memory:                             |
|       access_count += 1, last_accessed = utcnow()         |
|                                                           |
|  6. CO-RETRIEVAL LOGGING                                  |
|     Log memory_ids + domain to co_retrieval_log.json      |
|                                                           |
+-----------------------------------------------------------+
    |
    v
Prompt Assembly (existing)
    |
    v
Model Inference
    |
    v
+--- _57_memory_maintenance.py (every N cycles) -----------+
|                                                           |
|  1. DEDUPLICATION                                         |
|     Scan for >0.90 similarity pairs                       |
|     Apply resolution hierarchy                            |
|     Deprecate with superseded_by audit trail              |
|                                                           |
|  2. RELATED MEMORY LINKING (write-time)                   |
|     Compare tags across active memories                   |
|     If overlap >= 3: add to related_memory_ids            |
|                                                           |
|  3. CLUSTER DETECTION                                     |
|     Read co_retrieval_log.json                            |
|     Find pairs co-occurring > 5 times                     |
|     Write to cluster_candidates                           |
|                                                           |
|  4. DORMANCY CHECK                                        |
|     Flag memories with access_count=0 after N cycles      |
|                                                           |
+-----------------------------------------------------------+
```

---

## What This Does NOT Do

- Does NOT use LLM calls for any memory operation
- Does NOT delete memories — only deprecates with audit trail
- Does NOT consolidate clusters automatically (future enhancement, requires opt-in)
- Does NOT modify FAISS index structure — works with existing metadata and similarity search
- Does NOT modify `_55_memory_classifier.py` — runs as companion extensions
- Does NOT touch Agent-Zero core files
- Does NOT modify the classification axes — adds temporal scoring, query expansion, and related linking as retrieval modifiers
- Does NOT implement iterative model-in-the-loop retrieval (MemR3 style) — uses deterministic multi-query instead
- Does NOT build full graph memory (Mem0 style) — uses tag-overlap links as lightweight alternative

---

## File Inventory

| File | Location | Action | Purpose |
|------|----------|--------|---------|
| `_56_memory_enhancement.py` | `extensions/message_loop_prompts_after/` | CREATE | Query expansion, temporal decay, access tracking, co-retrieval logging, related memory boost |
| `_57_memory_maintenance.py` | `extensions/monologue_end/` | CREATE | Deduplication, related memory linking, cluster detection, dormancy |
| `classification_config.json` | `/a0/usr/memory/` | MODIFY | Add `query_expansion`, `temporal_decay`, `related_memories`, `deduplication` sections |
| `co_retrieval_log.json` | `/a0/usr/memory/` | CREATE (runtime) | Co-retrieval sidecar |

### Existing Files NOT Modified
| File | Note |
|------|------|
| `_55_memory_classifier.py` | Enhancement runs as separate extensions in the same hooks |

---

## Configuration Summary

All additions to `/a0/usr/memory/classification_config.json`:

```json
{
  "query_expansion": {
    "enabled": true,
    "retrieval_k_per_variant": 8,
    "use_domain_scoping": true,
    "use_keyword_extraction": true,
    "max_keywords": 12
  },
  "temporal_decay": {
    "enabled": true,
    "decay_weight": 0.15,
    "half_life_hours": 168,
    "exempt_utilities": ["load_bearing"],
    "exempt_sources": ["user_asserted"],
    "exempt_validities": ["confirmed"],
    "min_recency_score": 0.1
  },
  "related_memories": {
    "enabled": true,
    "tag_overlap_threshold": 3,
    "related_boost": 0.08,
    "max_related_per_memory": 10,
    "rebuild_interval_cycles": 25
  },
  "deduplication": {
    "enabled": true,
    "similarity_threshold": 0.90,
    "auto_deprecate_agent_inferred": true,
    "max_pairs_per_cycle": 20,
    "log_all_candidates": true
  }
}
```

---

## Testing Criteria

### Query Expansion (1-5)
1. Three FAISS queries generated per turn (original, keyword, domain-scoped)
2. Results merged by memory ID with highest score retained
3. Keyword extraction removes stopwords and caps at 12 terms
4. Domain prefix correctly applied from BST classification
5. Merged pool is larger than any single query's results

### Temporal Decay (6-10)
6. Memory with `last_accessed` 30 days ago scores lower than identical memory accessed today
7. `load_bearing` memories maintain full score regardless of age
8. `user_asserted` memories maintain full score regardless of age
9. `confirmed` memories maintain full score regardless of age
10. Decay curve follows exponential half-life (score ~ 0.5 at `half_life_hours`)

### Access Tracking (11-14)
11. `access_count` increments by 1 on each injection
12. `last_accessed` updates to current UTC on injection
13. Memories with `access_count: 0` use `created_at` for decay
14. Metadata persists across container restarts

### Co-Retrieval Logging (15-18)
15. Each retrieval creates an entry in co_retrieval_log.json
16. Entry contains correct memory IDs, domain, and cycle number
17. Log respects `max_entries` cap with FIFO eviction
18. Cluster candidates detected when pair co-occurs > threshold

### Related Memory Links (19-22)
19. Memories sharing 3+ tags get added to each other's related_memory_ids
20. Related memory boost applied correctly during retrieval scoring
21. Boost respects `max_related_per_memory` cap
22. Link rebuilding occurs only during maintenance cycles

### Deduplication (23-28)
23. Memory pairs with >0.90 cosine similarity identified
24. Both `agent_inferred`: older auto-deprecated with `superseded_by`
25. One `user_asserted`: user memory preserved, other deprecated
26. Both `user_asserted`: flagged, no auto-action
27. `load_bearing` never auto-deprecated
28. Respects `max_pairs_per_cycle` limit

---

## Dependency Map

```
classification_config.json
    +-- query_expansion config -> _56 (reads at init)
    +-- temporal_decay config  -> _56 (reads at init)
    +-- related_memories config -> _56 (read-time boost)
    |                           -> _57 (write-time linking)
    +-- deduplication config   -> _57 (reads at init)

BST domain classification (existing Layer 3)
    +-- _56 (reads domain for query expansion)

FAISS index (index.pkl)
    +-- _56 (multi-query retrieval, access metadata writes)
    +-- _57 (dedup similarity, deprecation + link metadata writes)

co_retrieval_log.json
    +-- _56 (writes entries)
    +-- _57 (reads for cluster detection, writes candidates)

Model profile (model_profiles/*.json)
    +-- _56 (reads memory.max_injected, memory.similarity_threshold)
```

---

*Spec compiled 2026-02-20 v2.0. Implementation targets Sonnet 4.6 deployment via Claude Code.*

---

## Further Reading (Adjacent Research)

Papers discovered during research that inform future Exocortex development:

- **"Memory in the Age of AI Agents"** (Zhang et al., Dec 2025, arXiv:2512.13564) — Comprehensive survey. Identifies procedural memory as underexplored — supports prioritizing procedural documents in the bookshelf system.
- **"A-MEM: Agentic Memory for LLM Agents"** (Xu et al., NeurIPS 2025, arXiv:2502.12110) — Write-time linking approach adopted for Component 5. MIT licensed.
- **"MemR3: Memory Retrieval via Reflective Reasoning"** (Dec 2025, arXiv:2512.20237) — Deterministic query expansion (Component 1) is our adaptation of their insight.
- **"AgeMem: Agentic Memory"** (Alibaba/Wuhan, Jan 2026, arXiv:2601.01885) — RL approach we deliberately avoid. Unified LTM/STM insight informs BST-scoped retrieval.
- **"SimpleMem"** (Jan 2026, github.com/aiming-lab/SimpleMem) — Validates deduplication. Future direction for working buffer compression (Layer 6).
- **"Mem0"** (Chhikara et al., Apr 2025, arXiv:2504.19413) — Graph memory as future direction if tag-linking ceiling is hit.
- **"SkillsBench"** (Li, Chen et al., Feb 2026, arXiv:2602.12670) — Validates entire Exocortex design philosophy.
