"""
Entity Resolution Engine — Agent-Zero Ontology Layer
=====================================================
Deterministic entity resolution pipeline:
  1. Preprocessing: normalize names, addresses, dates, extract identifiers
  2. Blocking: reduce N² comparisons to candidate pairs
  3. Scoring: 5-axis weighted composite (name, identifier, address, date, context)
  4. Threshold decisions: merge (≥0.85), flag (0.60-0.85), distinct (<0.60)
  5. Transitive closure: union-find to consolidate merge chains

No external dependencies. Stdlib only: re, json, difflib, collections, hashlib, datetime, os.

Usage:
    from resolution_engine import resolve_candidates
    results = await resolve_candidates(candidates, agent, config)
"""

import hashlib
import json
import os
import re
from collections import defaultdict
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any

# ── Paths ─────────────────────────────────────────────────────────────────────

ONTOLOGY_DIR = "/a0/usr/ontology"
CONFIG_PATH = os.path.join(ONTOLOGY_DIR, "ontology_config.json")
SCHEMA_PATH = os.path.join(ONTOLOGY_DIR, "ontology_schema.json")
AUDIT_LOG = os.path.join(ONTOLOGY_DIR, "resolution_audit.jsonl")
REVIEW_QUEUE = os.path.join(ONTOLOGY_DIR, "review_queue.jsonl")
INGESTION_QUEUE = os.path.join(ONTOLOGY_DIR, "ingestion_queue.jsonl")

# ── Default config ────────────────────────────────────────────────────────────

DEFAULT_RESOLUTION_CONFIG = {
    "enabled": True,
    "merge_threshold": 0.85,
    "review_threshold": 0.60,
    "scoring_weights": {
        "name": 0.35,
        "identifier": 0.30,
        "address": 0.15,
        "date": 0.10,
        "context": 0.10,
    },
    "blocking_strategies": ["identifier", "name_prefix", "phonetic"],
    "transitive_closure": True,
    "audit_log": AUDIT_LOG,
    "review_queue": REVIEW_QUEUE,
}

# ── Honorifics to strip during name normalization ────────────────────────────

_HONORIFICS = re.compile(
    r'\b(mr|mrs|ms|dr|prof|jr|sr|iii|ii|iv|esq|phd|md|dds|dvm|jd)\b\.?',
    re.IGNORECASE
)

# ── Street abbreviation expansions ────────────────────────────────────────────

_ADDR_REPLACEMENTS = [
    (re.compile(r'\bst\b', re.I), 'street'),
    (re.compile(r'\bave\b', re.I), 'avenue'),
    (re.compile(r'\bblvd\b', re.I), 'boulevard'),
    (re.compile(r'\bdr\b', re.I), 'drive'),
    (re.compile(r'\bln\b', re.I), 'lane'),
    (re.compile(r'\brd\b', re.I), 'road'),
    (re.compile(r'\bcorp\b', re.I), 'corporation'),
    (re.compile(r'\binc\b', re.I), 'incorporated'),
    (re.compile(r'\bllc\b', re.I), 'llc'),
    (re.compile(r'\bco\b', re.I), 'company'),
    (re.compile(r'\bltd\b', re.I), 'limited'),
    (re.compile(r'\bplc\b', re.I), 'plc'),
    (re.compile(r'\bintl\b', re.I), 'international'),
]

# ── Date parsing patterns ─────────────────────────────────────────────────────

_DATE_PATTERNS = [
    (re.compile(r'^(\d{4})-(\d{2})-(\d{2})$'), '%Y-%m-%d'),
    (re.compile(r'^(\d{2})/(\d{2})/(\d{4})$'), None),   # MM/DD/YYYY special
    (re.compile(r'^(\d{2})-(\d{2})-(\d{4})$'), None),   # MM-DD-YYYY special
    (re.compile(r'^(\d{4})$'), None),                     # Year only
]


# ═════════════════════════════════════════════════════════════════════════════
# Stage 1: Preprocessing
# ═════════════════════════════════════════════════════════════════════════════

