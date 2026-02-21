# Claude Code Implementation Prompt — Layer 11: Ontology Layer

## Task
Read `ONTOLOGY_LAYER_SPEC_L3.md` in the repo root first. That is the complete specification.

You are building the Ontology Layer for Agent-Zero — 7 components across 15 new files and 4 modified files. This is the largest build in the Exocortex stack. Build incrementally: core components first (schema, store, resolution engine), then connectors and orchestrator.

## Context — Read These First

**Pattern source for Agent-Zero extensions:**
```
/a0/python/extensions/message_loop_prompts_after/_56_memory_enhancement.py
```
This is the most recent working extension. Study how it:
- Extracts user messages from `loop_data`
- Accesses FAISS via `Memory.get(self.agent)` and `db.search_similarity_threshold()`
- Reads config files with `json.load()`
- Writes to `loop_data.extras_persistent`
- Logs with `print("[PREFIX]", flush=True)`

**Pattern source for maintenance extensions:**
```
/a0/python/extensions/monologue_end/_57_memory_maintenance.py
```
Study how it:
- Implements cycle-counter gating (run every N cycles)
- Accesses `db.db.get_all_docs()` for full memory iteration
- Handles metadata reads and writes on memory documents

**Pattern source for Agent-Zero tools:**
```
/a0/python/tools/
```
Read the existing tool files to understand how Agent-Zero registers and invokes tools.

**Memory helper API:**
```
/a0/python/helpers/memory.py
```
Read this to understand `Memory.get()`, `search_similarity_threshold()`, `get_all_docs()`, and how to store new memories.

**Existing config to extend:**
```
/a0/usr/memory/classification_config.json
```

**Organization kernel structure:**
```
/a0/organizations/
```

## Build Order

### Phase 1: Foundation (build first)
1. `ontology_schema.json` — default schema with 7 entity types, 8 relationship types
2. `ontology_config.json` — all configuration with defaults from spec section 7
3. `resolution_engine.py` — the entity resolution pipeline (preprocessing, blocking, scoring, merge/flag/distinct, transitive closure)
4. Ontology store integration — function library for storing resolved entities as classified memories in FAISS with ontology metadata

### Phase 2: Ingestion
5. `csv_connector.py` — CSV/TSV ingestion producing CandidateEntity dicts
6. `json_connector.py` — JSON/JSONL ingestion with JSONPath mapping
7. `html_connector.py` — HTML text extraction with regex+heuristic entity detection
8. `relationship_extractor.py` — co-occurrence, property-based, temporal relationship discovery

### Phase 3: Agent-Zero Integration
9. `_58_ontology_query.py` — extension in `message_loop_prompts_after/` that adds entity detection and relationship expansion to the retrieval pipeline
10. `_59_ontology_maintenance.py` — extension in `monologue_end/` that runs ontology maintenance tasks on the cycle counter
11. `investigation_tools.py` — Agent-Zero tools for ontology_search, source_ingest, entity_resolve, relationship_query, investigation_report
12. `intelligence_analyst.json` — org kernel role definition

### Phase 4: Modifications
13. Modify `_56_memory_enhancement.py` — add entity detection hook that calls `_58`'s functions
14. Modify `_57_memory_maintenance.py` — add ontology maintenance tasks to existing cycle
15. Modify `classification_config.json` — add ontology config reference
16. Add Intelligence Analyst role to org kernel config

## Files to Create

### `/a0/usr/ontology/ontology_schema.json`
Default entity and relationship type definitions. Copy the schema structure exactly from spec section 4.1.

### `/a0/usr/ontology/ontology_config.json`
All configuration. Copy the complete JSON block from spec section 7 verbatim.

### `/a0/usr/ontology/resolution_engine.py`
**This is the most complex file.** The entity resolution pipeline with 5 stages:

1. **Preprocessing** — name normalization (lowercase, strip honorifics, normalize whitespace), address canonicalization, date normalization to ISO 8601, identifier extraction
2. **Blocking** — reduce N² comparisons. Group candidates by: exact identifier match, first 3 chars of normalized name + entity type, phonetic encoding (use `metaphone` if available, fall back to first-3-chars)
3. **Deterministic matching** — for each candidate pair in same block, compute weighted composite score across 5 axes (name, identifier, address, date, context). Use Levenshtein ratio for name_score (implement with `difflib.SequenceMatcher` — no external dependencies).
4. **Threshold decisions** — composite ≥ 0.85 → auto-merge, 0.60-0.85 → flag for review, < 0.60 → distinct
5. **Transitive closure** — union-find algorithm to consolidate merge chains

