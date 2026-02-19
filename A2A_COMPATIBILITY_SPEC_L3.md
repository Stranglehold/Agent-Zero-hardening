# A2A Compatibility Layer — Build Specification (Level 3)
## Organization Kernel · Phase 4: Agent-to-Agent Protocol

**Implementation note:** This spec defines intent, integration contracts, and behavioral
requirements. The implementing agent reads the Agent-Zero source, the A2A protocol
specification, and makes all implementation decisions.

**A2A Reference:** https://a2a-protocol.org/latest/specification/
**A2A Python SDK:** `pip install a2a-python`

---

## Mission

Expose the Organization Kernel as an A2A-compliant agent server. Any A2A client —
regardless of framework, vendor, or implementation — can discover this agent's
capabilities, send it tasks, receive real-time status updates, and collect completed
artifacts. The client does zero additional work beyond speaking standard A2A protocol.

The org kernel, graph workflows, PACE escalation, SALUTE reporting, supervisor loop —
all of it runs invisibly behind a single A2A endpoint. The client sees a capable agent
that accepts work and delivers results. Everything else is internal.

---

## What This Is and Isn't

**This IS:**
- A translation layer between A2A protocol and the org kernel's internal dispatch
- An HTTP server that speaks A2A's JSON-RPC 2.0 on the outside
- A generator that produces A2A Agent Cards from org definitions and role profiles
- A mapper that converts SALUTE reports to A2A task status updates
- A bridge that turns PACE escalations into A2A "input-needed" states

**This is NOT:**
- A modification to the org kernel, graph engine, supervisor, or any existing extension
- A replacement for Agent-Zero's existing web UI or MCP server
- A new agent framework — it's a protocol adapter for the existing architecture

---

## Concepts

### Agent Card
A JSON document published at a well-known URL that describes the agent's capabilities,
supported task types, authentication requirements, and connection information. A2A
clients read this to discover what the agent can do and how to interact with it.

In our implementation, the Agent Card is **generated** from the active organization
definition and its role profiles. The org's mission becomes the agent's description.
The roles' BST domains and graph workflows become the agent's skills. This is not
a static file — it reflects the currently active organization.

### Task
The fundamental unit of work in A2A. A client sends a task, the server works on it,
and delivers results. Tasks have a lifecycle:

| A2A Task State | Org Kernel Equivalent |
|---|---|
| `submitted` | Message received, BST classifying domain |
| `working` | Role activated, graph workflow executing |
| `input-needed` | PACE contingent — agent needs user/client guidance |
| `completed` | Graph workflow reached exit node, results delivered |
| `failed` | PACE emergency or unrecoverable error |
| `canceled` | Client requested cancellation |

### Artifact
The output of a completed task. Files created, code written, analysis produced,
reports generated. In our implementation, artifacts are collected from the agent's
working directory and any files referenced in the SALUTE report's `location.files_modified`.

### Message
Communication between client and server within a task context. Messages have parts
(text, files, structured data). Client messages become user input to the agent.
Server messages are the agent's responses, status updates, and requests for input.

---

## Architecture

```
A2A Client (any framework)
    │
    │  HTTP/JSON-RPC 2.0
    │  SSE for streaming
    ▼
┌─────────────────────────────┐
│  A2A Protocol Server        │  ← New: HTTP endpoint
│  (routes, auth, transport)  │
└─────────┬───────────────────┘
          │
          ▼
┌─────────────────────────────┐
│  A2A Translation Layer      │  ← New: maps A2A ↔ Org Kernel
│  - Task → User Message      │
│  - SALUTE → Task Status     │
│  - PACE → input-needed      │
│  - Files → Artifacts        │
└─────────┬───────────────────┘
          │
          ▼
┌─────────────────────────────┐
│  Organization Kernel        │  ← Existing: unchanged
│  (CO → XO → Specialist)    │
│  Graph Workflows            │
│  PACE / SALUTE / Supervisor │
└─────────────────────────────┘
```

The A2A server runs as a **separate process** alongside Agent-Zero, not inside the
extension system. It communicates with the agent through the same interface that the
web UI uses — submitting messages and reading responses. This keeps the A2A layer
completely decoupled from the agent's internal extension architecture.

---

## Agent Card Generation

### Endpoint
`GET /.well-known/agent.json`

