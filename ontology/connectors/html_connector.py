"""
HTML Connector — Agent-Zero Ontology Layer
==========================================
Extracts entity candidates from HTML or plain text using regex + heuristic
detection for names, dates, dollar amounts, and addresses.

Stdlib only: re, html, json, os, datetime.
"""

import html
import json
import os
import re
from datetime import datetime, timezone

ONTOLOGY_DIR = "/a0/usr/ontology"
INGESTION_QUEUE = os.path.join(ONTOLOGY_DIR, "ingestion_queue.jsonl")

# ── Regex patterns ────────────────────────────────────────────────────────────

# Capitalized multi-word sequences (candidate person/org names)
_PROPER_NOUN = re.compile(
    r'\b([A-Z][a-z]{1,20}(?:\s+(?:of|the|and|&|,)?\s*[A-Z][a-z]{1,20}){0,5})\b'
)

# Organization suffixes
_ORG_SUFFIXES = re.compile(
    r'\b(?:Inc|LLC|Corp|Corporation|Ltd|Limited|Co|Company|Group|Holdings|'
    r'Foundation|Association|Institute|Agency|Bureau|Department|Authority|'
    r'Trust|Fund|Partners|LLP|PLC|GmbH|SA|BV)\b\.?',
    re.IGNORECASE
)

# Date patterns
_DATE_PATTERNS = [
    re.compile(r'\b(\d{1,2})[/\-](\d{1,2})[/\-](\d{2,4})\b'),
    re.compile(r'\b(January|February|March|April|May|June|July|August|September|'
               r'October|November|December)\s+(\d{1,2}),?\s+(\d{4})\b', re.I),
    re.compile(r'\b(\d{4})[/\-](\d{2})[/\-](\d{2})\b'),
]

# Dollar/currency amounts
_AMOUNT = re.compile(
    r'\$\s*(\d{1,3}(?:,\d{3})*(?:\.\d{2})?(?:\s*[BKMG]illion|\s*[MBK])?)'
    r'|\b(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)\s*(?:USD|dollars?)\b',
    re.I
)

# Address pattern: number + word(s) + street type
_ADDRESS = re.compile(
    r'\b(\d{1,6}\s+[A-Z][a-zA-Z\s]{2,30}(?:Street|Avenue|Boulevard|Drive|Lane|'
    r'Road|Way|Court|Place|Circle|Parkway|St|Ave|Blvd|Dr|Ln|Rd)(?:\s*,\s*[A-Z][a-zA-Z\s]+)?)\b',
    re.I
)

# HTML tag removal
_HTML_TAG = re.compile(r'<[^>]+>')
_WHITESPACE = re.compile(r'\s+')

# Common words to exclude from proper noun detection
_COMMON_WORDS = {
    'The', 'This', 'That', 'These', 'Those', 'An', 'A', 'In', 'On', 'At',
    'By', 'For', 'With', 'From', 'To', 'Of', 'As', 'Or', 'And', 'But',
    'Not', 'No', 'It', 'Its', 'Be', 'Is', 'Are', 'Was', 'Were', 'Has',
    'Have', 'Had', 'Do', 'Does', 'Did', 'Will', 'Would', 'Could', 'Should',
    'May', 'Might', 'Can', 'January', 'February', 'March', 'April', 'May',
    'June', 'July', 'August', 'September', 'October', 'November', 'December',
    'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday',
}


