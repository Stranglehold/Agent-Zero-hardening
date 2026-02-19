"""
Task Registry
=============
Manages A2A task lifecycle. Maps A2A task IDs to internal Agent-Zero
sessions with state tracking, queueing, and concurrency control.
"""

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine

# A2A task states
STATE_SUBMITTED = "submitted"
STATE_WORKING = "working"
STATE_INPUT_REQUIRED = "input-required"
STATE_COMPLETED = "completed"
STATE_FAILED = "failed"
STATE_CANCELED = "canceled"

TERMINAL_STATES = {STATE_COMPLETED, STATE_FAILED, STATE_CANCELED}


class Task:
    """Represents a single A2A task with its lifecycle state."""

    def __init__(self, task_id: str, context_id: str, message_text: str):
        self.id = task_id
        self.context_id = context_id
        self.message_text = message_text
        self.state = STATE_SUBMITTED
        self.created_at = datetime.now(timezone.utc)
        self.updated_at = self.created_at

        # Agent-Zero integration
        self.agent_context_id: str | None = None
        self.last_salute: dict | None = None
        self.pace_level: str = "primary"

        # Results
        self.result_text: str | None = None
        self.artifacts: list[dict] = []
        self.messages: list[dict] = []
        self.error_detail: str | None = None

        # Streaming
        self.status_events: list[dict] = []
        self._waiters: list[asyncio.Event] = []

    def update_state(self, new_state: str, message: str | None = None):
        """Transition task to a new state."""
        self.state = new_state
        self.updated_at = datetime.now(timezone.utc)
        if message:
            self.messages.append({
                "role": "agent",
                "parts": [{"type": "text", "text": message}],
                "timestamp": self.updated_at.isoformat(),
            })
        # Wake up any waiters (SSE streams)
        for waiter in self._waiters:
            waiter.set()

    def add_status_event(self, event: dict):
        """Add a status update event for SSE streaming."""
        self.status_events.append(event)
        self.updated_at = datetime.now(timezone.utc)
        for waiter in self._waiters:
            waiter.set()

    def register_waiter(self) -> asyncio.Event:
        """Register a new waiter for SSE streaming."""
        event = asyncio.Event()
        self._waiters.append(event)
        return event

    def unregister_waiter(self, event: asyncio.Event):
        """Remove a waiter."""
        if event in self._waiters:
            self._waiters.remove(event)

    def to_a2a_task(self, include_history: bool = False) -> dict:
        """Convert to A2A task response format."""
        result = {
            "id": self.id,
            "contextId": self.context_id,
            "status": self._build_status(),
            "artifacts": self.artifacts,
        }
        if include_history and self.messages:
            result["history"] = self.messages
        return result

    def _build_status(self) -> dict:
        """Build A2A TaskStatus object."""
        status: dict[str, Any] = {
            "state": self.state,
            "timestamp": self.updated_at.isoformat(),
        }

        # Attach the most recent agent message
        if self.state == STATE_COMPLETED and self.result_text:
            status["message"] = {
                "role": "agent",
                "parts": [{"type": "text", "text": self.result_text}],
            }
        elif self.state == STATE_FAILED and self.error_detail:
            status["message"] = {
                "role": "agent",
                "parts": [{"type": "text", "text": self.error_detail}],
            }
        elif self.state == STATE_INPUT_REQUIRED and self.messages:
            status["message"] = self.messages[-1]
        elif self.state == STATE_WORKING and self.last_salute:
            status["message"] = {
                "role": "agent",
                "parts": [{"type": "text", "text": _salute_status_text(self.last_salute)}],
            }

        return status