Provide these utility functions inline:
```python
def normalize_name(name: str) -> str:
    """Lowercase, strip honorifics (Mr/Mrs/Dr/Jr/Sr/III), normalize whitespace."""
    import re
    name = name.lower().strip()
    name = re.sub(r'\b(mr|mrs|ms|dr|jr|sr|iii|ii|iv)\b\.?', '', name)
    return re.sub(r'\s+', ' ', name).strip()

def levenshtein_ratio(s1: str, s2: str) -> float:
    """String similarity ratio using SequenceMatcher."""
    from difflib import SequenceMatcher
    return SequenceMatcher(None, s1, s2).ratio()

def canonicalize_address(addr: str) -> str:
    """Expand common abbreviations, normalize whitespace."""
    import re
    replacements = {
        r'\bst\b': 'street', r'\bave\b': 'avenue', r'\bblvd\b': 'boulevard',
        r'\bdr\b': 'drive', r'\bln\b': 'lane', r'\brd\b': 'road',
        r'\bcorp\b': 'corporation', r'\binc\b': 'incorporated', r'\bllc\b': 'llc',
        r'\bco\b': 'company', r'\bltd\b': 'limited',
    }
    addr = addr.lower().strip()
    for pattern, replacement in replacements.items():
        addr = re.sub(pattern, replacement, addr)
    return re.sub(r'\s+', ' ', addr).strip()
```

**Do not use any external NLP libraries.** Only stdlib: `re`, `json`, `datetime`, `difflib`, `collections`, `math`, `os`, `hashlib`.

### `/a0/usr/ontology/connectors/csv_connector.py`
Read CSV files, map columns to entity properties using the `default_mappings` from config. Produce list of CandidateEntity dicts. Use stdlib `csv` module only.

### `/a0/usr/ontology/connectors/json_connector.py`
Read JSON/JSONL files. Simple key mapping to entity properties. Stdlib `json` only.

### `/a0/usr/ontology/connectors/html_connector.py`
Extract entity candidates from HTML text using regex patterns for:
- Names (capitalized word sequences)
- Dates (various formats)
- Dollar amounts
- Addresses (number + street patterns)
Use stdlib `re` and `html` modules only.

### `/a0/usr/ontology/relationship_extractor.py`
Discover relationships from co-occurrence, shared properties, temporal proximity. Read the spec section 4.4 for the 5 discovery methods and confidence scoring.

### `/a0/python/extensions/message_loop_prompts_after/_58_ontology_query.py`
**Hook:** `message_loop_prompts_after`
**Fires after:** `_56_memory_enhancement.py`
**Pattern:** Follow `_56`'s class structure exactly.

Responsibilities:
1. Read user message from `loop_data` (same extraction as `_56`)
2. Check for entity name matches against ontology entities in FAISS (area="ontology")
3. For matched entities, read relationships from `relationships.jsonl`
4. Retrieve 1-hop connected entity summaries from FAISS
5. Inject structured relationship context into `loop_data.extras_persistent`

### `/a0/python/extensions/monologue_end/_59_ontology_maintenance.py`
**Hook:** `monologue_end`
**Fires after:** `_57_memory_maintenance.py`
**Pattern:** Follow `_57`'s class structure exactly, including cycle-counter gating.

Responsibilities (run every N cycles, read interval from ontology_config):
1. Re-run entity resolution on any unresolved candidates in ingestion queue
2. Update relationship confidence from co-retrieval data
3. Compact deprecated relationships from JSONL
4. Rebuild entity summaries for recently merged entities

### `/a0/python/tools/investigation_tools.py`
Agent-Zero tools exposed to the agent:
- `ontology_search(query, entity_type=None)` — search ontology entities
- `source_ingest(file_path, connector_type, source_id)` — run a connector on a file
- `entity_resolve(source_id=None)` — run resolution on pending candidates
- `relationship_query(entity_id, relationship_type=None, hops=1)` — traverse relationships
- `investigation_report(investigation_id)` — generate findings report with evidence chains

### `/a0/organizations/roles/intelligence_analyst.json`
Org kernel role:
- Domain: investigation, analysis, research
- PACE protocols for investigation tasks
- Tools: the investigation tools above

## Critical Implementation Notes

1. **Agent-Zero message format.** Messages use `loop_data.user_message.output_text()` for clean text. See how `_56` extracts it after the JSON wrapper fix — the `_get_query()` function parses out the `user_message` field from the JSON wrapper.

