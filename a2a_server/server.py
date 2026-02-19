"""
A2A Protocol Server
===================
HTTP server implementing JSON-RPC 2.0 for A2A protocol.
Serves Agent Cards, handles task submission, streaming, and cancellation.

Routes:
  GET  /.well-known/agent.json       → Agent Card discovery
  GET  /.well-known/a2a/agent-card   → Agent Card discovery (1.0 path)
  POST /                             → JSON-RPC 2.0 endpoint
  GET  /health                       → Health check
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

from aiohttp import web

from .agent_card import generate_agent_card
from .agent_bridge import AgentBridge, AgentBridgeError
from .config import load_config
from .task_registry import (
    TaskRegistry, Task, TaskQueueFullError,
    STATE_SUBMITTED, STATE_WORKING, STATE_INPUT_REQUIRED,
    STATE_COMPLETED, STATE_FAILED, STATE_CANCELED, TERMINAL_STATES,
)
from .translation import (
    salute_to_a2a_state, salute_to_status_message, salute_to_sse_event,
    build_contingent_message, build_failure_report, collect_artifacts,
)

logger = logging.getLogger("a2a_server")

# JSON-RPC error codes
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
TASK_NOT_FOUND = -32001
TASK_NOT_CANCELABLE = -32002
QUEUE_FULL = -32003


def create_app(config: dict) -> web.Application:
    """Create the aiohttp web application."""
    app = web.Application()

    # Store shared state on app
    task_cfg = config.get("task_queue", {})
    app["config"] = config
    bridge = AgentBridge(config)
    app["bridge"] = bridge

    async def _on_task_promoted(task: Task):
        """Execute a promoted task (fired when a queued task becomes active)."""
        await _execute_task(bridge, app["registry"], task)

    app["registry"] = TaskRegistry(
        max_concurrent=task_cfg.get("max_concurrent", 1),
        max_queued=task_cfg.get("max_queued", 10),
        on_task_promoted=_on_task_promoted,
    )
    app["agent_card_cache"] = None
    app["agent_card_cache_time"] = 0

    # Routes
    app.router.add_get("/.well-known/agent.json", handle_agent_card)
    app.router.add_get("/.well-known/a2a/agent-card", handle_agent_card)
    app.router.add_post("/", handle_jsonrpc)
    app.router.add_get("/health", handle_health)

    # Lifecycle
    app.on_shutdown.append(on_shutdown)

    return app


# ── Agent Card ──────────────────────────────────────────────────

async def handle_agent_card(request: web.Request) -> web.Response:
    """Serve the dynamically generated Agent Card."""
    config = request.app["config"]

    # Cache for 30 seconds to avoid re-reading files every request
    now = time.monotonic()
    if request.app["agent_card_cache"] and now - request.app["agent_card_cache_time"] < 30:
        card = request.app["agent_card_cache"]
    else:
        # Determine base URL from request
        scheme = request.headers.get("X-Forwarded-Proto", request.scheme)
        host = request.headers.get("X-Forwarded-Host", request.host)
        base_url = f"{scheme}://{host}"

        card = generate_agent_card(config, base_url)
        request.app["agent_card_cache"] = card
        request.app["agent_card_cache_time"] = now

    return web.json_response(card, headers={
        "Access-Control-Allow-Origin": "*",
        "Cache-Control": "public, max-age=30",
    })


# ── Health Check ────────────────────────────────────────────────

async def handle_health(request: web.Request) -> web.Response:
    """Simple health check endpoint."""
    registry: TaskRegistry = request.app["registry"]
    active_ids = await registry.list_active_task_ids()
    return web.json_response({
        "status": "ok",
        "active_tasks": len(active_ids),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


# ── JSON-RPC Dispatcher ────────────────────────────────────────

async def handle_jsonrpc(request: web.Request) -> web.Response:
    """Dispatch JSON-RPC 2.0 requests."""
    # Auth check
    config = request.app["config"]
    auth_config = config.get("authentication", {})
    if not _check_auth(request, auth_config):
        return web.json_response(
            _jsonrpc_error(None, INVALID_REQUEST, "Unauthorized"),
            status=401,
        )

    # Parse request
    try:
        body = await request.json()
    except Exception:
        return web.json_response(
            _jsonrpc_error(None, PARSE_ERROR, "Invalid JSON"),
            status=400,
        )

    if not isinstance(body, dict):
        return web.json_response(
            _jsonrpc_error(None, INVALID_REQUEST, "Request must be a JSON object"),
            status=400,
        )

    # JSON-RPC 2.0 version validation
    if body.get("jsonrpc") != "2.0":
        return web.json_response(
            _jsonrpc_error(body.get("id"), INVALID_REQUEST,
                           "Missing or invalid jsonrpc version (must be \"2.0\")"),
            status=400,
        )

    req_id = body.get("id")
    method = body.get("method", "")
    params = body.get("params", {})

    logger.info(f"[A2A] {method} (id={req_id})")

    # Dispatch to handler
    handlers = {
        "message/send": handle_message_send,
        "message/stream": handle_message_stream,
        "tasks/get": handle_tasks_get,
        "tasks/cancel": handle_tasks_cancel,
        # PascalCase aliases (A2A 1.0 spec)
        "SendMessage": handle_message_send,
        "SendStreamingMessage": handle_message_stream,
        "GetTask": handle_tasks_get,
        "CancelTask": handle_tasks_cancel,
    }

    handler = handlers.get(method)
    if not handler:
        return web.json_response(
            _jsonrpc_error(req_id, METHOD_NOT_FOUND, f"Unknown method: {method}"),
        )

    try:
        return await handler(request, req_id, params)
    except TaskQueueFullError as e:
        return web.json_response(
            _jsonrpc_error(req_id, QUEUE_FULL, str(e)),
        )
    except AgentBridgeError as e:
        logger.error(f"[A2A] Bridge error: {e}")
        return web.json_response(
            _jsonrpc_error(req_id, INTERNAL_ERROR, f"Agent connection error: {e}"),
        )
    except Exception as e:
        logger.exception(f"[A2A] Internal error handling {method}")
        return web.json_response(
            _jsonrpc_error(req_id, INTERNAL_ERROR, str(e)),
        )


# ── message/send ────────────────────────────────────────────────

async def handle_message_send(
    request: web.Request, req_id: Any, params: dict
) -> web.Response:
    """Handle message/send — submit task or send follow-up to existing task."""
    registry: TaskRegistry = request.app["registry"]
    bridge: AgentBridge = request.app["bridge"]

    # Extract message text
    message_text = _extract_message_text(params)
    if not message_text:
        return web.json_response(
            _jsonrpc_error(req_id, INVALID_PARAMS, "No message text provided"),
        )

    # Check for follow-up to existing task (input-required resume)
    existing_task_id = params.get("taskId") or params.get("task_id")
    if not existing_task_id:
        msg_obj = params.get("message")
        if isinstance(msg_obj, dict):
            existing_task_id = msg_obj.get("contextId")
    if existing_task_id:
        existing = await registry.get_task(existing_task_id)
        if existing and existing.state == STATE_INPUT_REQUIRED:
            return await _handle_followup(request, req_id, existing, message_text, bridge, registry)

    # Create new task
    task = await registry.create_task(message_text)
    logger.info(f"[A2A] Task {task.id} created (state={task.state})")

    # If task is queued (not immediately active), return submitted state
    if task.state == STATE_SUBMITTED:
        return web.json_response(_jsonrpc_result(req_id, task.to_a2a_task()))

    # Execute the task
    try:
        result_text = await bridge.submit_task(task)

        # Read final SALUTE for artifact collection
        salute = bridge.read_latest_salute()
        artifacts = []
        if salute:
            task.last_salute = salute
            artifacts = collect_artifacts(salute)

        await registry.complete_task(task.id, result_text, artifacts)

    except AgentBridgeError as e:
        await registry.fail_task(task.id, str(e))

    return web.json_response(_jsonrpc_result(req_id, task.to_a2a_task()))


async def _handle_followup(
    request: web.Request, req_id: Any, task: Task,
    message_text: str, bridge: AgentBridge, registry: TaskRegistry,
) -> web.Response:
    """Handle follow-up message to resume an input-required task."""
    logger.info(f"[A2A] Follow-up for task {task.id} (was input-required)")

    await registry.resume_task(task.id)
    task.messages.append({
        "role": "user",
        "parts": [{"type": "text", "text": message_text}],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    try:
        result_text = await bridge.submit_followup(task, message_text)

        salute = bridge.read_latest_salute()
        artifacts = []
        if salute:
            task.last_salute = salute
            artifacts = collect_artifacts(salute)

        await registry.complete_task(task.id, result_text, artifacts)

    except AgentBridgeError as e:
        await registry.fail_task(task.id, str(e))

    return web.json_response(_jsonrpc_result(req_id, task.to_a2a_task()))


# ── message/stream ──────────────────────────────────────────────

async def handle_message_stream(
    request: web.Request, req_id: Any, params: dict
) -> web.StreamResponse:
    """Handle message/stream — submit task and stream SSE updates."""
    registry: TaskRegistry = request.app["registry"]
    bridge: AgentBridge = request.app["bridge"]

    # Extract message text
    message_text = _extract_message_text(params)
    if not message_text:
        return web.json_response(
            _jsonrpc_error(req_id, INVALID_PARAMS, "No message text provided"),
        )

    # Create task
    task = await registry.create_task(message_text)
    logger.info(f"[A2A] Task {task.id} streaming (state={task.state})")

    # Set up SSE response
    response = web.StreamResponse(
        status=200,
        reason="OK",
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
            "X-Accel-Buffering": "no",
        },
    )
    await response.prepare(request)

    # Send initial task event
    await _send_sse(response, "task", task.to_a2a_task())

    # If queued, wait for activation
    if task.state == STATE_SUBMITTED:
        await _send_sse(response, "status", {
            "taskId": task.id,
            "contextId": task.context_id,
            "status": {
                "state": STATE_SUBMITTED,
                "message": {"role": "agent", "parts": [{"type": "text", "text": "Task queued, waiting for capacity..."}]},
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        })

    # Run the task in background and stream SALUTE updates
    task_future = asyncio.create_task(
        _execute_task(bridge, registry, task)
    )

    # Stream SALUTE updates while task runs
    poll_interval = bridge.poll_interval
    last_salute_ts = ""

    try:
        while not task_future.done() and task.state not in TERMINAL_STATES:
            await asyncio.sleep(poll_interval)

            salute = bridge.read_latest_salute()
            if not salute:
                continue

            ts = salute.get("time", {}).get("timestamp", "")
            if ts == last_salute_ts:
                continue
            last_salute_ts = ts

            task.last_salute = salute
            pace = salute.get("status", {}).get("pace_level", "primary")
            task.pace_level = pace

            # Emit SSE status update
            event = salute_to_sse_event(task.id, task.context_id, salute)
            await _send_sse(response, "status_update", event.get("status_update", {}))

            # Handle PACE transitions
            if pace == "contingent" and task.state != STATE_INPUT_REQUIRED:
                msg = build_contingent_message(salute)
                await registry.set_input_required(task.id, msg)
                await _send_sse(response, "status_update", {
                    "taskId": task.id,
                    "contextId": task.context_id,
                    "status": {
                        "state": STATE_INPUT_REQUIRED,
                        "message": {"role": "agent", "parts": [{"type": "text", "text": msg}]},
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                })

        # Wait for task to finish
        await task_future

    except asyncio.CancelledError:
        task_future.cancel()
        raise
    except ConnectionResetError:
        # Client disconnected
        task_future.cancel()
        return response

    # Send final event
    await _send_sse(response, "task", task.to_a2a_task())
    await response.write_eof()

    return response


# ── tasks/get ───────────────────────────────────────────────────

async def handle_tasks_get(
    request: web.Request, req_id: Any, params: dict
) -> web.Response:
    """Handle tasks/get — check status of a previously submitted task."""
    registry: TaskRegistry = request.app["registry"]
    bridge: AgentBridge = request.app["bridge"]

    task_id = params.get("id") or params.get("taskId") or params.get("task_id")
    if not task_id:
        return web.json_response(
            _jsonrpc_error(req_id, INVALID_PARAMS, "Missing task ID"),
        )

    task = await registry.get_task(task_id)
    if not task:
        return web.json_response(
            _jsonrpc_error(req_id, TASK_NOT_FOUND, f"Task {task_id} not found"),
        )

    # Refresh SALUTE data if task is still active
    if task.state not in TERMINAL_STATES:
        salute = bridge.read_latest_salute()
        if salute:
            task.last_salute = salute
            task.pace_level = salute.get("status", {}).get("pace_level", "primary")

    return web.json_response(
        _jsonrpc_result(req_id, task.to_a2a_task(include_history=True))
    )


# ── tasks/cancel ────────────────────────────────────────────────

async def handle_tasks_cancel(
    request: web.Request, req_id: Any, params: dict
) -> web.Response:
    """Handle tasks/cancel — cancel a running task."""
    registry: TaskRegistry = request.app["registry"]
    bridge: AgentBridge = request.app["bridge"]

    task_id = params.get("id") or params.get("taskId") or params.get("task_id")
    if not task_id:
        return web.json_response(
            _jsonrpc_error(req_id, INVALID_PARAMS, "Missing task ID"),
        )

    task = await registry.get_task(task_id)
    if not task:
        return web.json_response(
            _jsonrpc_error(req_id, TASK_NOT_FOUND, f"Task {task_id} not found"),
        )

    if task.state in TERMINAL_STATES:
        return web.json_response(
            _jsonrpc_error(req_id, TASK_NOT_CANCELABLE,
                           f"Task {task_id} is already {task.state}"),
        )

    # Try to cancel in Agent-Zero
    await bridge.cancel_agent_task(task)
    cancelled = await registry.cancel_task(task_id)

    if cancelled:
        logger.info(f"[A2A] Task {task_id} canceled")
    else:
        logger.warning(f"[A2A] Task {task_id} cancel failed")

    return web.json_response(
        _jsonrpc_result(req_id, task.to_a2a_task())
    )


# ── Internal Helpers ────────────────────────────────────────────

async def _execute_task(bridge: AgentBridge, registry: TaskRegistry, task: Task):
    """Execute a task via the agent bridge. Runs as a background coroutine."""
    try:
        result_text = await bridge.submit_task(task)

        # Collect artifacts from final SALUTE
        salute = bridge.read_latest_salute()
        artifacts = []
        if salute:
            task.last_salute = salute
            pace = salute.get("status", {}).get("pace_level", "primary")

            # Check if we ended in emergency
            if pace == "emergency":
                report = build_failure_report(salute, result_text)
                artifacts = collect_artifacts(salute)
                await registry.fail_task(task.id, report, artifacts)
                return

            artifacts = collect_artifacts(salute)

        await registry.complete_task(task.id, result_text, artifacts)

    except AgentBridgeError as e:
        await registry.fail_task(task.id, str(e))
    except Exception as e:
        await registry.fail_task(task.id, f"Internal error: {e}")


async def _send_sse(response: web.StreamResponse, event_type: str, data: dict):
    """Send an SSE event."""
    payload = json.dumps(data)
    message = f"event: {event_type}\ndata: {payload}\n\n"
    await response.write(message.encode("utf-8"))


def _extract_message_text(params: dict) -> str:
    """Extract message text from A2A JSON-RPC params."""
    message = params.get("message", {})

    # Standard A2A format: message.parts[].text
    if isinstance(message, dict):
        parts = message.get("parts", [])
        texts = []
        for part in parts:
            if isinstance(part, dict):
                # Support both "text" key and "kind"/"type" variants
                text = part.get("text", "")
                if not text and part.get("kind") == "text":
                    text = part.get("text", "")
                if not text and part.get("type") == "text":
                    text = part.get("text", "")
                if text:
                    texts.append(text)
        if texts:
            return "\n".join(texts)

    # Fallback: direct text field
    if isinstance(message, str):
        return message

    # Fallback: text in params directly
    return params.get("text", "")


def _check_auth(request: web.Request, auth_config: dict) -> bool:
    """Validate request authentication."""
    scheme = auth_config.get("scheme", "none")

    if scheme == "none":
        return True

    expected_key = auth_config.get("api_key", "")
    if not expected_key:
        return True  # No key configured = open access

    # Check multiple auth locations
    # 1. X-API-KEY header
    api_key = request.headers.get("X-API-KEY", "")
    if api_key == expected_key:
        return True

    # 2. Authorization: Bearer <key>
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer ") and auth_header[7:] == expected_key:
        return True

    # 3. Query param api_key
    if request.query.get("api_key", "") == expected_key:
        return True

    return False


def _jsonrpc_result(req_id: Any, result: Any) -> dict:
    """Build a JSON-RPC 2.0 success response."""
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "result": result,
    }


def _jsonrpc_error(req_id: Any, code: int, message: str, data: Any = None) -> dict:
    """Build a JSON-RPC 2.0 error response."""
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": error,
    }


async def on_shutdown(app: web.Application):
    """Clean up on server shutdown."""
    bridge: AgentBridge = app["bridge"]
    await bridge.close()
