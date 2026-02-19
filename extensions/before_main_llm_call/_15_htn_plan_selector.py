"""
HTN Plan Selector — Agent-Zero Cognitive Architecture
=====================================================
Hook: before_main_llm_call (_15_)

Reads BST domain classification, matches plan templates,
tracks step progress, injects structured plan context.
Runs after BST (_10_), before context watchdog (_20_).

Zero model reasoning. Pure dict lookups and string matching.
"""

import json
from pathlib import Path
from typing import Any

from agent import LoopData
from python.helpers.extension import Extension

PLAN_LIBRARY_PATH = Path(__file__).parent / "htn_plan_library.json"
HTN_STATE_KEY = "_htn_state"
BST_STORE_KEY = "_bst_store"
BST_BELIEF_KEY = "__bst_belief_state__"


class HTNPlanSelector(Extension):
    """Selects and tracks execution of pre-built workflow plans."""

    async def execute(self, loop_data: LoopData = LoopData(), **kwargs) -> Any:
        try:
            library = _load_library(self.agent)
            if not library:
                return

            state = _get_state(self.agent)

            # If we have an active plan, check progress
            if state:
                state = _check_progress(self.agent, state, loop_data)
                if state:  # plan still active
                    _inject_plan_context(loop_data, state, library)
                    return

            # No active plan — try to match one
            domain = _get_bst_domain(self.agent)
            message = _get_user_message(loop_data)
            if not message:
                return

            plan_id, plan = _match_plan(library, domain, message, self.agent)
            if plan_id and plan:
                state = _create_state(self.agent, plan_id, plan)
                _inject_plan_context(loop_data, state, library)
                self.agent.context.log.log(
                    type="info",
                    content=f"[HTN] Plan activated: {plan.get('name', plan_id)} ({len(plan['steps'])} steps)"
                )

        except Exception as e:
            try:
                self.agent.context.log.log(
                    type="warning",
                    content=f"[HTN] Error (passthrough): {e}"
                )
            except Exception:
                pass


# ── Library Loading ──────────────────────────────────────────────

_library_cache = None

def _load_library(agent) -> dict | None:
    global _library_cache
    if _library_cache is not None:
        return _library_cache
    try:
        with open(PLAN_LIBRARY_PATH, "r") as f:
            _library_cache = json.load(f)
        return _library_cache
    except Exception:
        return None


# ── BST Integration ──────────────────────────────────────────────

def _get_bst_domain(agent) -> str:
    """Read BST's domain classification from agent._bst_store."""
    try:
        store = getattr(agent, BST_STORE_KEY, {})
        belief = store.get(BST_BELIEF_KEY, {})
        return belief.get("domain", "")
    except Exception:
        return ""


# ── User Message Extraction ─────────────────────────────────────

def _get_user_message(loop_data: LoopData) -> str:
    """Extract user message text from history."""
    if not loop_data.history_output:
        return ""
    for msg in reversed(loop_data.history_output):
        if not isinstance(msg, dict):
            continue
        if msg.get("ai", True):
            continue
        content = msg.get("content", "")
        if isinstance(content, dict):
            content = content.get("user_message", "") or content.get("message", "")
        return str(content).strip().lower()
    return ""


# ── Plan Matching ────────────────────────────────────────────────

def _match_plan(library: dict, domain: str, message: str, agent=None) -> tuple:
    """Match message against plan library. Returns (plan_id, plan) or (None, None)."""
    plans = library.get("plans", {})
    best_id = None
    best_score = 0

    # Org kernel HTN filter: if set, only allow plans in the active role's capability set
    allowed_plans = None
    if agent:
        try:
            allowed_plans = agent.get_data("_org_htn_allowed_plans")
        except Exception:
            pass

    for plan_id, plan in plans.items():
        # Org filter: skip plans not in the active role's allowed list
        if allowed_plans is not None and plan_id not in allowed_plans:
            continue

        # Domain filter: if plan specifies domains, message domain must match
        plan_domains = plan.get("domains", [])
        domain_match = not plan_domains or domain in plan_domains

        # Trigger matching
        triggers = plan.get("triggers", [])
        threshold = plan.get("trigger_threshold", 2)
        hits = sum(1 for t in triggers if t in message)

        if hits >= threshold and domain_match:
            # Score: hits + domain bonus
            score = hits + (1.0 if domain_match and plan_domains else 0)
            if score > best_score:
                best_score = score
                best_id = plan_id

    if best_id:
        return best_id, plans[best_id]
    return None, None


# ── State Management ─────────────────────────────────────────────

def _get_state(agent) -> dict | None:
    try:
        return getattr(agent, HTN_STATE_KEY, None)
    except Exception:
        return None

def _set_state(agent, state: dict):
    setattr(agent, HTN_STATE_KEY, state)

def _clear_state(agent):
    try:
        if hasattr(agent, HTN_STATE_KEY):
            delattr(agent, HTN_STATE_KEY)
    except Exception:
        pass

def _create_state(agent, plan_id: str, plan: dict) -> dict:
    state = {
        "plan_id": plan_id,
        "plan_name": plan.get("name", plan_id),
        "domain": plan.get("domains", [""])[0] if plan.get("domains") else "",
        "current_step": 0,
        "steps_completed": [],
        "steps_failed": [],
        "total_steps": len(plan.get("steps", [])),
        "stale_after_turns": plan.get("stale_after_turns", 10),
        "turns_since_progress": 0,
        "iteration_started": 0,
    }
    _set_state(agent, state)
    return state


