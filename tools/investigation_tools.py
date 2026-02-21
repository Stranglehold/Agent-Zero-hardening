"""
Investigation Tools — Agent-Zero Ontology Layer
================================================
Agent-Zero tools for ontology investigation tasks.

Tools exposed:
  - ontology_search(query, entity_type=None, limit=10)
  - source_ingest(file_path, connector_type, source_id)
  - entity_resolve(source_id=None, max_candidates=100)
  - relationship_query(entity_id, relationship_type=None, hops=1, min_confidence=0.3)
  - investigation_report(investigation_id, depth=2)

All tools follow Agent-Zero's Tool/Response pattern.
"""

import json
import os
import sys
from typing import Any

from python.helpers.tool import Tool, Response

ONTOLOGY_DIR = "/a0/usr/ontology"
CONFIG_PATH = os.path.join(ONTOLOGY_DIR, "ontology_config.json")
INVESTIGATIONS_DIR = os.path.join(ONTOLOGY_DIR, "investigations")


# ════════════════════════════════════════════════════════════════════════════
# Tool 1: ontology_search
# ════════════════════════════════════════════════════════════════════════════

class OntologySearch(Tool):
    """Search ontology entities by semantic query."""

    async def execute(
        self,
        query: str = "",
        entity_type: str = None,
        limit: int = 10,
        threshold: float = 0.3,
        **kwargs,
    ) -> Response:
        print(f"[ONT-INVEST] ontology_search: query={query!r}, type={entity_type}", flush=True)

        if not query:
            return Response(message="Error: query parameter required", break_loop=False)

        try:
            _ensure_ontology_path()
            from ontology_store import search_entities
            docs = await search_entities(
                self.agent, query,
                entity_type=entity_type,
                limit=int(limit),
                threshold=float(threshold),
            )

            if not docs:
                return Response(
                    message=f"No ontology entities found matching: {query}",
                    break_loop=False,
                )

            results = []
            for doc in docs:
                ont = doc.metadata.get('ontology', {}) if hasattr(doc, 'metadata') else {}
                props = ont.get('properties', {})
                entry = {
                    "entity_id": ont.get('entity_id', ''),
                    "entity_type": ont.get('entity_type', 'entity'),
                    "name": props.get('name', ''),
                    "summary": getattr(doc, 'page_content', '')[:200],
                    "sources": len(ont.get('provenance_chain', [])),
                }
                results.append(entry)

            text = f"Found {len(results)} ontology entities:\n\n"
            for r in results:
                text += f"**{r['name']}** ({r['entity_type']}, id: {r['entity_id']})\n"
                text += f"  {r['summary']}\n"
                text += f"  Sources: {r['sources']}\n\n"

            return Response(message=text, break_loop=False)

        except Exception as e:
            return Response(message=f"Ontology search error: {e}", break_loop=False)


# ════════════════════════════════════════════════════════════════════════════
# Tool 2: source_ingest
# ════════════════════════════════════════════════════════════════════════════

class SourceIngest(Tool):
    """Ingest a data file into the ontology via the appropriate connector."""

    async def execute(
        self,
        file_path: str = "",
        connector_type: str = "csv",
        source_id: str = "",
        entity_type: str = None,
        force_reingest: bool = False,
        **kwargs,
    ) -> Response:
        print(
            f"[ONT-INVEST] source_ingest: file={file_path}, type={connector_type}, "
            f"source_id={source_id}",
            flush=True,
        )

        if not file_path or not source_id:
            return Response(
                message="Error: file_path and source_id are required",
                break_loop=False,
            )

        try:
            _ensure_ontology_path()
            connector_type = connector_type.lower().strip()

            if connector_type in ('csv', 'tsv'):
                from connectors.csv_connector import ingest_csv
                result = ingest_csv(
                    file_path, source_id,
                    entity_type=entity_type,
                    force_reingest=force_reingest,
                )
            elif connector_type in ('json', 'jsonl'):
                from connectors.json_connector import ingest_json
                result = ingest_json(
                    file_path, source_id,
                    entity_type=entity_type,
                    force_reingest=force_reingest,
                )
            elif connector_type in ('html', 'text', 'txt'):
                from connectors.html_connector import ingest_html
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                is_html = connector_type == 'html'
                result = ingest_html(content, source_id, is_html=is_html)
            else:
                return Response(
                    message=f"Unknown connector type: {connector_type}. "
                            f"Supported: csv, tsv, json, jsonl, html, text",
                    break_loop=False,
                )

            n_candidates = len(result.get('candidates', []))
            skipped = result.get('skipped', 0)
            errors = result.get('errors', 0)

            text = (
                f"Ingestion complete for source '{source_id}':\n"
                f"  - {n_candidates} new candidates written to queue\n"
                f"  - {skipped} records skipped (already ingested)\n"
                f"  - {errors} records failed extraction\n\n"
                f"Use entity_resolve to run resolution on the queue."
            )

            return Response(message=text, break_loop=False)

        except Exception as e:
            return Response(message=f"Ingestion error: {e}", break_loop=False)


