# Layer 11 — Ontology Layer
## Level 3 Specification

**Version:** 1.0
**Date:** 2026-02-21
**Status:** Design
**Depends on:** Layer 10 (Memory Classification), Layer 10b (Memory Enhancement), Layer 7 (Organization Kernel), Layer 1 (BST)

---

## 1. Research Lineage

- **Palantir Foundry Ontology Architecture** (Palantir Technologies, docs.palantir.com) — The Ontology as an operational layer that maps digital assets to real-world entities through objects, properties, and links. The fourfold integration of data, logic, action, and security as the core abstraction. Foundry's principle that the semantic model is the heart of the platform and everything else operates through it directly informs our ontology-first design.

- **OpenPlanter** (ShinMegamiBoson, github.com/ShinMegamiBoson/OpenPlanter, Apache 2.0 anticipated) — Recursive investigation agent with 19 tools for dataset ingestion, entity resolution, web search, and sub-agent delegation across heterogeneous datasets. Provider-agnostic LLM abstraction. Demonstrates that entity resolution across corporate registries, campaign finance, lobbying disclosures, and government contracts is feasible with an agent-based architecture. We extract the investigation decomposition pattern and the concept of workspace-scoped investigations.

- **"Multi-Agent RAG Framework for Entity Resolution"** (Aatif et al., Dec 2025, doi:10.3390/computers14120525, github.com/Aatif123-hub/Household-Discovery-using-Multi-Agents) — Decomposes entity resolution into four specialized agents: Direct (deterministic name matching), Indirect (transitive linkage), Household (address clustering), and Movement (temporal relocation detection). Achieves 94.3% accuracy on name variation matching with 61% fewer API calls than single-LLM baselines. Key insight: hybrid rule-based preprocessing with LLM-guided reasoning for ambiguous cases. We adopt the specialized-agent-per-resolution-type pattern and the deterministic-first principle.

- **Resolvi: A Reference Architecture for Extensible, Scalable and Interoperable Entity Resolution** (arXiv:2503.08087, Mar 2025) — Formal reference architecture for ER systems using 4+1 view model. Establishes canonical pipeline: preprocessing → blocking → candidate generation → matching → clustering → canonicalization. We adopt the pipeline decomposition for our deterministic resolution engine.

- **"MemR³: Memory Retrieval via Reflective Reasoning"** (Dec 2025) — Retrieval failures are a control logic problem. Already deployed in Layer 10b query expansion. The ontology layer extends this: querying the ontology requires multi-path retrieval across entity types, not just memory content. Query expansion becomes entity-aware.

- **"A-MEM: Agentic Memory for LLM Agents"** (Xu et al., NeurIPS 2025, MIT License) — Retroactive cross-linking of related memories at write time. Already deployed in Layer 10b related memory links. The ontology layer promotes these links from implicit tag-overlap associations to typed relationships with named semantics (employs, owns, funded_by, located_at).

- **"SkillsBench"** (Li, Chen et al., 2026) — Curated procedural knowledge improves agent performance by 16.2pp. Informs the design of investigation skills — procedural templates for recurring investigation patterns that the agent follows rather than improvises.

---

## 2. Motivation

The classified memory system (Layer 10/10b) stores 168+ memories with four-axis metadata, related memory links (90 cross-references built from tag overlap), and co-retrieval logging. This infrastructure was designed for conversational memory — things the agent learned during interactions. It was never designed to answer questions like:

- "Who are the major shareholders of Company X, and do any of them have connections to companies in sector Y?"
- "What government contracts were awarded to organizations connected to this lobbying group?"
- "Map the supply chain relationships for these semiconductor manufacturers."

These questions require **entity resolution across heterogeneous datasets** — the ability to ingest structured and unstructured data from multiple sources, identify that "J. Smith" in a corporate registry is the same person as "John Smith" in a campaign finance filing, and surface the relationship between their company and a government contract.

The existing memory system provides the storage infrastructure. Related memory links are proto-graph edges. Co-retrieval logging identifies natural clusters. Query expansion enables multi-path traversal. What's missing is:

1. **Entity schema** — a type system for entities, properties, and relationships (not just "memories" with tags)
2. **Source ingestion** — the ability to pull data from heterogeneous sources (CSV, JSON, HTML, scraped web pages, PDFs, APIs)
3. **Entity resolution** — deterministic matching to identify when records across different sources refer to the same real-world entity
4. **Typed relationships** — named, directional links between entities (employs, owns, funded_by) rather than undirected tag-overlap associations
5. **Investigation orchestration** — the ability to decompose "investigate X" into parallel sub-tasks across data sources

The memory enhancement system's eval data provides the empirical anchor:
- `memory_noise_discrimination: 0.5` — Both 4B and 14B models accept whatever memories they're given without filtering. An ontology with source provenance and confidence scoring gives the model structured grounds for discrimination.
- `memory_reference_rate: 1.0` — Models use everything injected. Entity-typed memories with relationship context provide higher-quality injection than undifferentiated fragments.
- Related memory links at 90 cross-references demonstrate that the tag-overlap mechanism produces meaningful structure even without explicit entity typing. Promoting this to a typed ontology amplifies the signal.

The Exocortex thesis — deterministic scaffolding over probabilistic reasoning — applies directly. Entity resolution is 80% deterministic (name normalization, address matching, date proximity, identifier linking) and 20% ambiguous (is "J. Smith at Acme Corp" the same person as "John Smith, consultant"?). Build the deterministic 80% as infrastructure. Route the ambiguous 20% to the model when the model router exists. Until then, flag ambiguous matches for human review.

