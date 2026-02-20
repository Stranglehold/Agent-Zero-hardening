## Task: Build Memory Enhancement Extensions (v2.0)

Read `MEMORY_ENHANCEMENT_SPEC_L3.md` in the repo root first. That is the complete specification — 6 components, 2 extension files, 1 config modification. Build exactly what it describes, nothing more.

### Context
You are extending Agent-Zero's memory system. The existing memory classifier lives at:
- `/a0/python/extensions/monologue_end/_55_memory_classifier.py`

Read that file first to understand:
- How extensions access the FAISS index at `/a0/usr/memory/default/`
- How metadata is structured on LangChain Documents (classification dict, lineage dict)
- How `self.agent` provides access to context and logging
- The existing maintenance cycle pattern
- How the BST domain classification result is available in context

Also read:
- `/a0/usr/memory/classification_config.json` for current config structure
- Any existing extensions in `message_loop_prompts_after/` for hook patterns at that hook point
- The BST extension to understand how domain classification results are stored/accessible

### Files to Create

**1. `/a0/python/extensions/message_loop_prompts_after/_56_memory_enhancement.py`**
- Hook: `message_loop_prompts_after`
- Six responsibilities in this execution order:

  **a) Query Expansion** (Component 1):
  - Extract the user message content from the Agent-Zero dict message format
  - Get BST domain classification from context (if available, fallback to empty string)
  - Generate 3 query variants:
    - `original_query` = raw user message content
    - `keyword_query` = stopword-removed, noun/verb extraction, capped at 12 terms
    - `domain_query` = f"{bst_domain}: {keyword_query}"
  - Run FAISS similarity_search for each variant with `retrieval_k_per_variant` (default 8)
  - Merge results by memory ID, keeping highest similarity score per memory
  - This merged pool feeds into temporal decay

  **b) Temporal Decay** (Component 2):
  - For each memory in the merged candidate pool, compute:
    - `age_in_hours` from `last_accessed` (fallback `created_at`) to now
    - `decay_rate = ln(2) / half_life_hours`
    - `recency_score = exp(-decay_rate * age_in_hours)`
    - `final_score = (1 - decay_weight) * similarity + decay_weight * recency_score`
  - Exempt memories where classification shows `load_bearing` utility, `user_asserted` source, or `confirmed` validity — set `recency_score = 1.0`
  - Floor recency at `min_recency_score` (default 0.1)

  **c) Related Memory Boost** (Component 5 read-time):
  - After decay scoring, take preliminary top-k
  - For each selected memory, check `lineage.related_memory_ids`
  - For any related memory that exists in the broader candidate pool but didn't make the cut: add `related_boost` (default 0.08) to its `final_score`
  - Re-sort and re-select top-k with boosted scores

  **d) Top-K Selection**:
  - Select final memories for injection based on `memory.max_injected` from model profile (fallback to 5)

  **e) Access Tracking** (Component 3):
  - For each injected memory: `access_count += 1`, `last_accessed = utcnow()`
  - Write directly to the document metadata in the FAISS docstore

  **f) Co-Retrieval Logging** (Component 4):
  - Append entry to `/a0/usr/memory/co_retrieval_log.json` with timestamp, domain, memory_ids, cycle
  - FIFO eviction when entries exceed `max_entries` (500)
  - Create the file if it doesn't exist

- Read config from `/a0/usr/memory/classification_config.json` under `query_expansion`, `temporal_decay`, and `related_memories` keys.
- Read model profile from `/a0/usr/model_profiles/` for `memory.max_injected` and `memory.similarity_threshold` if available.
- Log prefix: `[MEM-ENHANCE]`

**Keyword extraction function** (include in _56):
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

def extract_keywords(text: str, max_keywords: int = 12) -> str:
    words = re.findall(r'\b\w+\b', text.lower())
    keywords = [w for w in words if w not in STOPWORDS and len(w) > 2]
    return ' '.join(keywords[:max_keywords])