def ingest_html(
    content: str,
    source_id: str,
    source_url: str = "",
    is_html: bool = True,
    min_name_length: int = 4,
    max_candidates: int = 200,
) -> dict:
    """Extract entity candidates from HTML or plain text.

    Returns: {"candidates": [...], "stats": {...}}
    """
    print(f"[ONT-INGEST] html_connector: extracting from source_id={source_id}", flush=True)

    # Strip HTML if needed
    text = _strip_html(content) if is_html else content

    # Extract entities by type
    names = _extract_names(text, min_name_length)
    dates = _extract_dates(text)
    amounts = _extract_amounts(text)
    addresses = _extract_addresses(text)

    print(
        f"[ONT-INGEST] Found: {len(names)} names, {len(dates)} dates, "
        f"{len(amounts)} amounts, {len(addresses)} addresses",
        flush=True,
    )

    candidates = []
    now = datetime.now(timezone.utc).isoformat()

    # Build person/organization candidates from names
    for i, (name, is_org) in enumerate(names[:max_candidates]):
        entity_type = "organization" if is_org else "person"
        props = {"name": name}

        # Associate nearby addresses if any
        if addresses:
            props["address"] = addresses[0]

        # Mark dates for context
        if dates:
            props["date"] = dates[0]

        candidates.append({
            "entity_type": entity_type,
            "properties": props,
            "relationships": [],
            "provenance": {
                "source_id": source_id,
                "source_type": "html_scrape",
                "record_id": f"name_{i}",
                "source_url": source_url,
                "ingested_at": now,
                "confidence": 0.6,  # Lower confidence for heuristic extraction
            },
        })

    # Build location candidates from addresses
    for i, addr in enumerate(addresses[:20]):
        candidates.append({
            "entity_type": "location",
            "properties": {"name": addr, "address": addr},
            "relationships": [],
            "provenance": {
                "source_id": source_id,
                "source_type": "html_scrape",
                "record_id": f"addr_{i}",
                "source_url": source_url,
                "ingested_at": now,
                "confidence": 0.5,
            },
        })

    # Build financial instrument candidates from amounts (if named nearby)
    for i, amount in enumerate(amounts[:10]):
        # Only create if we have enough context
        candidates.append({
            "entity_type": "financial_instrument",
            "properties": {"name": f"amount_{amount}", "value": amount},
            "relationships": [],
            "provenance": {
                "source_id": source_id,
                "source_type": "html_scrape",
                "record_id": f"amount_{i}",
                "source_url": source_url,
                "ingested_at": now,
                "confidence": 0.4,
            },
        })

    print(f"[ONT-INGEST] HTML result: {len(candidates)} candidates", flush=True)

    if candidates:
        _append_to_queue(candidates)

    return {
        "candidates": candidates,
        "stats": {
            "names": len(names),
            "dates": len(dates),
            "amounts": len(amounts),
            "addresses": len(addresses),
        },
    }


def _strip_html(content: str) -> str:
    """Remove HTML tags, decode entities, normalize whitespace."""
    text = _HTML_TAG.sub(' ', content)
    text = html.unescape(text)
    return _WHITESPACE.sub(' ', text).strip()


def _extract_names(text: str, min_length: int = 4) -> list:
    """Extract capitalized proper-noun sequences as candidate names.

    Returns list of (name, is_org) tuples.
    """
    seen = set()
    results = []

    for match in _PROPER_NOUN.finditer(text):
        name = match.group(1).strip()

        # Filter too-short or common words
        if len(name) < min_length:
            continue
        if name in _COMMON_WORDS:
            continue
        if name.lower() in ('the company', 'the agency'):
            continue

        # Normalize
        name_lower = name.lower()
        if name_lower in seen:
            continue
        seen.add(name_lower)

        # Determine if organization
        is_org = bool(_ORG_SUFFIXES.search(name))

        results.append((name, is_org))

    return results


def _extract_dates(text: str) -> list:
    """Extract date strings from text."""
    seen = set()
    results = []
    for pattern in _DATE_PATTERNS:
        for match in pattern.finditer(text):
            date_str = match.group(0).strip()
            if date_str not in seen:
                seen.add(date_str)
                results.append(date_str)
    return results


def _extract_amounts(text: str) -> list:
    """Extract dollar amounts from text."""
    seen = set()
    results = []
    for match in _AMOUNT.finditer(text):
        amt = (match.group(1) or match.group(2) or '').strip()
        if amt and amt not in seen:
            seen.add(amt)
            results.append(amt)
    return results


def _extract_addresses(text: str) -> list:
    """Extract street addresses from text."""
    seen = set()
    results = []
    for match in _ADDRESS.finditer(text):
        addr = match.group(1).strip()
        addr_lower = addr.lower()
        if addr_lower not in seen and len(addr) > 10:
            seen.add(addr_lower)
            results.append(addr)
    return results


def _append_to_queue(candidates: list):
    os.makedirs(ONTOLOGY_DIR, exist_ok=True)
    with open(INGESTION_QUEUE, 'a', encoding='utf-8') as f:
        for cand in candidates:
            f.write(json.dumps(cand) + '\n')