### Generation Logic
The Agent Card is built dynamically from the active organization:

**From Organization Definition:**
- `name` → org_name
- `description` → org description + mission objective
- `url` → server base URL
- `version` → org _version

**From Role Profiles (aggregated):**
- `skills` → one skill entry per unique BST domain across all roles in the org
- Each skill's `id` → the BST domain name
- Each skill's `name` → human-readable domain description
- Each skill's `description` → what the org can do in that domain, derived from
  the roles and graph workflows that handle it

**From Graph Workflow Library:**
- `skills` can also be derived from workflow names — "Bug Fix", "Feature Development",
  "Git Operations", "Docker Deployment", etc.
- These map more naturally to what a client would ask for

**Static fields:**
- `supportedProtocolVersions` → ["0.3"] (or current A2A version)
- `capabilities.streaming` → true (we support SSE for task updates)
- `capabilities.pushNotifications` → false (v1 — add later if needed)
- `defaultInputModes` → ["text"]
- `defaultOutputModes` → ["text"]
- `authentication` → configurable (API key, none for local, OAuth for production)

### Example Generated Agent Card
```json
{
  "name": "Software Development Organization",
  "description": "Full-stack software development agent. Accepts bug reports, feature requests, refactoring tasks, git operations, Docker deployments, API integrations, and infrastructure work. Tasks are routed to specialized roles and executed through verified workflow graphs with automatic escalation on failure.",
  "url": "http://localhost:8200",
  "version": "1.0",
  "supportedProtocolVersions": ["0.3"],
  "capabilities": {
    "streaming": true,
    "pushNotifications": false
  },
  "authentication": {
    "schemes": ["none"]
  },
  "defaultInputModes": ["text"],
  "defaultOutputModes": ["text"],
  "skills": [
    {
      "id": "bugfix",
      "name": "Bug Fix",
      "description": "Diagnose and fix software bugs with automated reproduction, isolation, fix, and regression testing."
    },
    {
      "id": "codegen",
      "name": "Code Generation",
      "description": "Create new code modules from specifications with scaffolding, implementation, testing, and documentation."
    },
    {
      "id": "git_ops",
      "name": "Git Operations",
      "description": "Branch management, feature branches, merges, pull request workflows."
    },
    {
      "id": "docker_ops",
      "name": "Docker Operations",
      "description": "Build, test, and deploy Docker images and containers."
    },
    {
      "id": "refactor",
      "name": "Safe Refactoring",
      "description": "Code refactoring with baseline testing, safe rollback on regression."
    },
    {
      "id": "analysis",
      "name": "Analysis & Research",
      "description": "Data analysis, research, and information synthesis."
    },
    {
      "id": "osint",
      "name": "OSINT & API Integration",
      "description": "Open source intelligence gathering and API integration work."
    }
  ]
}
```

---

## A2A Protocol Methods

The A2A server must implement these JSON-RPC methods:

### `message/send`
Client sends a message (task request) to the server.

**Translation:**
1. Receive the A2A message with task context
2. Extract the text content from message parts
3. Create or retrieve a task ID (map to an internal session/conversation)
4. Submit the text as a user message to the Agent-Zero instance
5. The org kernel processes it: BST classifies → dispatcher routes → graph executes
6. Collect the agent's response
7. Return an A2A response with the task state and any output

**Task State Mapping During Execution:**
- Agent is processing → return `working` with status message
- Agent produced output → return `completed` with artifacts
- PACE reached contingent → return `input-needed` with the PACE reason
- PACE reached emergency or unrecoverable error → return `failed`

### `message/stream`
Same as `message/send` but streams status updates via SSE.

**Translation:**
1. Accept the message and begin processing
2. Open an SSE stream to the client
3. As the agent works, poll SALUTE reports and agent state at regular intervals
4. For each SALUTE update, emit an SSE event with the mapped A2A task status:
   - Include current graph node, progress percentage, role name
   - Format as a human-readable status message in the A2A message parts
5. When the agent completes or fails, emit the final event and close the stream

**SALUTE → SSE Event Mapping:**
```
SALUTE emitted with:
  status.state = "active"
  activity.htn_plan = "bugfix_workflow"  
  activity.htn_step = 3
  activity.current_tool = "code_execution_tool"
  status.progress = 0.6

Becomes SSE event:
  {
    "task": {
      "id": "...",
      "status": {
        "state": "working",
        "message": {
          "role": "agent",
          "parts": [{"text": "Bugfix Workflow: implementing fix (step 3/5, 60% complete)"}]
        }
      }
    }
  }
```

