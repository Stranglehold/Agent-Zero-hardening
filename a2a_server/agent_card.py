"""
Agent Card Generation
=====================
Dynamically generates A2A Agent Cards from the active organization
definition, role profiles, and graph workflow library.
"""

import json
import os
from typing import Any


def generate_agent_card(config: dict, base_url: str | None = None) -> dict:
    """Build an A2A Agent Card from the active organization."""
    org_dir = config.get("org_dir", "/a0/usr/organizations")
    roles_dir = config.get("roles_dir", os.path.join(org_dir, "roles"))
    plan_library_path = config.get("plan_library_path", "")

    # Load active org
    org = _load_active_org(org_dir)
    if not org:
        return _fallback_card(config, base_url)

    # Load role profiles referenced by the org
    roles = _load_org_roles(org, roles_dir)

    # Load plan library for workflow-based skills
    plans = _load_plan_library(plan_library_path)

    # Build the card
    url = base_url or f"http://localhost:{config.get('port', 8200)}"

    card = {
        "name": org.get("org_name", "Agent Zero Organization"),
        "description": _build_description(org, roles),
        "url": url,
        "version": org.get("_version", "1.0"),
        "supportedProtocolVersions": ["0.3"],
        "capabilities": {
            "streaming": True,
            "pushNotifications": False,
        },
        "authentication": _build_auth_section(config),
        "defaultInputModes": ["text"],
        "defaultOutputModes": ["text"],
        "skills": _build_skills(org, roles, plans),
    }

    return card


def _load_active_org(org_dir: str) -> dict | None:
    """Load active.json from the organizations directory."""
    path = os.path.join(org_dir, "active.json")
    try:
        if not os.path.isfile(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _load_org_roles(org: dict, roles_dir: str) -> list[dict]:
    """Load all role profiles referenced in the org hierarchy."""
    roles = []
    hierarchy = org.get("hierarchy", {})
    for role_id in hierarchy:
        path = os.path.join(roles_dir, f"{role_id}.json")
        try:
            if os.path.isfile(path):
                with open(path, "r", encoding="utf-8") as f:
                    roles.append(json.load(f))
        except Exception:
            pass
    return roles


def _load_plan_library(path: str) -> dict:
    """Load the graph workflow library."""
    try:
        if not path or not os.path.isfile(path):
            return {}
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _build_description(org: dict, roles: list[dict]) -> str:
    """Build a human-readable description from org definition."""
    parts = []
    desc = org.get("description", "")
    if desc:
        parts.append(desc)

    # Summarize capabilities from role types
    specialists = [r for r in roles if r.get("role_type") == "specialist"]
    if specialists:
        names = [r.get("role_name", r.get("role_id", "")) for r in specialists]
        parts.append(f"Specialist roles: {', '.join(names)}.")

    parts.append(
        "Tasks are routed to specialized roles and executed through "
        "verified workflow graphs with automatic escalation on failure."
    )

    return " ".join(parts)


def _build_auth_section(config: dict) -> dict:
    """Build the authentication section of the Agent Card."""
    auth_config = config.get("authentication", {})
    scheme = auth_config.get("scheme", "none")

    if scheme == "none":
        return {"schemes": ["none"]}
    elif scheme == "apiKey":
        return {
            "schemes": ["apiKey"],
            "apiKeyLocation": "header",
            "apiKeyName": "X-API-KEY",
        }
    elif scheme == "bearer":
        return {"schemes": ["bearer"]}
    else:
        return {"schemes": [scheme]}


def _build_skills(org: dict, roles: list[dict], plans: dict) -> list[dict]:
    """Build skills list from org roles and graph workflows.

    Strategy: derive skills primarily from graph workflows (more natural
    for what a client would ask for), supplemented by BST domains from
    roles that don't map to a workflow.
    """
    skills = []
    seen_ids = set()

    # 1. Skills from graph workflows
    plan_entries = plans.get("plans", {})
    for plan_id, plan_data in plan_entries.items():
        skill_id = plan_id
        if skill_id in seen_ids:
            continue
        seen_ids.add(skill_id)

        # Determine which domains this plan covers
        domains = plan_data.get("domains", [])
        triggers = plan_data.get("triggers", [])

        skills.append({
            "id": skill_id,
            "name": plan_data.get("name", plan_id.replace("_", " ").title()),
            "description": _plan_description(plan_data, domains, triggers),
        })

    # 2. Skills from BST domains not covered by workflows
    all_workflow_domains = set()
    for plan_data in plan_entries.values():
        all_workflow_domains.update(plan_data.get("domains", []))

    # Collect all BST domains from specialist roles
    all_bst_domains = set()
    domain_roles = {}
    for role in roles:
        bst_domains = role.get("capabilities", {}).get("bst_domains", [])
        for d in bst_domains:
            all_bst_domains.add(d)
            if d not in domain_roles:
                domain_roles[d] = []
            domain_roles[d].append(role.get("role_name", role.get("role_id", "")))

    uncovered = all_bst_domains - all_workflow_domains - {"conversational"}
    for domain in sorted(uncovered):
        if domain in seen_ids:
            continue
        seen_ids.add(domain)
        role_names = domain_roles.get(domain, [])
        skills.append({
            "id": domain,
            "name": domain.replace("_", " ").title(),
            "description": f"Handles {domain.replace('_', ' ')} tasks. "
                           f"Specialist roles: {', '.join(role_names)}."
                           if role_names else
                           f"Handles {domain.replace('_', ' ')} tasks.",
        })

    return skills


def _plan_description(plan_data: dict, domains: list, triggers: list) -> str:
    """Build a description for a workflow-based skill."""
    name = plan_data.get("name", "")

    # Try to extract node names for a summary
    graph = plan_data.get("graph", {})
    nodes = graph.get("nodes", {})
    task_nodes = [
        n.get("name", nid)
        for nid, n in nodes.items()
        if n.get("type") == "task"
    ]

    parts = []
    if task_nodes:
        steps = ", ".join(task_nodes[:5])
        if len(task_nodes) > 5:
            steps += f", and {len(task_nodes) - 5} more steps"
        parts.append(f"Automated workflow: {steps}.")
    else:
        parts.append(f"Executes the {name} workflow.")

    if triggers:
        examples = triggers[:3]
        parts.append(f"Triggers on: {', '.join(examples)}.")

    return " ".join(parts)


def _fallback_card(config: dict, base_url: str | None = None) -> dict:
    """Generate a minimal Agent Card when no org is active."""
    url = base_url or f"http://localhost:{config.get('port', 8200)}"
    return {
        "name": "Agent Zero",
        "description": "General AI assistant with code execution, file management, "
                       "web browsing, and problem solving capabilities.",
        "url": url,
        "version": "1.0",
        "supportedProtocolVersions": ["0.3"],
        "capabilities": {
            "streaming": True,
            "pushNotifications": False,
        },
        "authentication": _build_auth_section(config),
        "defaultInputModes": ["text"],
        "defaultOutputModes": ["text"],
        "skills": [{
            "id": "general_assistance",
            "name": "General AI Assistant",
            "description": "Provides general AI assistance including code execution, "
                           "file management, web browsing, and problem solving.",
        }],
    }