def normalize_name(name: str) -> str:
    """Lowercase, strip honorifics/suffixes, normalize whitespace."""
    if not name:
        return ""
    name = name.lower().strip()
    name = _HONORIFICS.sub('', name)
    return re.sub(r'\s+', ' ', name).strip()


def canonicalize_address(addr: str) -> str:
    """Expand common abbreviations, lowercase, normalize whitespace."""
    if not addr:
        return ""
    addr = addr.lower().strip()
    for pattern, replacement in _ADDR_REPLACEMENTS:
        addr = pattern.sub(replacement, addr)
    return re.sub(r'\s+', ' ', addr).strip()


def normalize_date(date_str: str) -> str:
    """Parse date to ISO 8601 YYYY-MM-DD. Returns '' on failure."""
    if not date_str:
        return ""
    date_str = str(date_str).strip()

    # Already ISO
    if re.match(r'^\d{4}-\d{2}-\d{2}$', date_str):
        return date_str

    # MM/DD/YYYY
    m = re.match(r'^(\d{1,2})/(\d{1,2})/(\d{4})$', date_str)
    if m:
        return f"{m.group(3)}-{m.group(1).zfill(2)}-{m.group(2).zfill(2)}"

    # MM-DD-YYYY
    m = re.match(r'^(\d{1,2})-(\d{1,2})-(\d{4})$', date_str)
    if m:
        return f"{m.group(3)}-{m.group(1).zfill(2)}-{m.group(2).zfill(2)}"

    # Year only
    m = re.match(r'^(\d{4})$', date_str)
    if m:
        return f"{m.group(1)}-01-01"

    # Try common text formats
    for fmt in ('%B %d, %Y', '%b %d, %Y', '%d %B %Y', '%d %b %Y'):
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.strftime('%Y-%m-%d')
        except ValueError:
            pass

    return ""


def extract_identifiers(properties: dict) -> dict:
    """Extract recognized identifier fields from entity properties.

    Returns dict of {identifier_type: value}.
    """
    identifier_fields = {
        'ein', 'duns', 'ticker', 'lei', 'registration_number',
        'ssn_last4', 'passport', 'npi', 'isin', 'cusip', 'sedol',
        'contract_id', 'fec_id', 'lobbyist_id',
    }
    ids = {}
    for key, val in properties.items():
        k = key.lower()
        if k in identifier_fields and val:
            ids[k] = str(val).strip().lower()
    # Also check nested identifiers dict
    if isinstance(properties.get('identifiers'), dict):
        for key, val in properties['identifiers'].items():
            if val:
                ids[key.lower()] = str(val).strip().lower()
    return ids


def preprocess_candidate(candidate: dict) -> dict:
    """Normalize all fields in a candidate entity. Returns enriched candidate."""
    props = candidate.get('properties', {})
    result = dict(candidate)
    result['_normalized'] = {
        'name': normalize_name(props.get('name', '')),
        'aliases': [normalize_name(a) for a in props.get('aliases', []) if a],
        'address': canonicalize_address(
            props.get('address', '')
            or props.get('location', '')
        ),
        'dates': [
            normalize_date(props.get(k, ''))
            for k in ('date', 'date_of_birth', 'start_date', 'filing_date', 'effective_date')
            if props.get(k)
        ],
        'identifiers': extract_identifiers(props),
    }
    return result


# ═════════════════════════════════════════════════════════════════════════════
# Stage 2: Blocking
# ═════════════════════════════════════════════════════════════════════════════

def _phonetic_key(name: str) -> str:
    """Simple phonetic encoding (first 3 consonants + vowel pattern).

    Uses metaphone-lite: map similar-sounding letters, take first 4 chars.
    Falls back to first-3-chars if name is too short.
    """
    if not name or len(name) < 2:
        return name[:1] if name else ""

    # Metaphone-lite: collapse similar sounds
    s = name.upper()
    s = re.sub(r'[AEIOU]', 'V', s)      # vowels → V
    s = re.sub(r'PH', 'F', s)
    s = re.sub(r'CK', 'K', s)
    s = re.sub(r'SCH', 'S', s)
    s = re.sub(r'([BDFGJKLMNPQRSTVWXYZ])\1+', r'\1', s)  # deduplicate consonants
    s = re.sub(r'[^A-Z]', '', s)
    return s[:4] if len(s) >= 4 else s