---

## 3. Design Principles

- **Deterministic first.** Entity resolution uses heuristic matching (name normalization, Levenshtein distance, address canonicalization, identifier exact-match) before any model inference. The deterministic pipeline handles the majority of resolution. Model inference is reserved for genuinely ambiguous cases and is not required for the system to function.

- **Domain-agnostic.** The ontology schema defines entity types, property types, and relationship types — not domains. The same schema handles corporate investigations, supply chain mapping, political donor networks, and market analysis. You aim the system at data; relationships emerge from what's there.

- **Ontology-first.** Following Foundry's architecture: the semantic model is the core abstraction. Ingestion, resolution, querying, and visualization all operate through the ontology. An entity is an entity whether it came from a CSV, a web scrape, or an agent conversation.

- **Additive to classified memory.** Entities are stored as classified memories with additional ontology metadata. The existing four-axis classification (validity, relevance, utility, source), temporal decay, access tracking, and query expansion all apply to entity memories. The ontology extends the memory system; it does not replace it.

- **Source provenance always.** Every property value on every entity traces back to its source: which dataset, which record, which field, when ingested, confidence level. When sources conflict, both values are preserved with provenance. No information is silently overwritten.

- **Offline-capable.** Core entity resolution, relationship extraction, and ontology querying work without network access. Web scraping and external API ingestion require network but the ontology operates on whatever data has been ingested, regardless of connectivity.

---

## 4. Components

### 4.1 Entity Schema