class TaskRegistry:
    """Thread-safe task registry with queueing support."""

    def __init__(self, max_concurrent: int = 1, max_queued: int = 10,
                 on_task_promoted: Callable[["Task"], Coroutine] | None = None):
        self.max_concurrent = max_concurrent
        self.max_queued = max_queued
        self._tasks: dict[str, Task] = {}
        self._queue: list[str] = []  # task IDs waiting to run
        self._active: list[str] = []  # task IDs currently running
        self._lock = asyncio.Lock()
        self._on_task_promoted = on_task_promoted

    async def create_task(self, message_text: str, context_id: str | None = None) -> Task:
        """Create a new task. Returns the task (submitted or queued)."""
        async with self._lock:
            # Check queue capacity
            pending_count = len(self._queue)
            if pending_count >= self.max_queued:
                raise TaskQueueFullError(
                    f"Task queue full ({self.max_queued} tasks queued)"
                )

            task_id = str(uuid.uuid4())
            ctx_id = context_id or str(uuid.uuid4())
            task = Task(task_id, ctx_id, message_text)
            self._tasks[task_id] = task

            if len(self._active) < self.max_concurrent:
                self._active.append(task_id)
                task.update_state(STATE_WORKING)
            else:
                self._queue.append(task_id)
                # state stays SUBMITTED (queued)

            return task

    async def get_task(self, task_id: str) -> Task | None:
        """Retrieve a task by ID."""
        return self._tasks.get(task_id)

    async def complete_task(self, task_id: str, result_text: str, artifacts: list[dict] | None = None):
        """Mark a task as completed and dequeue the next one."""
        async with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            task.result_text = result_text
            task.artifacts = artifacts or []
            task.update_state(STATE_COMPLETED, result_text)

            self._deactivate(task_id)
            await self._promote_next()

    async def fail_task(self, task_id: str, error_detail: str, partial_artifacts: list[dict] | None = None):
        """Mark a task as failed."""
        async with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            task.error_detail = error_detail
            task.artifacts = partial_artifacts or []
            task.update_state(STATE_FAILED, error_detail)

            self._deactivate(task_id)
            await self._promote_next()

    async def cancel_task(self, task_id: str) -> bool:
        """Cancel a task. Returns True if cancelable."""
        async with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return False
            if task.state in TERMINAL_STATES:
                return False

            task.update_state(STATE_CANCELED)

            if task_id in self._queue:
                self._queue.remove(task_id)
            self._deactivate(task_id)
            await self._promote_next()
            return True

    async def set_input_required(self, task_id: str, reason: str):
        """Transition task to input-required state (PACE contingent)."""
        task = self._tasks.get(task_id)
        if task and task.state not in TERMINAL_STATES:
            task.update_state(STATE_INPUT_REQUIRED, reason)

    async def resume_task(self, task_id: str):
        """Resume a task from input-required state."""
        async with self._lock:
            task = self._tasks.get(task_id)
            if task and task.state == STATE_INPUT_REQUIRED:
                task.update_state(STATE_WORKING)

    async def list_active_task_ids(self) -> list[str]:
        """Return IDs of currently active tasks."""
        return list(self._active)

    def _deactivate(self, task_id: str):
        """Remove task from active list."""
        if task_id in self._active:
            self._active.remove(task_id)

    async def _promote_next(self):
        """Promote next queued task to active if capacity allows.

        If an on_task_promoted callback is registered, it is fired for each
        promoted task so the server can begin execution.
        """
        while self._queue and len(self._active) < self.max_concurrent:
            next_id = self._queue.pop(0)
            task = self._tasks.get(next_id)
            if task and task.state == STATE_SUBMITTED:
                self._active.append(next_id)
                task.update_state(STATE_WORKING)
                # Fire execution callback outside the lock
                if self._on_task_promoted and task:
                    asyncio.create_task(self._on_task_promoted(task))


class TaskQueueFullError(Exception):
    pass


def _salute_status_text(salute: dict) -> str:
    """Build a human-readable status string from a SALUTE report."""
    activity = salute.get("activity", {})
    status = salute.get("status", {})

    plan = activity.get("htn_plan", "")
    step = activity.get("htn_step", 0)
    total = activity.get("htn_total_steps", 0)
    progress = status.get("progress", 0)
    state = status.get("state", "active")
    tool = activity.get("current_tool", "")

    parts = []
    if plan:
        plan_name = plan.replace("_", " ").title()
        parts.append(plan_name)
    if step and total:
        parts.append(f"step {step}/{total}")
    if progress:
        parts.append(f"{int(progress * 100)}% complete")
    if tool:
        parts.append(f"using {tool}")
    if state and state not in ("active", "idle"):
        parts.append(f"({state})")

    return ": ".join(parts[:1]) + " (" + ", ".join(parts[1:]) + ")" if len(parts) > 1 else (parts[0] if parts else "Working...")
