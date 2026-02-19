"""
Organization Kernel Dispatcher — Agent-Zero Cognitive Architecture
==================================================================
Hook: before_main_llm_call (_12_)

Role-based coordination using military organizational doctrine.
Reads BST domain, selects role from active organization, filters
HTN plans to role capabilities, monitors PACE conditions, emits
SALUTE reports.

Runs after BST (_10_), before HTN (_15_) and context watchdog (_20_).
When no active organization exists, returns immediately — full
backward compatibility with pre-kernel operation.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent import LoopData
from python.helpers.extension import Extension

# ── Constants ────────────────────────────────────────────────────

ORG_DIR = "/a0/usr/organizations"
ACTIVE_ORG_PATH = os.path.join(ORG_DIR, "active.json")
ROLES_DIR = os.path.join(ORG_DIR, "roles")
REPORTS_DIR = os.path.join(ORG_DIR, "reports")
ARCHIVE_DIR = os.path.join(REPORTS_DIR, "archive")

# Agent attribute keys
ACTIVE_ROLE_KEY = "_org_active_role"
ACTIVE_ORG_KEY = "_org_active"
PACE_LEVEL_KEY = "_org_pace_level"
TURN_COUNTER_KEY = "_org_turn_counter"
PREV_ROLE_KEY = "_org_prev_role_id"

# BST integration (verified from _10_belief_state_tracker.py)
BST_STORE_KEY = "_bst_store"
BST_BELIEF_KEY = "__bst_belief_state__"

# HTN integration (verified from _15_htn_plan_selector.py)
HTN_STATE_KEY = "_htn_state"

# Tool fallback integration (verified from _30_tool_fallback_logger.py)
TOOL_FAILURES_KEY = "_tool_failures"

PACE_LEVELS = ["primary", "alternate", "contingent", "emergency"]


class OrgDispatcher(Extension):
    """Organization kernel dispatcher — role selection, PACE monitoring, SALUTE emission."""

    async def execute(self, loop_data: LoopData = LoopData(), **kwargs) -> Any:
        try:
            # Check if an active organization exists
            org = _load_active_org()
            if not org:
                return  # No org — full passthrough, backward compatible

            # Cache org on agent
            self.agent._org_active = org

            # Get BST domain classification
            domain = _get_bst_domain(self.agent)

            # Select role for this domain
            role = _select_role(org, domain)
            if not role:
                # No role for this domain (e.g. conversational) — clear and passthrough
                _clear_role(self.agent)
                return

            prev_role_id = getattr(self.agent, PREV_ROLE_KEY, None)
            current_role_id = role.get("role_id", "")

            # Store active role on agent
            self.agent._org_active_role = role
            setattr(self.agent, PREV_ROLE_KEY, current_role_id)

            # Log role change
            if prev_role_id and prev_role_id != current_role_id:
                self.agent.context.log.log(
                    type="info",
                    content=f"[ORG] Role switch: {prev_role_id} -> {current_role_id} ({role.get('role_name', '')})"
                )
            elif not prev_role_id:
                self.agent.context.log.log(
                    type="info",
                    content=f"[ORG] Role activated: {role.get('role_name', current_role_id)}"
                )

            # Set HTN plan filter
            allowed_plans = role.get("capabilities", {}).get("htn_plans")
            if allowed_plans is not None:
                self.agent.set_data("_org_htn_allowed_plans", allowed_plans)
            else:
                self.agent.set_data("_org_htn_allowed_plans", None)

            # PACE monitoring
            _evaluate_pace(self.agent, role)

            # SALUTE emission
            turn_counter = getattr(self.agent, TURN_COUNTER_KEY, 0) + 1
            setattr(self.agent, TURN_COUNTER_KEY, turn_counter)

            salute_interval = role.get("doctrine", {}).get("salute_interval_turns", 5)
            if turn_counter % salute_interval == 0:
                _emit_salute(self.agent, role, org, loop_data)

        except Exception as e:
            try:
                self.agent.context.log.log(
                    type="warning",
                    content=f"[ORG] Error (passthrough): {e}"
                )
            except Exception:
                pass


# ── Organization Loading ─────────────────────────────────────────

_org_cache = None
_org_cache_mtime = 0

def _load_active_org() -> dict | None:
    """Load active.json, with mtime-based caching."""
    global _org_cache, _org_cache_mtime
    try:
        if not os.path.isfile(ACTIVE_ORG_PATH):
            _org_cache = None
            return None

        mtime = os.path.getmtime(ACTIVE_ORG_PATH)
        if _org_cache is not None and mtime == _org_cache_mtime:
            return _org_cache

        with open(ACTIVE_ORG_PATH, "r", encoding="utf-8") as f:
            _org_cache = json.load(f)
        _org_cache_mtime = mtime
        return _org_cache
    except Exception:
        return None


def _load_role_profile(role_id: str) -> dict | None:
    """Load a role profile from the roles directory."""
    try:
        path = os.path.join(ROLES_DIR, f"{role_id}.json")
        if not os.path.isfile(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


# ── BST Integration ──────────────────────────────────────────────

def _get_bst_domain(agent) -> str:
    try:
        store = getattr(agent, BST_STORE_KEY, {})
        belief = store.get(BST_BELIEF_KEY, {})
        return belief.get("domain", "")
    except Exception:
        return ""


# ── Role Selection ───────────────────────────────────────────────

def _select_role(org: dict, domain: str) -> dict | None:
    """Select the best role for the given BST domain."""
    if not domain or domain == "conversational":
        return None

    hierarchy = org.get("hierarchy", {})
    candidates = []

    for role_id, role_info in hierarchy.items():
        profile = _load_role_profile(role_id)
        if not profile:
            continue

        bst_domains = profile.get("capabilities", {}).get("bst_domains", [])
        if domain in bst_domains:
            candidates.append(profile)

    if not candidates:
        return None

    # Prefer specialists over executives over commanders
    type_priority = {"specialist": 0, "executive": 1, "commander": 2}
    candidates.sort(key=lambda r: type_priority.get(r.get("role_type", ""), 3))
    return candidates[0]


def _clear_role(agent):
    """Clear active role state when no role matches."""
    try:
        if hasattr(agent, ACTIVE_ROLE_KEY):
            agent._org_active_role = None
        agent.set_data("_org_htn_allowed_plans", None)
    except Exception:
        pass


# ── PACE Monitoring ──────────────────────────────────────────────

def _evaluate_pace(agent, role: dict):
    """Evaluate PACE conditions and update level."""
    try:
        current_pace = getattr(agent, PACE_LEVEL_KEY, "primary")
        new_pace = "primary"

        pace_plan = role.get("pace_plan", {})

        # Read tool failure state
        failures = agent.get_data(TOOL_FAILURES_KEY) or {}
        consecutive = failures.get("consecutive", {})
        max_consecutive = max(consecutive.values()) if consecutive else 0

        # Read HTN staleness
        htn_state = getattr(agent, HTN_STATE_KEY, None)
        turns_without_progress = 0
        if htn_state:
            turns_without_progress = htn_state.get("turns_since_progress", 0)

        max_turns = role.get("doctrine", {}).get("max_turns_without_progress", 12)

        # Evaluate emergency first (most severe)
        emergency = pace_plan.get("emergency", {})
        emergency_trigger = emergency.get("trigger", "")
        if ("unrecoverable_error" in emergency_trigger and max_consecutive >= 8) or \
           (turns_without_progress > max_turns * 1.5):
            new_pace = "emergency"

        # Contingent
        elif _check_pace_trigger(pace_plan.get("contingent", {}), max_consecutive, turns_without_progress, agent):
            new_pace = "contingent"

        # Alternate
        elif _check_pace_trigger(pace_plan.get("alternate", {}), max_consecutive, turns_without_progress, agent):
            new_pace = "alternate"

        # Log transitions
        if new_pace != current_pace:
            direction = "escalated" if PACE_LEVELS.index(new_pace) > PACE_LEVELS.index(current_pace) else "restored"
            agent.context.log.log(
                type="warning" if direction == "escalated" else "info",
                content=f"[ORG] PACE {direction}: {current_pace} -> {new_pace}"
            )
            setattr(agent, PACE_LEVEL_KEY, new_pace)

            # Emit immediate SALUTE on state transition
            org = getattr(agent, ACTIVE_ORG_KEY, None)
            if org:
                _emit_salute(agent, role, org, None)
        else:
            setattr(agent, PACE_LEVEL_KEY, new_pace)

    except Exception:
        setattr(agent, PACE_LEVEL_KEY, "primary")


def _check_pace_trigger(pace_entry: dict, max_consecutive: int, turns_no_progress: int, agent) -> bool:
    """Parse and evaluate a PACE trigger condition."""
    trigger = pace_entry.get("trigger", "")
    if not trigger:
        return False

    triggered = False

    # Parse "consecutive_tool_failures >= N"
    if "consecutive_tool_failures" in trigger:
        try:
            parts = trigger.split("consecutive_tool_failures")
            for part in parts:
                part = part.strip().lstrip(">= ").strip()
                if part and part.split()[0].isdigit():
                    threshold = int(part.split()[0])
                    if max_consecutive >= threshold:
                        triggered = True
                    break
        except Exception:
            pass

    # Parse "context_fill > N"
    if "context_fill" in trigger:
        try:
            # Read from context watchdog if available
            ctx_fill = 0.0
            try:
                ctx_window = agent.get_data("ctx_window") or {}
                tokens = ctx_window.get("tokens", 0)
                window_size = agent.get_data("context_window_size") or 100000
                if tokens and window_size:
                    ctx_fill = tokens / window_size
            except Exception:
                pass

            parts = trigger.split("context_fill")
            for part in parts:
                part = part.strip().lstrip("> ").strip()
                if part:
                    try:
                        threshold = float(part.split()[0])
                        if ctx_fill > threshold:
                            triggered = True
                    except ValueError:
                        pass
                    break
        except Exception:
            pass

    # Handle OR conditions
    if " OR " in trigger and not triggered:
        # Check turns_without_progress conditions
        if "turns_without_progress" in trigger:
            try:
                parts = trigger.split("turns_without_progress")
                for part in parts:
                    part = part.strip().lstrip("> ").strip()
                    if part:
                        # Handle "max * 1.5" style
                        if "max" in part:
                            # Use doctrine max
                            pass
                        elif part.split()[0].isdigit():
                            threshold = int(part.split()[0])
                            if turns_no_progress > threshold:
                                triggered = True
                        break
            except Exception:
                pass

    return triggered


# ── SALUTE Report ────────────────────────────────────────────────

def _emit_salute(agent, role: dict, org: dict, loop_data):
    """Build and write a SALUTE report."""
    try:
        role_id = role.get("role_id", "unknown")
        now = datetime.now(timezone.utc)

        # Gather data from available sources
        pace_level = getattr(agent, PACE_LEVEL_KEY, "primary")

        # HTN state
        htn_state = getattr(agent, HTN_STATE_KEY, None)
        htn_plan = ""
        htn_step = 0
        htn_total = 0
        turns_since_progress = 0
        progress = 0.0
        if htn_state:
            htn_plan = htn_state.get("plan_name", "")
            htn_step = htn_state.get("current_step", 0)
            htn_total = htn_state.get("total_steps", 0)
            turns_since_progress = htn_state.get("turns_since_progress", 0)
            if htn_total > 0:
                progress = len(htn_state.get("steps_completed", [])) / htn_total

        # BST domain
        bst_domain = _get_bst_domain(agent)

        # Tool failures
        failures = agent.get_data(TOOL_FAILURES_KEY) or {}
        consecutive = failures.get("consecutive", {})
        max_consecutive = max(consecutive.values()) if consecutive else 0
        total_failures = len(failures.get("history", []))

        # Context info
        ctx_tokens = 0
        ctx_max = 0
        ctx_fill = 0.0
        if loop_data:
            ctx_tokens = loop_data.params_temporary.get("context_token_count", 0)
            ctx_fill = loop_data.params_temporary.get("context_utilization", 0.0)
        try:
            ctx_max = agent.get_data("context_window_size") or 100000
        except Exception:
            ctx_max = 100000

        # Health
        if pace_level in ("contingent", "emergency"):
            health = "critical"
        elif pace_level == "alternate" or max_consecutive >= 2:
            health = "degraded"
        else:
            health = "nominal"

        # State
        if not htn_state and not bst_domain:
            state = "idle"
        elif pace_level == "emergency":
            state = "aborted"
        elif pace_level == "contingent":
            state = "escalating"
        elif pace_level == "alternate":
            state = "error_recovery"
        elif htn_state:
            state = "active"
        else:
            state = "active"

        salute = {
            "_schema": "orgkernel:salute_report",
            "_version": "1.0",
            "status": {
                "state": state,
                "progress": round(progress, 2),
                "pace_level": pace_level,
                "health": health,
            },
            "activity": {
                "current_task": htn_plan or bst_domain or "idle",
                "bst_domain": bst_domain,
                "htn_plan": htn_plan,
                "htn_step": htn_step,
                "htn_total_steps": htn_total,
                "current_tool": "",
                "iterations_on_current_step": turns_since_progress,
            },
            "location": {
                "working_directory": "",
                "files_modified": [],
                "files_read": [],
                "resources_claimed": [],
            },
            "unit": {
                "role_id": role_id,
                "role_name": role.get("role_name", ""),
                "agent_number": getattr(agent, "number", 0),
                "reports_to": role.get("chain_of_command", {}).get("reports_to", ""),
                "organization": org.get("org_id", ""),
            },
            "time": {
                "timestamp": now.isoformat(),
                "task_started": None,
                "elapsed_seconds": 0,
                "turns_elapsed": getattr(agent, TURN_COUNTER_KEY, 0),
                "turns_since_progress": turns_since_progress,
                "context_turns_remaining": None,
            },
            "environment": {
                "model": "",
                "context_fill_pct": round(ctx_fill, 3),
                "context_tokens_used": ctx_tokens,
                "context_tokens_max": ctx_max,
                "gpu_available": True,
                "tool_failures_consecutive": max_consecutive,
                "tool_failures_total": total_failures,
                "memory_fragments_stored": 0,
            },
        }

        # Memory classification health (from Layer 7)
        try:
            mem_health = getattr(agent, "_memory_health", None)
            if mem_health:
                salute["environment"]["memory_health"] = mem_health
                salute["environment"]["memory_fragments_stored"] = (
                    mem_health.get("total_memories", 0)
                )
        except Exception:
            pass

        # Try to get model name
        try:
            salute["environment"]["model"] = str(getattr(agent.config, "chat_model", ""))
        except Exception:
            pass

        # Write to disk
        _write_salute(role_id, salute)

    except Exception:
        pass


def _write_salute(role_id: str, salute: dict):
    """Write SALUTE report to latest and archive."""
    try:
        os.makedirs(REPORTS_DIR, exist_ok=True)
        os.makedirs(ARCHIVE_DIR, exist_ok=True)

        # Write latest
        latest_path = os.path.join(REPORTS_DIR, f"{role_id}_latest.json")
        with open(latest_path, "w", encoding="utf-8") as f:
            json.dump(salute, f, indent=2)

        # Write archive
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        archive_path = os.path.join(ARCHIVE_DIR, f"{role_id}_{ts}.json")
        with open(archive_path, "w", encoding="utf-8") as f:
            json.dump(salute, f, indent=2)

    except Exception:
        pass