# ── Progress Checking ────────────────────────────────────────────

def _check_progress(agent, state: dict, loop_data: LoopData) -> dict | None:
    """Check if current step is verified, advance if so. Returns updated state or None if plan complete/stale."""

    # Staleness check
    state["turns_since_progress"] = state.get("turns_since_progress", 0) + 1
    stale_limit = state.get("stale_after_turns", 10)
    if state["turns_since_progress"] > stale_limit:
        agent.context.log.log(
            type="info",
            content=f"[HTN] Plan '{state['plan_name']}' expired (no progress for {stale_limit} turns)"
        )
        _clear_state(agent)
        return None

    # Plan complete check
    if state["current_step"] >= state["total_steps"]:
        agent.context.log.log(
            type="info",
            content=f"[HTN] Plan '{state['plan_name']}' completed!"
        )
        _clear_state(agent)
        return None

    # Check last tool output against current step's verification
    library = _load_library(agent)
    if not library:
        return state

    plan = library.get("plans", {}).get(state["plan_id"])
    if not plan:
        _clear_state(agent)
        return None

    current_idx = state["current_step"]
    step = plan["steps"][current_idx]

    # Get last tool output from history
    last_output = _get_last_tool_output(loop_data)

    if last_output is not None:
        verified = _verify_step(step, last_output)
        if verified:
            state["steps_completed"].append(current_idx)
            state["current_step"] = current_idx + 1
            state["turns_since_progress"] = 0
            agent.context.log.log(
                type="info",
                content=f"[HTN] Step {current_idx + 1} verified: {step['name']}"
            )

            # Check if plan is now complete
            if state["current_step"] >= state["total_steps"]:
                agent.context.log.log(
                    type="info",
                    content=f"[HTN] Plan '{state['plan_name']}' completed!"
                )
                _clear_state(agent)
                return None
        else:
            on_fail = step.get("on_fail", "warn")
            if on_fail == "skip":
                state["steps_failed"].append(current_idx)
                state["current_step"] = current_idx + 1
                state["turns_since_progress"] = 0
            elif on_fail == "abort":
                state["steps_failed"].append(current_idx)
                agent.context.log.log(
                    type="warning",
                    content=f"[HTN] Plan aborted: step '{step['name']}' failed verification"
                )
                _clear_state(agent)
                return None
            # "warn" and "block" both keep current_step unchanged

    _set_state(agent, state)
    return state


def _get_last_tool_output(loop_data: LoopData) -> str | None:
    """Extract the most recent tool output from history."""
    if not loop_data.history_output:
        return None
    for msg in reversed(loop_data.history_output):
        if not isinstance(msg, dict):
            continue
        content = msg.get("content", "")
        if isinstance(content, dict):
            if "tool_name" in content:
                return str(content.get("tool_result", content.get("output", content.get("result", ""))))
        if isinstance(content, str) and content.startswith("[tool_result"):
            return content
    return None


# ── Verification ─────────────────────────────────────────────────

def _verify_step(step: dict, output: str) -> bool:
    """Run verification check on tool output."""
    verify = step.get("verify")
    if not verify:
        return True  # No verification = auto-pass

    vtype = verify.get("type", "any_output")
    value = verify.get("value", "")
    output_lower = output.lower()

    if vtype == "output_contains":
        return value.lower() in output_lower
    elif vtype == "output_not_contains":
        return value.lower() not in output_lower
    elif vtype == "exit_code_zero":
        return "error" not in output_lower and "exit code" not in output_lower
    elif vtype == "any_output":
        return bool(output.strip())
    elif vtype == "file_exists":
        return True  # Can't check file system from here; model confirms
    elif vtype == "manual":
        return True  # Model self-reports
    return True


# ── Context Injection ────────────────────────────────────────────

def _inject_plan_context(loop_data: LoopData, state: dict, library: dict):
    """Build and inject the plan context string into extras_temporary."""
    plan = library.get("plans", {}).get(state["plan_id"])
    if not plan:
        return

    lines = [f"[ACTIVE PLAN: {state['plan_name']}]"]

    for i, step in enumerate(plan.get("steps", [])):
        step_num = i + 1
        name = step.get("name", f"Step {step_num}")

        if i in state.get("steps_completed", []):
            lines.append(f"  Step {step_num}/{state['total_steps']}: {name} [DONE]")
        elif i in state.get("steps_failed", []):
            lines.append(f"  Step {step_num}/{state['total_steps']}: {name} [FAILED]")
        elif i == state["current_step"]:
            lines.append(f"  Step {step_num}/{state['total_steps']}: {name} << CURRENT")
            lines.append(f"    Action: {step.get('action', '')}")
            if step.get("tool"):
                lines.append(f"    Tool: {step['tool']}")
            if step.get("tool_hint"):
                lines.append(f"    Hint: {step['tool_hint']}")
            verify = step.get("verify", {})
            if verify.get("type") and verify["type"] != "manual":
                lines.append(f"    Verify: {verify.get('type')}: {verify.get('value', '')}")
        else:
            lines.append(f"  Step {step_num}/{state['total_steps']}: {name} [PENDING]")

    lines.append("")
    lines.append(f"Execute Step {state['current_step'] + 1} now. Do not skip ahead. Verify before proceeding.")

    loop_data.extras_temporary["htn_active_plan"] = "\n".join(lines)