```

---

**2. `/a0/python/extensions/monologue_end/_57_memory_maintenance.py`**
- Hook: `monologue_end`
- Four responsibilities (all run during maintenance cycle only):

  **a) Deduplication** (Component 6):
  - Every N cycles (read `maintenance_interval_loops` from config, default 25), scan memory pairs with cosine similarity > 0.90
  - Resolution hierarchy:
    - Both `agent_inferred` -> deprecate older with `superseded_by` pointing to newer
    - One `user_asserted` -> keep user memory, deprecate other
    - Both `user_asserted` -> flag for review, no auto-action
    - One `confirmed` -> keep confirmed, deprecate other
    - `load_bearing` utility -> never auto-deprecate, flag instead
  - Cap at `max_pairs_per_cycle` (default 20)

  **b) Related Memory Linking** (Component 5 write-time):
  - For memories processed during this maintenance cycle, extract classification tags
  - Compare tag sets between memory pairs
  - If `len(overlap) >= tag_overlap_threshold` (default 3): add each memory's ID to the other's `lineage.related_memory_ids`
  - Respect `max_related_per_memory` cap (default 10)
  - Initialize `related_memory_ids: []` on any memory that doesn't have it yet

  **c) Cluster Candidate Detection** (Component 4 maintenance):
  - Read `/a0/usr/memory/co_retrieval_log.json`
  - Find memory ID pairs co-occurring > `cluster_threshold` (default 5) times
  - Write qualifying pairs to `cluster_candidates` array in same file
  - Do NOT take any automatic consolidation action — observation only

  **d) Dormancy Check** (Component 3 maintenance):
  - Flag memories where `access_count == 0` and memory age > `archival_threshold_cycles` maintenance passes
  - Mark as candidates for `dormant` relevance reclassification
  - Log only — do not auto-reclassify

- Follow the same maintenance cycle pattern as `_55_memory_classifier.py` — use a cycle counter, only run expensive operations every N cycles.
- Log prefix: `[MEM-MAINT]`

---

**3. Modify `/a0/usr/memory/classification_config.json`**
Add these sections to existing config (do not overwrite existing sections):
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

### Critical Implementation Notes

1. **Agent-Zero message format**: Messages use `{'ai': False, 'content': {'user_message': 'text'}}` dict format, not raw strings. Check `_55_memory_classifier.py` for how it extracts content.

2. **Extension class pattern**: Follow whatever class pattern you see in the existing extensions at the target hook points. Agent-Zero loads extensions by numeric prefix order within each hook directory.

3. **FAISS access**: The memory index is at `/a0/usr/memory/default/`. LangChain's FAISS uses `index.pkl` containing a tuple of (docstore, id_mapping). Read `_55_memory_classifier.py` for how it loads and saves this. For query expansion, you need to call `similarity_search_with_score` (or equivalent) 3 times and merge results.

4. **BST domain access**: Find how the BST extension stores its domain classification result. It should be available on the agent context or in a known location. If not accessible, degrade gracefully — skip domain_query variant and run with 2 queries instead of 3.

5. **Logging**: Use `self.agent.context.log.log(type="info", content="message")` — the instance method pattern, not module-level.

6. **Related memory IDs field**: Not all memories will have `lineage.related_memory_ids` yet. Initialize it as an empty list when first encountered. Never fail on missing field.

7. **Co-retrieval log file**: Create `/a0/usr/memory/co_retrieval_log.json` if it doesn't exist. Use file locking or atomic writes if possible — both _56 and _57 access this file.

8. **Cache clearing**: After creating the files, clear Python cache:
   ```bash
   rm -rf /a0/python/extensions/message_loop_prompts_after/__pycache__/
   rm -rf /a0/python/extensions/monologue_end/__pycache__/
   ```

9. **Syntax validation**: Run `python3 -m py_compile` on each file before committing.

10. **No LLM calls**: Every operation must be deterministic. Math functions, threshold comparisons, metadata reads/writes. No calls to any model for memory operations.

11. **Import math**: You'll need `from math import exp, log` for the decay formula. `log` here is natural log (ln).

12. **Datetime handling**: Use `datetime.utcnow().isoformat()` for timestamps. Parse existing timestamps with `datetime.fromisoformat()`. Handle both `last_accessed` (may be null) and `created_at` fields.

13. **Graceful degradation**: Every component reads an `enabled` flag from config. If a component's config section is missing or `enabled: false`, skip it entirely and proceed with remaining components. The extension should never crash the agent loop.

---

### Execution Flow Reference

```
_56 pipeline (every turn):
  query_expansion -> temporal_decay -> related_boost -> top_k -> access_tracking -> co_retrieval_log

_57 pipeline (every 25 turns):
  deduplication -> related_linking -> cluster_detection -> dormancy_check
```

### Testing
After building, verify:
- Both files compile without errors (`python3 -m py_compile`)
- Config JSON is valid (`python3 -m json.tool`)
- Extensions load on container restart (check docker logs for `[MEM-ENHANCE]` and `[MEM-MAINT]` prefixes)
- No import errors or missing dependencies
- Query expansion generates 3 distinct FAISS queries
- Temporal decay exemptions work (load_bearing memories not penalized)
- Related memory IDs field initialized on first encounter without error
- Co-retrieval log created and respects FIFO cap