# ════════════════════════════════════════════════════════════════════════════
# Tool 3: entity_resolve
# ════════════════════════════════════════════════════════════════════════════

class EntityResolve(Tool):
    """Run entity resolution on pending candidates in the ingestion queue."""

    async def execute(
        self,
        source_id: str = None,
        max_candidates: int = 100,
        **kwargs,
    ) -> Response:
        print(f"[ONT-INVEST] entity_resolve: source_id={source_id}, max={max_candidates}", flush=True)

        try:
            _ensure_ontology_path()
            from resolution_engine import (
                read_ingestion_queue, resolve_batch, mark_queue_resolved,
                load_resolution_config, _candidate_id,
            )
            from ontology_store import store_entity

            config = load_resolution_config()
            candidates = read_ingestion_queue(limit=int(max_candidates))

            # Filter by source_id if specified
            if source_id:
                candidates = [
                    c for c in candidates
                    if c.get('provenance', {}).get('source_id') == source_id
                ]

            if not candidates:
                return Response(
                    message="No pending candidates in ingestion queue.",
                    break_loop=False,
                )

            result = resolve_batch(candidates, config)
            resolved = result.get('resolved', [])
            distinct = result.get('distinct', [])
            flagged = result.get('flagged', [])

            # Store resolved entities in FAISS
            stored = 0
            for entity in resolved + distinct:
                try:
                    eid = await store_entity(self.agent, entity)
                    if eid:
                        stored += 1
                except Exception as e:
                    print(f"[ONT-INVEST] Store error: {e}", flush=True)

            # Mark processed candidates as resolved
            candidate_ids = {_candidate_id(c) for c in candidates}
            mark_queue_resolved(candidate_ids)

            text = (
                f"Entity resolution complete:\n"
                f"  - {len(candidates)} candidates processed\n"
                f"  - {len(resolved)} entities merged (auto-resolved)\n"
                f"  - {len(distinct)} entities created as distinct\n"
                f"  - {len(flagged)} ambiguous pairs flagged for review\n"
                f"  - {stored} entities stored in ontology\n\n"
            )

            if flagged:
                text += (
                    f"Review queue has {len(flagged)} entries. "
                    f"Use relationship_query to explore ambiguous matches."
                )

            return Response(message=text, break_loop=False)

        except Exception as e:
            return Response(message=f"Resolution error: {e}", break_loop=False)


# ════════════════════════════════════════════════════════════════════════════
# Tool 4: relationship_query
# ════════════════════════════════════════════════════════════════════════════