def build_blocks(candidates: list) -> dict:
    """Group candidates into comparison blocks to reduce N² pairs.

    Returns dict: block_key → list of candidate indices.
    """
    blocks = defaultdict(list)
    strategies = ['identifier', 'name_prefix', 'phonetic']

    for i, cand in enumerate(candidates):
        norm = cand.get('_normalized', {})
        entity_type = cand.get('entity_type', 'entity')

        # Strategy 1: exact identifier match
        for id_key, id_val in norm.get('identifiers', {}).items():
            if id_val:
                blocks[f"id:{id_key}:{id_val}"].append(i)

        # Strategy 2: name prefix + entity type
        name = norm.get('name', '')
        if name:
            prefix = name[:3]
            blocks[f"np:{entity_type}:{prefix}"].append(i)
            for alias in norm.get('aliases', [])[:3]:
                if alias:
                    blocks[f"np:{entity_type}:{alias[:3]}"].append(i)

        # Strategy 3: phonetic key
        if name:
            phon = _phonetic_key(name)
            if phon:
                blocks[f"ph:{entity_type}:{phon}"].append(i)

    return dict(blocks)


def get_candidate_pairs(candidates: list) -> set:
    """Return set of (i, j) pairs (i < j) that share at least one block."""
    blocks = build_blocks(candidates)
    pairs = set()
    for block_indices in blocks.values():
        if len(block_indices) < 2:
            continue
        for i in range(len(block_indices)):
            for j in range(i + 1, len(block_indices)):
                a, b = block_indices[i], block_indices[j]
                if a != b:
                    pairs.add((min(a, b), max(a, b)))
    return pairs


# ═════════════════════════════════════════════════════════════════════════════
# Stage 3: Scoring
# ═════════════════════════════════════════════════════════════════════════════

def levenshtein_ratio(s1: str, s2: str) -> float:
    """String similarity ratio using SequenceMatcher."""
    if not s1 and not s2:
        return 1.0
    if not s1 or not s2:
        return 0.0
    return SequenceMatcher(None, s1, s2).ratio()


def _name_score(norm_a: dict, norm_b: dict) -> float:
    """Best name match across name + aliases."""
    names_a = [norm_a.get('name', '')] + norm_a.get('aliases', [])
    names_b = [norm_b.get('name', '')] + norm_b.get('aliases', [])
    best = 0.0
    for na in names_a:
        if not na:
            continue
        for nb in names_b:
            if not nb:
                continue
            score = levenshtein_ratio(na, nb)
            if score > best:
                best = score
    return best


def _identifier_score(norm_a: dict, norm_b: dict) -> float:
    """1.0 if any identifier matches exactly, 0.0 otherwise."""
    ids_a = norm_a.get('identifiers', {})
    ids_b = norm_b.get('identifiers', {})
    for key, val_a in ids_a.items():
        if not val_a:
            continue
        val_b = ids_b.get(key, '')
        if val_b and val_a == val_b:
            return 1.0
    return 0.0


def _address_score(norm_a: dict, norm_b: dict) -> float:
    """Token overlap ratio on canonicalized addresses."""
    addr_a = norm_a.get('address', '')
    addr_b = norm_b.get('address', '')
    if not addr_a or not addr_b:
        return 0.0
    tokens_a = set(addr_a.split())
    tokens_b = set(addr_b.split())
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return len(intersection) / len(union)


def _date_score(norm_a: dict, norm_b: dict) -> float:
    """1.0 if dates within 1 day, decaying to 0.0 over 365 days."""
    dates_a = [d for d in norm_a.get('dates', []) if d]
    dates_b = [d for d in norm_b.get('dates', []) if d]
    if not dates_a or not dates_b:
        return 0.0

    best = 0.0
    for da in dates_a:
        for db in dates_b:
            try:
                dt_a = datetime.strptime(da, '%Y-%m-%d')
                dt_b = datetime.strptime(db, '%Y-%m-%d')
                delta = abs((dt_a - dt_b).days)
                score = max(0.0, 1.0 - delta / 365.0)
                if score > best:
                    best = score
            except ValueError:
                pass
    return best