**Purpose:** Define the type system for the ontology — what kinds of things exist, what properties they have, and what kinds of relationships connect them. The schema is the "language" of the ontology (following Foundry's Language/Engine/Toolchain decomposition). It must be domain-agnostic: the same type system represents people, organizations, locations, events, documents, and financial instruments without modification.

**Mechanism:**

Entity types are defined in a schema file. Each type specifies required and optional properties with data types. Relationships are typed and directional with their own properties.

```
Schema Structure:
  entity_types:
    person:
      properties: [name, aliases, date_of_birth, identifiers, description]
      required: [name]
    organization:
      properties: [name, aliases, type, jurisdiction, identifiers, description]
      required: [name]
    location:
      properties: [name, coordinates, address, type]
      required: [name]
    event:
      properties: [name, date, location, type, description]
      required: [name]
    document:
      properties: [title, date, source, type, content_hash]
      required: [title]
    financial_instrument:
      properties: [name, type, issuer, identifiers]
      required: [name]
    asset:
      properties: [name, type, owner, value, description]
      required: [name]

  relationship_types:
    employs: {from: organization, to: person, properties: [role, start_date, end_date]}
    owns: {from: [person, organization], to: [organization, asset], properties: [share_pct, since]}
    funded_by: {from: [organization, person, event], to: [person, organization], properties: [amount, date, type]}
    located_at: {from: [person, organization, event], to: location, properties: [since, type]}
    related_to: {from: any, to: any, properties: [type, confidence, evidence]}
    mentioned_in: {from: any, to: document, properties: [context, page, confidence]}
    participated_in: {from: [person, organization], to: event, properties: [role]}
    contracted_with: {from: organization, to: organization, properties: [value, date, type, contract_id]}
```

Entity types are extensible — users can define custom types that inherit base properties (name, aliases, identifiers, description) and add domain-specific ones. Relationship types follow the same pattern.

**Configuration:**
```json
{
  "ontology_schema": {
    "schema_file": "ontology_schema.json",
    "allow_custom_types": true,
    "default_confidence": 0.5,
    "require_source_provenance": true
  }
}
```

**Integration Point:** Schema file read by all other ontology components at initialization. Stored at `/a0/usr/ontology/ontology_schema.json`. Does not hook into Agent-Zero's pipeline — it's a static configuration.

**Edge Cases:**
- Schema file missing on first run → create with default entity and relationship types above
- Unknown entity type encountered during ingestion → classify as generic `entity` type with warning logged
- Relationship between entity types not defined in schema → store as `related_to` with evidence field noting the original relationship type

---

### 4.2 Source Connector Framework

**Purpose:** Ingest data from heterogeneous sources into a normalized intermediate format that the entity resolution engine can process. Each source type has a connector that handles parsing, field mapping, and initial entity extraction. The framework is pluggable — adding a new source type means adding a connector, not modifying the pipeline.

**Mechanism:**

```
Ingestion pipeline per source:
  1. Connector reads raw data (CSV, JSON, HTML, PDF text, API response)
  2. Connector extracts candidate entities with properties
  3. Each candidate tagged with source provenance:
     - source_id: unique identifier for this dataset
     - source_type: "csv" | "json" | "html_scrape" | "api" | "pdf" | "agent_conversation"
     - record_id: row number, URL, or unique key within the source
     - ingested_at: timestamp
     - confidence: connector's confidence in extraction (1.0 for structured, lower for scraped)
  4. Candidates written to ingestion queue for resolution
```

**Built-in connectors:**

| Connector | Input | Entity Extraction Method |
|-----------|-------|--------------------------|
| `csv_connector` | CSV/TSV files | Column mapping to entity properties (configurable) |
| `json_connector` | JSON/JSONL | JSONPath mapping to entity properties |
| `html_connector` | Scraped web pages | Regex + heuristic extraction of names, orgs, dates, addresses |
| `pdf_connector` | PDF text (via existing extraction) | Same as html_connector on extracted text |
| `agent_connector` | Agent conversation memories | Promote existing classified memories to typed entities |
| `api_connector` | REST API responses | JSON connector with authentication and pagination |

Each connector produces a list of `CandidateEntity` dicts:
```python
{
  "entity_type": "person",
  "properties": {"name": "John Smith", "role": "Director"},
  "relationships": [{"type": "employs", "target_hint": "Acme Corp"}],
  "provenance": {
    "source_id": "sec_filings_2024",
    "record_id": "row_142",
    "confidence": 1.0,
    "ingested_at": "2026-02-21T..."
  }
}
```

**Configuration:**
```json
{
  "source_connectors": {
    "enabled": true,
    "connectors_dir": "/a0/usr/ontology/connectors/",
    "ingestion_queue": "/a0/usr/ontology/ingestion_queue.jsonl",
    "max_batch_size": 500,
    "default_mappings": {
      "csv": {
        "name_columns": ["name", "full_name", "entity_name", "company_name", "org_name"],
        "date_columns": ["date", "filing_date", "effective_date", "start_date"],
        "amount_columns": ["amount", "value", "total", "contribution"],
        "address_columns": ["address", "location", "city", "state"]
      }
    }
  }
}
```

**Integration Point:** Connectors run as Agent-Zero tools, invoked by the agent during investigation tasks. The agent decides which connector to use based on the data source. Connectors write to the ingestion queue; the resolution engine reads from it. No Agent-Zero hooks — tool-chain execution.

**Edge Cases:**
- CSV with no header row → fall back to positional mapping, log warning
- Empty or malformed records → skip with provenance noting "extraction_failed"
- Duplicate source ingestion → check source_id + record_id; skip if already ingested unless `force_reingest` flag set
- Extremely large files (>100MB) → stream in batches per `max_batch_size`

---

### 4.3 Entity Resolution Engine

**Purpose:** Determine when candidate entities from different sources refer to the same real-world entity. This is the core intelligence of the ontology layer. Following the Resolvi reference architecture and the multi-agent ER paper's key insight: decompose resolution into specialized stages, each combining deterministic preprocessing with scored confidence.

**Mechanism:**

```
Resolution pipeline (per candidate batch):
  1. PREPROCESSING
     - Name normalization: lowercase, strip honorifics/suffixes, normalize whitespace
     - Address canonicalization: abbreviation expansion (St→Street, Corp→Corporation)
     - Date normalization: parse to ISO 8601
     - Identifier extraction: EIN, DUNS, ticker symbols, registration numbers

  2. BLOCKING (reduce comparison space)
     - Exact identifier match → same block
     - First 3 chars of normalized name + entity type → same block
     - Phonetic encoding (Soundex/Metaphone on name) → same block
     - Result: candidate pairs to compare, not N² comparisons

  3. DETERMINISTIC MATCHING (high-confidence resolution)
     Score each candidate pair on multiple axes:
     - name_score: Levenshtein ratio on normalized names (0.0-1.0)
     - identifier_score: 1.0 if any identifier matches exactly, 0.0 otherwise
     - address_score: token overlap ratio on canonicalized addresses
     - date_score: 1.0 if dates within 1 day, decaying to 0.0 over 365 days
     - context_score: Jaccard similarity of associated entity names/types

     Weighted composite: Σ(weight_i × score_i) / Σ(weight_i)

     If composite ≥ merge_threshold (default 0.85): AUTO-MERGE
       - Create single entity with properties from both candidates
       - Higher-confidence source wins for conflicting values
       - Both source provenances preserved
       - Merge logged in audit trail

     If composite ≥ review_threshold (default 0.60) and < merge_threshold: FLAG
       - Both candidates preserved
       - Potential match logged in review queue
       - Agent or user resolves manually

     If composite < review_threshold: DISTINCT
       - Both candidates become separate entities

  4. TRANSITIVE CLOSURE
     If A merged with B, and B merged with C → A, B, C are same entity
     Apply after all pairwise merges to catch chains

  5. RELATIONSHIP RESOLUTION
     For each candidate's relationship hints (e.g., "target_hint": "Acme Corp"):
     - Search existing entities for target by name/identifier
     - If found with confidence ≥ 0.80: create typed relationship
     - If found with lower confidence: create relationship with confidence score
     - If not found: create stub entity for target, mark as "unresolved"
```

**Why deterministic-first instead of LLM-first:**

The multi-agent ER paper achieves 94.3% accuracy with four specialized LLM agents and 61% fewer API calls than single-LLM approaches. But "fewer API calls" still means API calls. Our deterministic pipeline handles the cases that are unambiguous — exact identifier matches, high name similarity with matching addresses — without any model inference. The 80/20 split: 80% of entity pairs are clearly same or clearly different based on string metrics alone. The 20% that fall in the review zone (0.60-0.85 composite score) are where model reasoning adds value. Until the model router exists, these go to the review queue for human decision. When the router exists, route to 14B (strategic reasoning) for ambiguous resolution.

**Configuration:**
```json
{
  "entity_resolution": {
    "enabled": true,
    "merge_threshold": 0.85,
    "review_threshold": 0.60,
    "scoring_weights": {
      "name": 0.35,
      "identifier": 0.30,
      "address": 0.15,
      "date": 0.10,
      "context": 0.10
    },
    "blocking_strategies": ["identifier", "name_prefix", "phonetic"],
    "transitive_closure": true,
    "audit_log": "/a0/usr/ontology/resolution_audit.jsonl",
    "review_queue": "/a0/usr/ontology/review_queue.jsonl"
  }
}
```

**Integration Point:** Runs as a maintenance-class operation, triggered after source ingestion completes or on a configurable cycle. Reads from ingestion queue, writes resolved entities to the ontology store (Component 4.5). Can also be triggered manually by the agent as a tool. Does not hook into per-turn Agent-Zero pipeline — it's a batch operation.

**Edge Cases:**
- First entity of a type → no existing entities to match against; create directly
- Identifier conflict (two different entities share an identifier) → flag for review, do not auto-merge
- Name-only matching with very common names (e.g., "John Smith") → context_score becomes the tiebreaker; if context is insufficient, flag for review rather than merge
- Circular merge chains → transitive closure detects and consolidates
- Source retraction (source dataset corrected/removed) → mark affected entities with `source_retracted` flag; do not delete (non-destructive principle)

---

### 4.4 Relationship Extraction

**Purpose:** Identify and type the connections between resolved entities. While the resolution engine handles explicit relationship hints from source data, relationship extraction discovers implicit relationships from co-occurrence patterns, shared properties, and temporal proximity.

**Mechanism:**

```
Relationship discovery (runs after resolution):
  1. CO-OCCURRENCE RELATIONSHIPS
     Entities appearing in the same source record → "co_mentioned" relationship
     Entities appearing in the same document → "mentioned_in" + link between co-mentioned entities
     Weight by co-occurrence frequency across sources

  2. PROPERTY-BASED RELATIONSHIPS
     Shared address → "co_located" relationship with confidence from address_score
     Shared organization → "affiliated" relationship
     Shared identifiers (partial) → "potentially_related" with evidence

  3. TEMPORAL RELATIONSHIPS
     Events involving the same entities within configurable time windows → "temporally_linked"
     Sequence detection: entity A files document, entity B responds within N days → "responded_to"

  4. GRAPH-BASED DISCOVERY
     Promote existing Layer 10b related memory links to typed relationships where entity typing provides the semantics
     Co-retrieval clusters from Layer 10b → candidate relationship groups
     Shortest-path analysis between entities of interest

  5. CONFIDENCE SCORING
     Each discovered relationship gets a confidence score:
     - Explicit from source data: 1.0
     - Co-occurrence (≥3 sources): 0.8
     - Co-occurrence (1-2 sources): 0.5
     - Property-based inference: 0.6
     - Temporal inference: 0.4
     Relationships below configurable threshold (default 0.3) are stored but not surfaced in queries
```

**Configuration:**
```json
{
  "relationship_extraction": {
    "enabled": true,
    "co_occurrence_min_sources": 1,
    "temporal_window_days": 30,
    "min_confidence_to_surface": 0.3,
    "promote_memory_links": true,
    "max_hops_for_path_analysis": 4
  }
}
```

**Integration Point:** Runs as part of maintenance pipeline alongside Layer 10b maintenance (dedup, related linking). Reads from ontology store, writes relationships back. Periodic execution, not per-turn.

**Edge Cases:**
- Two entities co-occur in a single source but the source is low-confidence → cap relationship confidence at source confidence
- Path analysis finds a connection through 10+ hops → truncate at `max_hops_for_path_analysis`; note "indirect connection" in evidence
- Relationship type changes (entity was "employee" but new source says "consultant") → preserve both with temporal markers and source provenance

---

### 4.5 Ontology Store

**Purpose:** Persist entities, properties, and relationships in a queryable format that extends the existing classified memory system. Entities are stored as classified memories with additional ontology metadata. Relationships are stored as a separate graph structure that maps entity IDs to typed, directional edges.

**Mechanism:**

Each resolved entity becomes a classified memory with extended metadata:

```python
memory_metadata = {
  # Existing Layer 10 classification
  "validity": "confirmed",      # confirmed if from high-confidence source
  "relevance": "active",
  "utility": "tactical",        # or "load_bearing" for key entities in active investigations
  "source": "external_retrieved",

  # Existing Layer 10 lineage
  "lineage": {
    "created_at": "...",
    "access_count": 0,
    "last_accessed": None,
    "source_provenance": [...]
  },

  # New: Ontology metadata
  "ontology": {
    "entity_type": "person",
    "entity_id": "ent_a1b2c3d4",   # Stable identifier across merges
    "properties": {
      "name": "John Smith",
      "aliases": ["J. Smith", "John A. Smith"],
      "identifiers": {"ssn_last4": "1234"},
      "date_of_birth": "1985-03-15"
    },
    "provenance_chain": [
      {"source_id": "sec_filings_2024", "record_id": "row_142", "confidence": 1.0},
      {"source_id": "campaign_finance_q3", "record_id": "entry_89", "confidence": 0.9}
    ],
    "merge_history": [
      {"merged_from": "candidate_x7y8", "score": 0.92, "timestamp": "..."}
    ],
    "investigation_tags": ["active:supply_chain_q1"]
  }
}
```

The memory's `page_content` contains a natural-language summary of the entity for FAISS retrieval:
```
"John Smith (person) — Director at Acme Corp. Appears in SEC filings (2024) and Q3 campaign finance records. Connected to Acme Corp (employs), Widget Inc (board member)."
```

This ensures FAISS semantic search finds entities through natural-language queries while the structured `ontology` metadata enables precise graph traversal.

**Relationship graph** stored as a separate JSON file:
```python
# /a0/usr/ontology/relationships.jsonl
{
  "rel_id": "rel_001",
  "type": "employs",
  "from_entity": "ent_a1b2c3d4",
  "to_entity": "ent_e5f6g7h8",
  "properties": {"role": "Director", "start_date": "2020-01-15"},
  "confidence": 1.0,
  "provenance": {"source_id": "sec_filings_2024", "record_id": "row_142"},
  "created_at": "...",
  "updated_at": "..."
}
```

**Configuration:**
```json
{
  "ontology_store": {
    "enabled": true,
    "entities_area": "ontology",
    "relationships_file": "/a0/usr/ontology/relationships.jsonl",
    "entity_id_prefix": "ent_",
    "summary_max_length": 500,
    "rebuild_summary_on_merge": true
  }
}
```

**Integration Point:** Extends the existing FAISS memory store. Entities are stored in the same FAISS index as conversational memories but distinguished by `ontology.entity_type` metadata. The memory enhancement pipeline (Layer 10b) applies query expansion, temporal decay, and access tracking to entity memories the same way it handles conversational memories. The `area` field in memory classification is set to `"ontology"` for entity memories, enabling area-based filtering.

**Edge Cases:**
- FAISS index grows large with entity ingestion → entity summaries kept concise (max 500 chars); detailed properties live in metadata not in page_content
- Entity merge requires updating FAISS → delete old memory, create new memory with merged content and combined provenance chain
- Relationship graph file grows large → periodic compaction removes relationships marked as deprecated

---

### 4.6 Investigation Orchestrator

**Purpose:** Decompose investigation tasks into structured sub-tasks that can be executed through Agent-Zero's existing tool chain and organization kernel. An investigation is a named, scoped task that collects data from specified sources, resolves entities, and produces a structured report of findings.

**Mechanism:**

Following OpenPlanter's recursive delegation pattern and the org kernel's role-based dispatch:

```
Investigation lifecycle:
  1. TASK DECOMPOSITION
     User says "Investigate the supply chain for Company X"
     BST classifies as domain: investigation
     Org kernel activates "Intelligence Analyst" role
     Orchestrator decomposes into sub-tasks:
       a. Search existing ontology for Company X and known relationships
       b. Identify data sources to query (SEC filings, news, corporate registries)
       c. For each source: ingest, extract entities, resolve
       d. Run relationship extraction on new + existing entities
       e. Build findings report with evidence chains

  2. SUB-TASK EXECUTION
     Each sub-task maps to an Agent-Zero tool or tool chain:
       - Ontology search → memory retrieval with area="ontology" filter
       - Web scraping → existing code_execution tool with scraping scripts
       - Source ingestion → source connector tools (Component 4.2)
       - Entity resolution → resolution engine tool (Component 4.3)
       - Report generation → structured output to file

  3. EVIDENCE CHAINS
     Every finding traces back through:
       finding → relationship → entity → provenance → source record
     The report includes the chain for each finding.
     Confidence is the minimum confidence across the chain.

  4. INVESTIGATION SCOPE
     Each investigation has:
       - investigation_id: unique identifier
       - name: human-readable description
       - target_entities: starting points
       - source_scope: which sources to query
       - depth: how many relationship hops to follow
       - status: active | paused | complete
     Entities discovered during investigation get tagged with investigation_id
     for traceability.
```

**Configuration:**
```json
{
  "investigation": {
    "enabled": true,
    "max_depth": 3,
    "max_entities_per_investigation": 500,
    "auto_resolve_on_ingest": true,
    "findings_dir": "/a0/usr/ontology/investigations/",
    "evidence_chain_min_confidence": 0.4
  }
}
```

**Integration Point:** The orchestrator is an Agent-Zero extension in `before_main_llm_call/` that detects investigation-type queries (via BST domain classification) and injects investigation context into the agent's prompt. Sub-tasks execute through the existing tool chain. Investigation state persists to disk.

An "Intelligence Analyst" role is added to the organization kernel with:
- Domain: investigation, analysis, research
- Tools: ontology_search, source_ingest, entity_resolve, relationship_query, investigation_report
- PACE protocols: Primary (ontology search), Alternate (web scrape + ingest), Contingent (broaden search scope), Emergency (report partial findings with confidence flags)

**Edge Cases:**
- Investigation target not found in ontology → create stub entity, proceed to external source search
- Source unavailable (network down, API rate limited) → log failure, continue with available sources, note coverage gaps in report
- Investigation scope too broad (>500 entities discovered) → pause at threshold, report partial findings, request user guidance on focus
- Overlapping investigations → entities tagged with multiple investigation_ids; cross-investigation findings are a feature, not a bug

---

### 4.7 Ontology Query Interface

**Purpose:** Enable the agent to query the ontology during normal conversation, not just during formal investigations. When the agent encounters an entity name, organization, or topic that exists in the ontology, it should be able to traverse relationships and provide context without requiring the user to initiate an investigation.

**Mechanism:**

Extends the Layer 10b memory enhancement pipeline:

```
Ontology-aware retrieval (extends _56_memory_enhancement.py):
  1. Standard query expansion runs (original, keyword, domain-scoped)
  2. NEW: Entity detection in user message
     - Check if any named entities in the message match ontology entity names/aliases
     - If match found: add entity-specific queries to expansion set
       - "relationships of [entity_name]"
       - "[entity_type] connected to [entity_name]"
  3. Retrieved memories include both conversational and ontology memories
  4. NEW: For ontology memories, also retrieve connected entities (1-hop)
     - Read relationship graph for matched entity_ids
     - Retrieve connected entity summaries
     - Inject as structured context: "Known connections: [entity] --[relationship]--> [entity]"
  5. Standard temporal decay, access tracking, co-retrieval logging apply
```

**Configuration:**
```json
{
  "ontology_query": {
    "enabled": true,
    "entity_detection_in_messages": true,
    "auto_expand_relationships": true,
    "relationship_hops": 1,
    "max_connected_entities": 10,
    "inject_format": "structured"
  }
}
```

**Integration Point:** Extension of `_56_memory_enhancement.py` in `message_loop_prompts_after/`. Runs after standard query expansion. Reads from FAISS (entity memories) and relationship graph file. Writes additional context to `loop_data.extras_persistent`.

**Edge Cases:**
- Common name matches multiple entities → include disambiguation context (entity type, key relationships) so the model can determine which is relevant
- Entity exists but has no relationships → return entity properties only, no relationship expansion
- Too many connected entities (>10) → sort by relationship confidence, return top N

---

## 5. Pipeline Flow Diagram

### Per-Turn Pipeline (Hot Path — extends existing Layer 10b)

```
User message
    │
    ▼
BST domain classification (Layer 1)
    │
    ├── domain: investigation → activate Investigation Orchestrator (4.6)
    │                            decompose into sub-tasks
    │                            execute via tool chain
    │
    └── domain: other → standard pipeline continues
                            │
                            ▼
                  Memory Enhancement (_56)
                    │
                    ├── Standard query expansion (3 variants)
                    ├── NEW: Entity detection + ontology queries (4.7)
                    ├── FAISS retrieval (conversational + ontology memories)
                    ├── NEW: Relationship expansion (1-hop connected entities)
                    ├── Temporal decay scoring
                    ├── Access tracking
                    └── Inject into extras_persistent
                            │
                            ▼
                  Main LLM call (with ontology context injected)
```

### Investigation Pipeline (Triggered by investigation tasks)

```
"Investigate [target]"
    │
    ▼
Investigation Orchestrator (4.6)
    │
    ├── Search existing ontology for target
    ├── Identify external sources
    │
    ▼
Source Connectors (4.2)              ← parallel per source
    │
    ├── CSV connector
    ├── HTML/scrape connector
    ├── API connector
    └── PDF connector
    │
    ▼
Ingestion Queue (JSONL)
    │
    ▼
Entity Resolution Engine (4.3)
    │
    ├── Preprocessing (normalize, canonicalize)
    ├── Blocking (reduce comparison space)
    ├── Deterministic matching (score + threshold)
    ├── Transitive closure
    └── Relationship resolution
    │
    ▼
Ontology Store (4.5)
    │
    ├── Entities → FAISS as classified memories
    └── Relationships → relationships.jsonl
    │
    ▼
Relationship Extraction (4.4)
    │
    ├── Co-occurrence analysis
    ├── Property-based inference
    ├── Temporal analysis
    └── Graph-based discovery
    │
    ▼
Investigation Report (findings + evidence chains)
```

### Maintenance Pipeline (extends existing Layer 10b maintenance cycle)

```
Every N cycles (_57 maintenance fires):
    │
    ├── Existing: deduplication, related memory linking
    │
    ├── NEW: Ontology maintenance
    │   ├── Re-run entity resolution on unresolved candidates
    │   ├── Update relationship confidence from co-retrieval data
    │   ├── Compact deprecated relationships
    │   ├── Rebuild entity summaries for merged entities
    │   └── Update investigation status (stale check)
    │
    └── Report: entities resolved, relationships updated, investigations active
```

---

## 6. File Inventory

### Files to CREATE

| File | Location | Purpose |
|------|----------|---------|
| `ontology_schema.json` | `/a0/usr/ontology/` | Entity and relationship type definitions |
| `ontology_config.json` | `/a0/usr/ontology/` | All ontology layer configuration |
| `relationships.jsonl` | `/a0/usr/ontology/` | Relationship graph store |
| `ingestion_queue.jsonl` | `/a0/usr/ontology/` | Candidate entities awaiting resolution |
| `resolution_audit.jsonl` | `/a0/usr/ontology/` | Merge/split decisions with evidence |
| `review_queue.jsonl` | `/a0/usr/ontology/` | Ambiguous matches awaiting human/model review |
| `_58_ontology_query.py` | `/a0/python/extensions/message_loop_prompts_after/` | Ontology-aware retrieval extension |
| `_59_ontology_maintenance.py` | `/a0/python/extensions/monologue_end/` | Ontology maintenance extension |
| `csv_connector.py` | `/a0/usr/ontology/connectors/` | CSV ingestion connector |
| `json_connector.py` | `/a0/usr/ontology/connectors/` | JSON ingestion connector |
| `html_connector.py` | `/a0/usr/ontology/connectors/` | HTML/scrape ingestion connector |
| `resolution_engine.py` | `/a0/usr/ontology/` | Entity resolution pipeline |
| `relationship_extractor.py` | `/a0/usr/ontology/` | Relationship discovery |
| `investigation_tools.py` | `/a0/python/tools/` | Agent-Zero tools for investigation tasks |
| `intelligence_analyst.json` | `/a0/organizations/roles/` | Org kernel role definition |

### Files to MODIFY

| File | Location | Modification |
|------|----------|-------------|
| `_56_memory_enhancement.py` | `message_loop_prompts_after/` | Add entity detection and relationship expansion to query pipeline |
| `_57_memory_maintenance.py` | `monologue_end/` | Add ontology maintenance tasks to maintenance cycle |
| `classification_config.json` | `/a0/usr/memory/` | Add ontology configuration sections |
| Organization kernel config | `/a0/organizations/` | Add Intelligence Analyst role |

### Files NOT modified

| File | Location | Reason |
|------|----------|--------|
| `_50_recall_memories.py` | `message_loop_prompts_after/` | Standard recall unaffected; _56 handles ontology queries |
| `_55_memory_classifier.py` | `monologue_end/` | Classification system unchanged; ontology entities classified using existing axes |
| `memory.py` | `/a0/python/helpers/` | FAISS API unchanged; entities stored as standard memories |
| Agent-Zero core files | `/a0/python/` | No core modifications |

---

## 7. Configuration Summary

Complete new configuration for `ontology_config.json`:

```json
{
  "ontology_schema": {
    "schema_file": "ontology_schema.json",
    "allow_custom_types": true,
    "default_confidence": 0.5,
    "require_source_provenance": true
  },
  "source_connectors": {
    "enabled": true,
    "connectors_dir": "/a0/usr/ontology/connectors/",
    "ingestion_queue": "/a0/usr/ontology/ingestion_queue.jsonl",
    "max_batch_size": 500,
    "default_mappings": {
      "csv": {
        "name_columns": ["name", "full_name", "entity_name", "company_name", "org_name"],
        "date_columns": ["date", "filing_date", "effective_date", "start_date"],
        "amount_columns": ["amount", "value", "total", "contribution"],
        "address_columns": ["address", "location", "city", "state"]
      }
    }
  },
  "entity_resolution": {
    "enabled": true,
    "merge_threshold": 0.85,
    "review_threshold": 0.60,
    "scoring_weights": {
      "name": 0.35,
      "identifier": 0.30,
      "address": 0.15,
      "date": 0.10,
      "context": 0.10
    },
    "blocking_strategies": ["identifier", "name_prefix", "phonetic"],
    "transitive_closure": true,
    "audit_log": "/a0/usr/ontology/resolution_audit.jsonl",
    "review_queue": "/a0/usr/ontology/review_queue.jsonl"
  },
  "relationship_extraction": {
    "enabled": true,
    "co_occurrence_min_sources": 1,
    "temporal_window_days": 30,
    "min_confidence_to_surface": 0.3,
    "promote_memory_links": true,
    "max_hops_for_path_analysis": 4
  },
  "ontology_store": {
    "enabled": true,
    "entities_area": "ontology",
    "relationships_file": "/a0/usr/ontology/relationships.jsonl",
    "entity_id_prefix": "ent_",
    "summary_max_length": 500,
    "rebuild_summary_on_merge": true
  },
  "ontology_query": {
    "enabled": true,
    "entity_detection_in_messages": true,
    "auto_expand_relationships": true,
    "relationship_hops": 1,
    "max_connected_entities": 10,
    "inject_format": "structured"
  },
  "investigation": {
    "enabled": true,
    "max_depth": 3,
    "max_entities_per_investigation": 500,
    "auto_resolve_on_ingest": true,
    "findings_dir": "/a0/usr/ontology/investigations/",
    "evidence_chain_min_confidence": 0.4
  }
}
```

---

## 8. Testing Criteria

### 4.1 Entity Schema
1. Default schema file created on first run with all 7 entity types and 8 relationship types
2. Custom entity type added via config loads successfully and is available for classification
3. Candidate with unknown entity type classified as generic `entity` with warning logged

### 4.2 Source Connectors
1. CSV file with headers "company_name, amount, filing_date" produces CandidateEntity dicts with correct type mapping
2. JSON file with nested objects extracts entities with JSONPath-mapped properties
3. Duplicate source ingestion (same source_id + record_id) skipped without creating duplicate candidates
4. Malformed CSV row skipped with provenance noting "extraction_failed"; pipeline continues

### 4.3 Entity Resolution Engine
1. Two candidates with identical EIN/DUNS identifiers merge automatically with composite score ≥ 0.85
2. Two candidates with name "John Smith" vs "J. Smith" and same address merge; different address flags for review
3. Candidate with name "John Smith" and no other matching signals treated as distinct from existing "John Smith" at different organization
4. Transitive closure: A merges with B, B merges with C → resulting entity contains provenance from A, B, and C
5. Resolution audit log contains entry for every merge decision with scores and evidence

### 4.4 Relationship Extraction
1. Two entities appearing in same source record produce "co_mentioned" relationship with confidence ≥ 0.5
2. Entities sharing address produce "co_located" relationship
3. Relationship with confidence below `min_confidence_to_surface` stored but excluded from query results
4. Existing Layer 10b related memory links for entities promoted to typed relationships

### 4.5 Ontology Store
1. Resolved entity stored in FAISS with `area == "ontology"` and `ontology.entity_type` in metadata
2. Entity page_content contains natural-language summary searchable by FAISS semantic similarity
3. Entity merge updates FAISS memory (old removed, new created) with combined provenance
4. Relationship graph file contains valid JSONL with all required fields per entry

### 4.6 Investigation Orchestrator
1. "Investigate Company X" decomposes into sub-tasks: ontology search, source identification, ingestion, resolution, report
2. Entities discovered during investigation tagged with investigation_id
3. Investigation exceeding `max_entities_per_investigation` pauses and reports partial findings
4. Evidence chain in report traces from finding through relationship, entity, and provenance to source record

### 4.7 Ontology Query Interface
1. User message mentioning entity name that exists in ontology triggers entity-specific FAISS query
2. Retrieved ontology memory includes 1-hop relationship context in injected extras
3. Common name matching multiple entities includes disambiguation context (entity type, key relationships)
4. Query for entity with no relationships returns entity properties only, no error

---

## 9. Dependency Map

```
ontology_config.json
    ├── read by: _58_ontology_query.py
    ├── read by: _59_ontology_maintenance.py
    ├── read by: resolution_engine.py
    ├── read by: relationship_extractor.py
    ├── read by: investigation_tools.py
    └── read by: all connectors

ontology_schema.json
    ├── read by: resolution_engine.py (entity type validation)
    ├── read by: all connectors (type mapping)
    └── read by: _58_ontology_query.py (entity detection)

FAISS index (/a0/usr/memory/default/)
    ├── read/write by: _56_memory_enhancement.py (existing)
    ├── read/write by: _58_ontology_query.py (entity retrieval)
    ├── read/write by: ontology_store (entity persistence)
    └── read by: _57/_59 maintenance

relationships.jsonl
    ├── write by: resolution_engine.py (relationship resolution)
    ├── write by: relationship_extractor.py
    ├── read by: _58_ontology_query.py (relationship expansion)
    ├── read by: investigation_tools.py (evidence chains)
    └── read/write by: _59_ontology_maintenance.py

ingestion_queue.jsonl
    ├── write by: all connectors
    └── read by: resolution_engine.py

resolution_audit.jsonl
    └── write by: resolution_engine.py

review_queue.jsonl
    ├── write by: resolution_engine.py
    └── read by: investigation_tools.py (present to user/model)

classification_config.json (existing)
    └── modified: add ontology config reference

model_profiles/*.json (existing)
    └── read by: _58 for entity detection thresholds
    └── read by: resolution_engine if model-assisted resolution enabled

intelligence_analyst.json (org kernel)
    └── read by: org kernel dispatcher when BST domain = investigation
```

---

## 10. What This Does NOT Do

1. **Does not perform web scraping autonomously.** The source connectors ingest data that the agent retrieves through its existing tool chain (code execution, web fetch). The ontology layer processes data; the agent collects it. No autonomous crawling or scraping daemon.

2. **Does not require model inference for entity resolution.** The deterministic pipeline handles resolution without LLM calls. Model-assisted resolution is an optional enhancement for the review queue, gated behind the model router which does not yet exist.

3. **Does not replace the classified memory system.** Entities are classified memories with additional metadata. All existing memory operations (query expansion, temporal decay, access tracking, deduplication, related linking) apply to entity memories unchanged.

4. **Does not build a separate database.** Entities live in the existing FAISS index. Relationships live in a JSONL file. No PostgreSQL, no Neo4j, no graph database. The "graph" is a flat file traversed by Python. This keeps the dependency footprint at zero.

5. **Does not modify Agent-Zero core files.** All new code is extensions, tools, and data files. No changes to `agent.py`, `memory.py`, or the extension loader.

6. **Does not perform real-time streaming ingestion.** Sources are ingested in batch when the agent executes ingestion tools. No WebSocket feeds, no change-data-capture, no real-time event streams. This is a deliberate scope limit — streaming is a Scale-phase capability.

7. **Does not enforce access control on ontology data.** Palantir Foundry's fourth pillar is security — granular access controls on ontology objects. This is a single-user system on local hardware. Access control is out of scope.

8. **Does not provide visualization.** The ontology produces structured data. Visualization (graph rendering, timeline displays, map overlays) is a separate UI concern. The data format is designed to be visualizable, but the layer does not include a UI component.

9. **Does not auto-initiate investigations.** The agent executes investigations when directed by the user. No autonomous "discover interesting connections" daemon. The user aims the system; the system follows.

10. **Does not depend on the model router.** All components function without model routing. The router is an enhancement that enables model-assisted resolution of ambiguous entities. Without it, ambiguous cases go to the review queue.

---

## 11. Further Reading

- **"Knowledge Graph Construction from Heterogeneous Data Sources"** (various, survey literature) — Broader context for building knowledge graphs from diverse sources. Exocortex takes the entity-resolution-first approach rather than the NLP-extraction-first approach common in academic KG construction.

- **Palantir Gotham** (Palantir Technologies) — The intelligence-focused precursor to Foundry. Relevant for understanding the entity-centric investigation pattern that OpenPlanter replicates. Gotham's architecture is not public but the operational pattern (ingest → resolve → connect → analyze) is well-documented in case studies.

- **spaCy NER / Presidio** — Named entity recognition tools that could enhance the html_connector's entity extraction from unstructured text. Currently using regex + heuristic; NER would improve extraction quality at the cost of adding a model dependency. Relevant if the agent connector needs to extract entities from conversational text.

- **"Scaling Entity Resolution with MapReduce"** (Kolb et al., 2012) — Foundational work on blocking strategies for large-scale entity resolution. Our blocking implementation (identifier, name prefix, phonetic) draws from this lineage. Relevant if the ontology grows beyond 10K entities and blocking efficiency matters.

- **Neo4j / NetworkX** — Graph database and Python graph library respectively. The current design uses flat JSONL for relationships to keep dependencies at zero. If graph traversal becomes a bottleneck (>50K relationships, multi-hop queries), migrating to NetworkX in-memory or Neo4j as a sidecar service would be the scaling path.