class RelationshipQuery(Tool):
    """Query relationships for an entity, optionally traversing multiple hops."""

    async def execute(
        self,
        entity_id: str = "",
        entity_name: str = "",
        relationship_type: str = None,
        hops: int = 1,
        min_confidence: float = 0.3,
        **kwargs,
    ) -> Response:
        print(
            f"[ONT-INVEST] relationship_query: entity={entity_id or entity_name}, "
            f"type={relationship_type}, hops={hops}",
            flush=True,
        )

        if not entity_id and not entity_name:
            return Response(
                message="Error: entity_id or entity_name required",
                break_loop=False,
            )

        try:
            _ensure_ontology_path()
            from ontology_store import (
                get_entity_relationships, get_entity_by_id, search_entities,
            )

            # Resolve entity_id from name if needed
            if not entity_id and entity_name:
                docs = await search_entities(self.agent, entity_name, limit=1, threshold=0.5)
                if docs:
                    ont = docs[0].metadata.get('ontology', {})
                    entity_id = ont.get('entity_id', '')

            if not entity_id:
                return Response(
                    message=f"Entity '{entity_name}' not found in ontology.",
                    break_loop=False,
                )

            # Traverse hops
            visited = {entity_id}
            frontier = [entity_id]
            all_rels = []
            hop_labels = {}

            for hop in range(int(hops)):
                next_frontier = []
                for eid in frontier:
                    rels = get_entity_relationships(
                        eid,
                        rel_type=relationship_type,
                        direction="both",
                    )
                    for rel in rels:
                        if rel.get('confidence', 0) < float(min_confidence):
                            continue
                        all_rels.append({**rel, "_hop": hop + 1})
                        for connected_id in (rel.get('from_entity'), rel.get('to_entity')):
                            if connected_id and connected_id not in visited:
                                visited.add(connected_id)
                                next_frontier.append(connected_id)
                frontier = next_frontier
                if not frontier:
                    break

            if not all_rels:
                return Response(
                    message=f"No relationships found for entity {entity_id}.",
                    break_loop=False,
                )

            # Format output
            text = f"Relationships for entity {entity_id}:\n\n"
            for rel in all_rels[:30]:
                from_name = rel.get('from_entity_name', rel.get('from_entity', ''))
                to_name = rel.get('to_entity_name', rel.get('to_entity', ''))
                rel_type = rel.get('type', 'related_to')
                conf = rel.get('confidence', 0)
                hop = rel.get('_hop', 1)
                props = rel.get('properties', {})

                text += (
                    f"  [{hop}-hop] {from_name} --[{rel_type}]--> {to_name}"
                    f" (confidence: {conf:.2f})\n"
                )
                if props.get('role'):
                    text += f"    Role: {props['role']}\n"

            text += f"\nTotal: {len(all_rels)} relationships across {hops} hop(s)\n"
            return Response(message=text, break_loop=False)

        except Exception as e:
            return Response(message=f"Relationship query error: {e}", break_loop=False)


# ════════════════════════════════════════════════════════════════════════════
# Tool 5: investigation_report
# ════════════════════════════════════════════════════════════════════════════

class InvestigationReport(Tool):
    """Generate a findings report for an investigation with evidence chains."""

    async def execute(
        self,
        investigation_id: str = "",
        target_entity: str = "",
        depth: int = 2,
        min_confidence: float = 0.4,
        **kwargs,
    ) -> Response:
        print(
            f"[ONT-INVEST] investigation_report: id={investigation_id}, "
            f"target={target_entity}, depth={depth}",
            flush=True,
        )

        if not investigation_id and not target_entity:
            return Response(
                message="Error: investigation_id or target_entity required",
                break_loop=False,
            )

        try:
            _ensure_ontology_path()
            from ontology_store import search_entities, get_entity_relationships

            # If investigation_id given, load saved investigation
            inv_file = os.path.join(INVESTIGATIONS_DIR, f"{investigation_id}.json")
            if investigation_id and os.path.isfile(inv_file):
                with open(inv_file, 'r', encoding='utf-8') as f:
                    investigation = json.load(f)
                target_entity = investigation.get('target_entity', target_entity)

            # Search for target entity
            target_docs = []
            if target_entity:
                target_docs = await search_entities(
                    self.agent, target_entity, limit=3, threshold=0.4,
                )

            if not target_docs:
                return Response(
                    message=(
                        f"Target entity '{target_entity}' not found in ontology. "
                        f"Run source_ingest and entity_resolve first."
                    ),
                    break_loop=False,
                )

            # Build evidence chain
            findings = []
            for doc in target_docs[:3]:
                ont = doc.metadata.get('ontology', {})
                entity_id = ont.get('entity_id', '')
                entity_name = ont.get('properties', {}).get('name', '')
                provenance = ont.get('provenance_chain', [])

                entity_finding = {
                    "entity": entity_name,
                    "entity_id": entity_id,
                    "entity_type": ont.get('entity_type', 'entity'),
                    "sources": [p.get('source_id', '') for p in provenance],
                    "confidence": min((p.get('confidence', 0.5) for p in provenance), default=0.5),
                    "relationships": [],
                    "evidence_chain": [],
                }

                # Get relationships (multi-hop)
                visited = {entity_id}
                frontier = [entity_id]
                for hop in range(int(depth)):
                    next_frontier = []
                    for eid in frontier:
                        rels = get_entity_relationships(eid, direction="both")
                        for rel in rels:
                            conf = rel.get('confidence', 0)
                            if conf < float(min_confidence):
                                continue
                            entity_finding['relationships'].append(rel)

                            # Build evidence chain entry
                            from_name = rel.get('from_entity_name', rel.get('from_entity', ''))
                            to_name = rel.get('to_entity_name', rel.get('to_entity', ''))
                            rel_type = rel.get('type', 'related_to')
                            prov = rel.get('provenance', {})

                            entity_finding['evidence_chain'].append({
                                "finding": f"{from_name} {rel_type} {to_name}",
                                "confidence": conf,
                                "source": prov.get('source_id', 'unknown'),
                                "hop": hop + 1,
                            })

                            for connected in (rel.get('from_entity'), rel.get('to_entity')):
                                if connected and connected not in visited:
                                    visited.add(connected)
                                    next_frontier.append(connected)

                    frontier = next_frontier
                    if not frontier:
                        break

                findings.append(entity_finding)

            # Format report
            report = _format_report(
                target_entity, findings, investigation_id, depth, min_confidence,
            )

            # Save report to disk
            os.makedirs(INVESTIGATIONS_DIR, exist_ok=True)
            report_id = investigation_id or target_entity.replace(' ', '_').lower()[:30]
            report_file = os.path.join(INVESTIGATIONS_DIR, f"{report_id}_report.json")
            with open(report_file, 'w', encoding='utf-8') as f:
                json.dump({"target": target_entity, "findings": findings, "report": report}, f, indent=2)

            return Response(message=report, break_loop=False)

        except Exception as e:
            return Response(message=f"Report generation error: {e}", break_loop=False)