def _context_score(cand_a: dict, cand_b: dict) -> float:
    """Jaccard similarity of associated entity name tokens."""
    def context_tokens(cand):
        tokens = set()
        for rel in cand.get('relationships', []):
            hint = rel.get('target_hint', '')
            if hint:
                tokens.update(normalize_name(hint).split())
        props = cand.get('properties', {})
        for key in ('description', 'type', 'jurisdiction'):
            val = props.get(key, '')
            if val:
                tokens.update(str(val).lower().split())
        return tokens

    ta = context_tokens(cand_a)
    tb = context_tokens(cand_b)
    if not ta or not tb:
        return 0.0
    intersection = ta & tb
    union = ta | tb
    return len(intersection) / len(union)


def compute_composite_score(
    cand_a: dict, cand_b: dict, weights: dict,
) -> tuple:
    """Compute weighted composite score. Returns (score, axis_scores)."""
    norm_a = cand_a.get('_normalized', {})
    norm_b = cand_b.get('_normalized', {})

    axis_scores = {
        'name': _name_score(norm_a, norm_b),
        'identifier': _identifier_score(norm_a, norm_b),
        'address': _address_score(norm_a, norm_b),
        'date': _date_score(norm_a, norm_b),
        'context': _context_score(cand_a, cand_b),
    }

    total_weight = sum(weights.values())
    if total_weight <= 0:
        total_weight = 1.0

    composite = sum(
        weights.get(axis, 0.0) * score
        for axis, score in axis_scores.items()
    ) / total_weight

    return composite, axis_scores


# ═════════════════════════════════════════════════════════════════════════════
# Stage 4: Threshold Decisions
# ═════════════════════════════════════════════════════════════════════════════

def decide_action(
    composite: float, merge_threshold: float, review_threshold: float,
) -> str:
    """Map composite score to resolution decision."""
    if composite >= merge_threshold:
        return "merge"
    if composite >= review_threshold:
        return "flag"
    return "distinct"


def merge_candidates(cand_a: dict, cand_b: dict, score: float) -> dict:
    """Merge two candidates into one resolved entity.

    Higher-confidence source wins for conflicting values.
    Both provenances preserved.
    """
    # Determine winner by confidence
    prov_a = cand_a.get('provenance', {})
    prov_b = cand_b.get('provenance', {})
    conf_a = prov_a.get('confidence', 0.5)
    conf_b = prov_b.get('confidence', 0.5)

    primary, secondary = (cand_a, cand_b) if conf_a >= conf_b else (cand_b, cand_a)

    # Merge properties — primary wins on conflict
    props = dict(secondary.get('properties', {}))
    props.update(primary.get('properties', {}))

    # Merge aliases
    aliases = list(set(
        primary.get('properties', {}).get('aliases', [])
        + secondary.get('properties', {}).get('aliases', [])
        + [primary.get('properties', {}).get('name', '')]
        + [secondary.get('properties', {}).get('name', '')]
    ))
    # Remove the canonical name from aliases, deduplicate
    canonical_name = props.get('name', '')
    aliases = [a for a in aliases if a and a != canonical_name]
    props['aliases'] = list(dict.fromkeys(aliases))

    # Merge relationships
    rels = primary.get('relationships', []) + secondary.get('relationships', [])

    # Merge provenances
    provenance_chain = []
    if prov_a:
        provenance_chain.append(prov_a)
    if prov_b:
        provenance_chain.append(prov_b)

    merged = {
        'entity_type': primary.get('entity_type', 'entity'),
        'properties': props,
        'relationships': rels,
        'provenance': primary.get('provenance', {}),
        'provenance_chain': provenance_chain,
        'merge_history': [{
            'merged_from_a': _candidate_id(cand_a),
            'merged_from_b': _candidate_id(cand_b),
            'score': round(score, 4),
            'timestamp': datetime.now(timezone.utc).isoformat(),
        }],
        '_normalized': primary.get('_normalized', {}),
    }
    return merged