2. **Extension class pattern.** Every extension must:
   ```python
   from python.helpers.extension import Extension
   from agent import LoopData
   
   class ClassName(Extension):
       async def execute(self, loop_data: LoopData = LoopData(), **kwargs) -> Any:
   ```

3. **FAISS access.** Always use:
   ```python
   from python.helpers.memory import Memory
   db = await Memory.get(self.agent)
   # Search: db.search_similarity_threshold(query=q, limit=N, threshold=T)
   # All docs: db.db.get_all_docs()
   ```

4. **Memory metadata.** When storing entity memories, include both the standard Layer 10 classification fields AND the ontology metadata in the document's metadata dict. The `page_content` is the natural-language summary for FAISS search.

5. **Logging.** Use `print("[PREFIX] message", flush=True)` in extensions. Use prefixes:
   - `[ONT-QUERY]` for _58
   - `[ONT-MAINT]` for _59
   - `[ONT-RESOLVE]` for resolution engine
   - `[ONT-INGEST]` for connectors
   - `[ONT-INVEST]` for investigation tools

6. **No external dependencies.** The entire ontology layer uses Python stdlib only (re, json, csv, datetime, difflib, collections, math, os, hashlib, html). No numpy, no networkx, no spacy, no external NLP. FAISS access goes through Agent-Zero's existing LangChain wrapper.

7. **Graceful degradation.** Every component reads an `enabled` flag from config. If missing or false, skip silently. If ontology_config.json doesn't exist, create it with defaults on first access.

8. **File creation at runtime.** Create `/a0/usr/ontology/` directory and all JSONL files on first access if they don't exist. Never crash on missing files — create them.

9. **No LLM calls.** The entire ontology layer is deterministic. Entity resolution uses string metrics. Relationship extraction uses co-occurrence and property matching. No calls to `self.agent.call_utility_model()` or any model inference.

10. **Cache clearing.** After deploying any extension:
    ```bash
    rm -rf /a0/python/extensions/<hook_dir>/__pycache__/
    ```

11. **Syntax validation.** Before committing any file:
    ```bash
    python3 -m py_compile <file>
    ```

12. **Import requirements.** Extensions need: `json`, `os`, `re`, `datetime`, `typing`, `pathlib`. Resolution engine needs: `difflib`, `collections`, `hashlib` additionally. No third-party imports except Agent-Zero's own modules.

## Execution Flow Reference

```
_58 pipeline: entity_detect → ontology_search → relationship_expand → context_inject
_59 pipeline: cycle_check → queue_resolve → relationship_update → compact → summary_rebuild
resolution: preprocess → block → score → threshold → transitive_closure → store
connectors: read_source → extract_candidates → tag_provenance → write_queue
investigation: decompose → search_ontology → identify_sources → ingest → resolve → extract_relationships → report
```

## Testing

After building each phase, verify:

### Phase 1
```bash
python3 -m py_compile /a0/usr/ontology/resolution_engine.py
python3 -c "import json; json.load(open('/a0/usr/ontology/ontology_schema.json'))"
python3 -c "import json; json.load(open('/a0/usr/ontology/ontology_config.json'))"
```

### Phase 2
```bash
python3 -m py_compile /a0/usr/ontology/connectors/csv_connector.py
python3 -m py_compile /a0/usr/ontology/connectors/json_connector.py
python3 -m py_compile /a0/usr/ontology/connectors/html_connector.py
python3 -m py_compile /a0/usr/ontology/relationship_extractor.py
```

### Phase 3
```bash
python3 -m py_compile /a0/python/extensions/message_loop_prompts_after/_58_ontology_query.py
python3 -m py_compile /a0/python/extensions/monologue_end/_59_ontology_maintenance.py
rm -rf /a0/python/extensions/message_loop_prompts_after/__pycache__/
rm -rf /a0/python/extensions/monologue_end/__pycache__/
```

### Functional verification (after container restart)
```powershell
docker logs <container> 2>&1 | Select-String "ONT-QUERY|ONT-MAINT" | Select-Object -Last 10
```

Send a message mentioning an entity name. Verify `[ONT-QUERY]` appears in logs. Run 3+ message cycles and verify `[ONT-MAINT]` cycle counter increments.

## Files NOT to Modify
- `/a0/python/agent.py` — Agent-Zero core
- `/a0/python/helpers/memory.py` — Memory API
- `/a0/python/helpers/extension.py` — Extension base class
- `_50_recall_memories.py` — Standard recall
- `_55_memory_classifier.py` — Memory classification