### `tasks/get`
Client checks status of a previously submitted task.

**Translation:**
1. Look up the task ID in the internal task registry
2. Read the latest SALUTE report for the active role
3. Map to A2A task state and return

### `tasks/cancel`
Client requests cancellation of a running task.

**Translation:**
1. Look up the task ID
2. Signal the Agent-Zero instance to stop (if possible via intervention mechanism)
3. Return canceled state

---

## Task Registry

The A2A server maintains a registry mapping A2A task IDs to internal Agent-Zero
sessions. This is an in-memory dictionary with optional persistence to disk.

```
{
  "task_id": {
    "a2a_task_id": "uuid",
    "agent_session": <reference to agent instance or conversation>,
    "created_at": "ISO-8601",
    "last_salute": <latest SALUTE report dict>,
    "state": "working | completed | failed | input-needed | canceled",
    "artifacts": [<list of file paths produced>],
    "messages": [<conversation history for context>]
  }
}
```

### Concurrency
For v1 (microcosm), handle one task at a time. Queue additional tasks and return
`submitted` state until the current task completes. This matches the single-container,
single-model constraint.

For future macrocosm: multiple tasks execute concurrently across containers. The CO
routes via the announce function / A2A discovery. The task registry becomes a shared
coordination layer.

---

## PACE → A2A State Mapping

This is the critical translation that makes the org kernel's failure handling
visible to A2A clients without the client knowing anything about PACE.

| PACE Level | A2A Task State | Client Experience |
|---|---|---|
| Primary | `working` | Agent is executing normally. Status updates stream via SSE. |
| Alternate | `working` | Agent is self-recovering. Client sees status like "retrying with alternative approach." No client action needed. |
| Contingent | `input-needed` | Agent has tried and failed. Needs guidance. Client receives a message explaining what was attempted, what failed, and what kind of input would help. |
| Emergency | `failed` | Agent cannot continue. Client receives a structured failure report: what was accomplished, where it got stuck, partial artifacts if any. |