def _candidate_id(cand: dict) -> str:
    """Stable ID for a candidate based on provenance."""
    prov = cand.get('provenance', {})
    key = f"{prov.get('source_id', '')}:{prov.get('record_id', '')}"
    return hashlib.md5(key.encode()).hexdigest()[:12]


# ═════════════════════════════════════════════════════════════════════════════
# Stage 5: Transitive Closure (Union-Find)
# ═════════════════════════════════════════════════════════════════════════════

class UnionFind:
    """Union-find for transitive closure of merge chains."""

    def __init__(self, n: int):
        self.parent = list(range(n))
        self.rank = [0] * n

    def find(self, x: int) -> int:
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])
        return self.parent[x]

    def union(self, x: int, y: int):
        rx, ry = self.find(x), self.find(y)
        if rx == ry:
            return
        if self.rank[rx] < self.rank[ry]:
            rx, ry = ry, rx
        self.parent[ry] = rx
        if self.rank[rx] == self.rank[ry]:
            self.rank[rx] += 1


def apply_transitive_closure(
    candidates: list, merge_pairs: list,
) -> list:
    """Apply union-find to collapse merge chains.

    merge_pairs: list of (i, j) index pairs to merge.
    Returns list of merged candidate groups [[indices]].
    """
    uf = UnionFind(len(candidates))
    for i, j in merge_pairs:
        uf.union(i, j)

    groups = defaultdict(list)
    for i in range(len(candidates)):
        groups[uf.find(i)].append(i)

    return list(groups.values())


# ═════════════════════════════════════════════════════════════════════════════
# Main Resolution Pipeline
# ═════════════════════════════════════════════════════════════════════════════

def resolve_batch(candidates: list, config: dict = None) -> dict:
    """Run full resolution pipeline on a batch of candidates.

    Returns:
        {
          "resolved": [merged_candidate, ...],
          "flagged": [{"pair": (i, j), "score": float, "axes": dict}, ...],
          "distinct": [candidate, ...],
          "merges": [(i, j), ...],
          "audit": [audit_entry, ...],
        }
    """
    print(f"[ONT-RESOLVE] resolve_batch: {len(candidates)} candidates", flush=True)

    if config is None:
        config = load_resolution_config()

    res_config = config.get('entity_resolution', DEFAULT_RESOLUTION_CONFIG)
    merge_threshold = res_config.get('merge_threshold', 0.85)
    review_threshold = res_config.get('review_threshold', 0.60)
    weights = res_config.get('scoring_weights', DEFAULT_RESOLUTION_CONFIG['scoring_weights'])

    if not candidates:
        return {"resolved": [], "flagged": [], "distinct": [], "merges": [], "audit": []}

    # Stage 1: Preprocess all
    preprocessed = [preprocess_candidate(c) for c in candidates]

    # Stage 2: Block
    pairs = get_candidate_pairs(preprocessed)
    print(f"[ONT-RESOLVE] {len(pairs)} candidate pairs after blocking", flush=True)

    # Stage 3 & 4: Score + decide
    merge_pairs = []
    flag_pairs = []
    audit = []

    for i, j in pairs:
        composite, axes = compute_composite_score(preprocessed[i], preprocessed[j], weights)
        action = decide_action(composite, merge_threshold, review_threshold)

        audit_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "candidate_a": _candidate_id(preprocessed[i]),
            "candidate_b": _candidate_id(preprocessed[j]),
            "composite_score": round(composite, 4),
            "axis_scores": {k: round(v, 4) for k, v in axes.items()},
            "action": action,
        }
        audit.append(audit_entry)

        if action == "merge":
            merge_pairs.append((i, j))
        elif action == "flag":
            flag_pairs.append({"pair": (i, j), "score": composite, "axes": axes})

    # Stage 5: Transitive closure
    groups = apply_transitive_closure(preprocessed, merge_pairs)

    # Build resolved entities (merged groups)
    resolved = []
    merged_indices = set()
    for group in groups:
        if len(group) == 1:
            continue  # single = distinct (handled below)
        merged_indices.update(group)

        # Merge all in group sequentially
        merged = preprocessed[group[0]]
        for k in group[1:]:
            pair_score = 0.85  # approximate for transitive members
            merged = merge_candidates(merged, preprocessed[k], pair_score)
        resolved.append(merged)

    # Distinct = never merged
    distinct = [preprocessed[i] for i in range(len(preprocessed)) if i not in merged_indices]

    print(
        f"[ONT-RESOLVE] Result: {len(resolved)} merged, "
        f"{len(flag_pairs)} flagged, {len(distinct)} distinct",
        flush=True,
    )

    # Write audit log
    _append_jsonl(res_config.get('audit_log', AUDIT_LOG), audit)

    # Write review queue
    if flag_pairs:
        review_entries = []
        for fp in flag_pairs:
            i, j = fp['pair']
            review_entries.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "status": "pending",
                "score": round(fp['score'], 4),
                "axes": {k: round(v, 4) for k, v in fp['axes'].items()},
                "candidate_a": _candidate_id(preprocessed[i]),
                "candidate_b": _candidate_id(preprocessed[j]),
                "entity_type": preprocessed[i].get('entity_type', 'entity'),
            })
        _append_jsonl(res_config.get('review_queue', REVIEW_QUEUE), review_entries)

    return {
        "resolved": resolved,
        "flagged": flag_pairs,
        "distinct": distinct,
        "merges": merge_pairs,
        "audit": audit,
    }