def _format_report(
    target: str, findings: list, inv_id: str, depth: int, min_conf: float,
) -> str:
    """Format investigation findings as structured text."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')

    lines = [
        f"# Investigation Report",
        f"**Target:** {target}",
        f"**Investigation ID:** {inv_id or 'ad-hoc'}",
        f"**Generated:** {now}",
        f"**Depth:** {depth} hops | **Min Confidence:** {min_conf}",
        "",
    ]

    for finding in findings:
        entity_name = finding['entity']
        entity_type = finding['entity_type']
        sources = finding['sources']
        relationships = finding['relationships']
        evidence = finding['evidence_chain']

        lines.append(f"## {entity_name} ({entity_type})")
        lines.append(f"**Entity ID:** {finding['entity_id']}")
        lines.append(f"**Sources:** {', '.join(sources) if sources else 'unknown'}")
        lines.append(f"**Overall Confidence:** {finding['confidence']:.2f}")
        lines.append("")

        if relationships:
            lines.append(f"### Relationships ({len(relationships)} found)")
            for rel in relationships[:15]:
                from_n = rel.get('from_entity_name', rel.get('from_entity', ''))
                to_n = rel.get('to_entity_name', rel.get('to_entity', ''))
                rel_type = rel.get('type', '')
                conf = rel.get('confidence', 0)
                lines.append(f"- {from_n} --[{rel_type}]--> {to_n} (conf: {conf:.2f})")
            lines.append("")

        if evidence:
            lines.append("### Evidence Chain")
            for e in evidence[:10]:
                chain_conf = e.get('confidence', 0)
                source = e.get('source', 'unknown')
                hop = e.get('hop', 1)
                lines.append(
                    f"- [hop {hop}] {e['finding']} "
                    f"(source: {source}, conf: {chain_conf:.2f})"
                )
            lines.append("")

    if not findings:
        lines.append("No entities found in ontology for this target.")

    return "\n".join(lines)


# ── Utilities ─────────────────────────────────────────────────────────────────

def _ensure_ontology_path():
    """Add ontology directory to sys.path for module imports."""
    ontology_connectors = os.path.join(ONTOLOGY_DIR, "connectors")
    for path in (ONTOLOGY_DIR, ontology_connectors):
        if path not in sys.path:
            sys.path.insert(0, path)