### Contingent → input-needed Detail
When PACE reaches contingent, the A2A response includes:
- What the agent was trying to do (from SALUTE activity)
- What approaches failed (from graph traversal event log)
- What kind of guidance would help (from the role's PACE contingent description)
- Any partial results produced so far

This is NOT "the agent gave up." It's "the agent is requesting operational guidance"
— exactly what PACE contingent means in military doctrine. The client (or the human
behind the client) provides additional context, and the agent resumes.

### Emergency → failed Detail
When PACE reaches emergency, the A2A response includes:
- A structured failure report with everything accomplished
- Partial artifacts (files created, code written, analysis completed before failure)
- The specific reason for failure
- Suggestions for what a different agent or approach might try

Even in failure, the agent delivers value. This is the "abort and report" doctrine.

---

## Artifact Collection

When a task completes, the A2A layer collects artifacts to return to the client.

**Sources:**
1. SALUTE report's `location.files_modified` — any files the agent created or changed
2. The agent's final response text — the completion message
3. The graph workflow's exit node context — what was verified as complete

**Artifact Format:**
Each file becomes an A2A artifact with:
- `name` → filename
- `parts` → file content as text (for code/text files) or base64 (for binary)
- `metadata.mimeType` → detected from file extension

**Size Limits:**
For v1, include file contents directly in the artifact if under 1MB.
For larger files, include the file path and let the client fetch via a separate
endpoint (future: implement `artifacts/get` method).

---

## Server Configuration

The A2A server runs as a configurable component:

```json
{
  "a2a_server": {
    "enabled": true,
    "host": "0.0.0.0",
    "port": 8200,
    "authentication": {
      "scheme": "none",
      "api_key": null
    },
    "agent_connection": {
      "method": "direct",
      "agent_zero_url": "http://localhost:5000"
    },
    "task_queue": {
      "max_concurrent": 1,
      "max_queued": 10,
      "task_timeout_seconds": 600
    },
    "salute_poll_interval_seconds": 2,
    "org_dir": "/a0/usr/organizations"
  }
}
```

### Port Selection
Use port 8200 by default — distinct from Agent-Zero's web UI port and any
development server ports. Configurable.

### Agent Connection
The A2A server needs to submit messages to Agent-Zero and read responses.
Determine the best integration method by reading Agent-Zero's source:
- If there's an internal API or message queue → use it directly
- If the web UI communicates via WebSocket or HTTP API → use the same interface
- If needed, create a minimal bridge that submits messages and polls for responses

The implementing agent must read Agent-Zero's web server source to determine the
actual communication interface. Do not assume — verify.

---

## Behavioral Requirements

### Startup
- Read the active organization from `/a0/usr/organizations/active.json`
- Generate the Agent Card from the org definition
- Start the HTTP server on the configured port
- Serve the Agent Card at `/.well-known/agent.json`
- Begin accepting A2A JSON-RPC requests

### Agent Card Refresh
- If the active organization changes (different `active.json`), regenerate the card
- For v1, regeneration happens on server restart
- Future: watch the file for changes and regenerate dynamically

### Task Processing
1. Receive `message/send` or `message/stream` request
2. Validate the request against A2A JSON-RPC format
3. Create a task entry in the registry
4. Submit the message text to Agent-Zero
5. Monitor execution via SALUTE reports (poll the reports directory)
6. Map SALUTE state to A2A task state
7. For streaming: emit SSE events on each SALUTE update
8. For non-streaming: wait for completion and return final state
9. On completion: collect artifacts, update registry, return response
10. On failure: collect partial artifacts, return structured failure

### Error Handling
- A2A protocol errors (malformed JSON-RPC) → return JSON-RPC error response
- Agent-Zero connection errors → return A2A `failed` state with connection error detail
- Task timeout → return A2A `failed` state with timeout detail
- All errors must be valid A2A responses — the client should never see raw exceptions

### Logging
- Log all incoming A2A requests (method, task_id, message preview)
- Log all state transitions (submitted → working → completed)
- Log PACE level changes with A2A state mapping
- Use the same logging pattern as Agent-Zero's existing components

---

## Testing Criteria

### Test 1: Agent Card Discovery
- Start the A2A server with an active `software_dev` organization
- `GET http://localhost:8200/.well-known/agent.json`
- Response must be valid JSON matching A2A Agent Card schema
- Skills must reflect the organization's capabilities
- `curl` or any HTTP client should receive the card without authentication

### Test 2: Simple Task Submission
- Send a `message/send` request with a simple task: "List the files in /tmp"
- Response must include a valid task ID and state
- State should transition to `completed` with the file listing as an artifact or message

### Test 3: Task Status Streaming
- Send a `message/stream` request with a multi-step task: "Create a hello world Python script, test it, then clean up"
- SSE stream should emit multiple events showing progress
- Events should include human-readable status messages derived from SALUTE
- Final event should show `completed` state

### Test 4: PACE Contingent → input-needed
- Send a task that will trigger PACE contingent (e.g., "Fix the bug in /nonexistent/critical/app.py")
- After enough failures, the A2A response should show `input-needed` state
- The message should explain what was tried and what guidance is needed
- Send a follow-up message with guidance and verify the task resumes

### Test 5: Task Failure
- Send a task designed to trigger PACE emergency
- Response must show `failed` state
- Must include partial artifacts (if any) and a structured failure explanation
- The client should have enough information to understand what happened

### Test 6: Multiple Task Queuing
- Submit a task while another is running
- Second task should return `submitted` state (queued)
- After first task completes, second task should begin processing

### Test 7: Task Cancellation
- Submit a long-running task
- Send `tasks/cancel` for that task ID
- Task should transition to `canceled` state

### Test 8: Cross-Framework Client
- Use the A2A Python SDK to create a minimal client
- Discover the Agent Card
- Submit a task, monitor via streaming, collect results
- This validates that any standard A2A client works without modification

### Test 9: Agent Card Accuracy
- Verify that every skill listed in the Agent Card maps to a real BST domain
  and graph workflow in the active organization
- Submit a task for each listed skill and verify it routes correctly

---

## File Structure

```
/a0/python/a2a_server/
├── __init__.py
├── server.py              # HTTP server, JSON-RPC routing, SSE streaming
├── agent_card.py          # Agent Card generation from org definitions
├── task_registry.py       # Task lifecycle management
├── translation.py         # SALUTE ↔ A2A state mapping, PACE ↔ A2A state
├── agent_bridge.py        # Communication with Agent-Zero instance
├── config.py              # Server configuration
└── run.py                 # Entry point: python -m a2a_server.run
```

### Startup Command
```bash
python -m a2a_server.run --config /a0/usr/organizations/a2a_config.json
```

Or integrate into Agent-Zero's existing startup so the A2A server launches
alongside the web UI automatically.

---

## Installation

### Dependencies
```bash
pip install a2a-python --break-system-packages
```

If `a2a-python` is not available or doesn't cover server-side needs,
implement the JSON-RPC 2.0 + SSE layer directly using `aiohttp` or
whatever HTTP library Agent-Zero already uses. The A2A protocol is
simple enough that a direct implementation may be cleaner than an SDK
dependency.

### Script: `install_a2a_server.sh`

**Must do:**
1. Install dependencies
2. Create the `/a0/python/a2a_server/` directory and files
3. Create a default `a2a_config.json` in the organizations directory
4. Add a startup entry (systemd service, Docker entrypoint addition, or
   integration into Agent-Zero's existing launch script)

### Docker Integration
If Agent-Zero runs in Docker, the A2A port (8200) needs to be exposed:
```dockerfile
EXPOSE 8200
```

And mapped in docker-compose or run command:
```yaml
ports:
  - "8200:8200"
```

---

## Relationship to Existing Architecture

| Component | Relationship to A2A Layer |
|---|---|
| Organization Kernel | A2A reads org definitions to generate Agent Cards. Org kernel processes tasks internally. No modifications. |
| Graph Workflow Engine | Graph traversal state feeds SALUTE which feeds A2A status updates. No modifications. |
| Supervisor Loop | Continues monitoring internally. PACE changes detected by A2A layer through SALUTE. No modifications. |
| BST | Classifies incoming A2A task messages same as any user message. No modifications. |
| SALUTE Reports | A2A layer polls report files for status updates. Primary bridge between internal state and external visibility. No modifications. |
| Agent-Zero Web UI | Runs independently on its own port. A2A server is a separate interface to the same agent. |
| MCP Server | Continues exposing tools. A2A exposes the agent. Complementary, not competing. |

**Zero modifications to any existing component.** The A2A layer is purely additive.

---

## Future Extensions

### Push Notifications
A2A supports server-initiated push notifications to a client webhook URL.
This would let the A2A server push SALUTE updates to the client instead of
the client polling. Map to: client provides a webhook in the task submission,
server POSTs A2A task status events to the webhook on each SALUTE emission.

### Multi-Task Concurrency (Macrocosm)
When the org kernel supports multiple containers, the A2A server becomes
the CO's external interface. It accepts multiple tasks, routes them through
the org hierarchy to available containers, and aggregates results. The task
registry becomes distributed.

### Agent-to-Agent Chaining
This A2A server can also be an A2A **client** — discovering other A2A agents
and delegating subtasks to them. The CO reads remote Agent Cards, matches
capabilities to task requirements, and sends subtasks via A2A. This is the
distributed compute pooling concept from the org kernel spec, implemented
over a standard protocol instead of custom SSH coordination.

### A2UI Integration
Google's A2UI protocol (announced December 2025) lets remote agents send
UI component blueprints to client applications. Future integration could
let the agent send rich status displays — graph workflow visualizations,
SALUTE dashboard components — to A2UI-compatible clients.

---

## Why This Matters

Without this layer, the org kernel is powerful but isolated. It can only
be used by someone sitting at the Agent-Zero web UI typing messages.

With this layer, the org kernel becomes a service. Any A2A client anywhere
on the network can discover it, send it work, and receive results. The
organizational doctrine, graph workflows, PACE escalation, SALUTE reporting —
all of it executes behind the A2A interface, invisible to the client.

The client sends: "Fix the authentication bug in our login module."
The client receives: streaming status updates as the bugfix specialist works,
a request for guidance if PACE escalates, and completed fixed files as
artifacts on success.

The client doesn't know about BST, PACE, SALUTE, graph nodes, role profiles,
or military doctrine. It doesn't need to. It just gets results from a
capable agent that handles its own complexity internally.

That's the digital agency.