# ═════════════════════════════════════════════════════════════════════════════
# Queue Operations
# ═════════════════════════════════════════════════════════════════════════════

def read_ingestion_queue(limit: int = 500) -> list:
    """Read candidates from the ingestion queue JSONL."""
    _ensure_file(INGESTION_QUEUE)
    candidates = []
    try:
        with open(INGESTION_QUEUE, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    cand = json.loads(line)
                    if cand.get('_resolved'):
                        continue  # Skip already-resolved
                    candidates.append(cand)
                    if len(candidates) >= limit:
                        break
                except json.JSONDecodeError:
                    pass
    except OSError:
        pass
    return candidates


def write_to_queue(candidates: list):
    """Append candidates to the ingestion queue."""
    _ensure_dir(ONTOLOGY_DIR)
    _append_jsonl(INGESTION_QUEUE, candidates)


def mark_queue_resolved(candidate_ids: set):
    """Mark candidates in the queue as resolved (in-place rewrite)."""
    if not os.path.isfile(INGESTION_QUEUE):
        return
    lines = []
    try:
        with open(INGESTION_QUEUE, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    cand = json.loads(line)
                    cid = _candidate_id(cand)
                    if cid in candidate_ids:
                        cand['_resolved'] = True
                    lines.append(json.dumps(cand))
                except json.JSONDecodeError:
                    lines.append(line)
    except OSError:
        return
    with open(INGESTION_QUEUE, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')


# ═════════════════════════════════════════════════════════════════════════════
# Config & Utilities
# ═════════════════════════════════════════════════════════════════════════════

def load_resolution_config() -> dict:
    """Load ontology config from disk with defaults."""
    try:
        if os.path.isfile(CONFIG_PATH):
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return {"entity_resolution": DEFAULT_RESOLUTION_CONFIG}


def load_schema() -> dict:
    """Load ontology schema from disk."""
    _ensure_dir(ONTOLOGY_DIR)
    if not os.path.isfile(SCHEMA_PATH):
        _write_default_schema()
    try:
        with open(SCHEMA_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _write_default_schema():
    """Write default schema file if missing."""
    schema_src = os.path.join(os.path.dirname(__file__), 'ontology_schema.json')
    if os.path.isfile(schema_src):
        import shutil
        shutil.copy(schema_src, SCHEMA_PATH)


def _append_jsonl(path: str, entries: list):
    """Append entries to a JSONL file."""
    if not entries:
        return
    _ensure_dir(os.path.dirname(path))
    with open(path, 'a', encoding='utf-8') as f:
        for entry in entries:
            f.write(json.dumps(entry) + '\n')


def _ensure_file(path: str):
    """Create empty file if it doesn't exist."""
    _ensure_dir(os.path.dirname(path))
    if not os.path.exists(path):
        open(path, 'w').close()


def _ensure_dir(path: str):
    """Create directory if it doesn't exist."""
    if path:
        os.makedirs(path, exist_ok=True)
