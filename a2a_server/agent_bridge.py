"""
Agent Bridge
============
Communication bridge between the A2A server and Agent-Zero.

Submits tasks via Agent-Zero's HTTP API (/api_message endpoint)
and monitors execution via SALUTE report files on disk.
"""

import asyncio
import json
import os
import time
from datetime import datetime, timezone
from typing import Any

import aiohttp

from . import translation
from . import task_registry as tr


class AgentBridge:
    """Handles communication with an Agent-Zero instance."""

    def __init__(self, config: dict):
        conn = config.get("agent_connection", {})
        self.base_url = conn.get("base_url", "http://localhost:5000").rstrip("/")
        self.api_key = conn.get("api_key", "")
        self.reports_dir = config.get("reports_dir", "/a0/usr/organizations/reports")
        self.poll_interval = config.get("salute_poll_interval_seconds", 2)
        self.task_timeout = config.get("task_queue", {}).get("task_timeout_seconds", 600)
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def submit_task(self, task: tr.Task) -> str:
        """Submit a message to Agent-Zero and wait for the result.

        Returns the agent's response text.
        Raises on timeout or connection error.
        """
        session = await self._get_session()
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-API-KEY"] = self.api_key

        payload = {
            "text": task.message_text,
            "context": "",  # Let A0 create a new context
        }

        try:
            async with session.post(
                f"{self.base_url}/api_message",
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=self.task_timeout),
            ) as resp:
                if resp.status == 401:
                    raise AgentBridgeError("Authentication failed — check API key")
                if resp.status != 200:
                    text = await resp.text()
                    raise AgentBridgeError(f"Agent-Zero returned HTTP {resp.status}: {text[:200]}")

                data = await resp.json()
                task.agent_context_id = data.get("context", "")
                return data.get("message", "")

        except asyncio.TimeoutError:
            raise AgentBridgeError(f"Task timed out after {self.task_timeout}s")
        except aiohttp.ClientError as e:
            raise AgentBridgeError(f"Connection to Agent-Zero failed: {e}")

    async def submit_followup(self, task: tr.Task, message_text: str) -> str:
        """Send a follow-up message to an existing Agent-Zero context.

        Used to resume input-required tasks with additional guidance.
        Returns the agent's response text.
        """
        if not task.agent_context_id:
            raise AgentBridgeError("No agent context to send follow-up to")

        session = await self._get_session()
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-API-KEY"] = self.api_key

        payload = {
            "text": message_text,
            "context": task.agent_context_id,  # Send to existing context
        }

        try:
            async with session.post(
                f"{self.base_url}/api_message",
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=self.task_timeout),
            ) as resp:
                if resp.status == 401:
                    raise AgentBridgeError("Authentication failed — check API key")
                if resp.status != 200:
                    text = await resp.text()
                    raise AgentBridgeError(f"Agent-Zero returned HTTP {resp.status}: {text[:200]}")

                data = await resp.json()
                return data.get("message", "")

        except asyncio.TimeoutError:
            raise AgentBridgeError(f"Follow-up timed out after {self.task_timeout}s")
        except aiohttp.ClientError as e:
            raise AgentBridgeError(f"Connection to Agent-Zero failed: {e}")

    def read_latest_salute(self, role_id: str | None = None) -> dict | None:
        """Read the latest SALUTE report from disk.

        If role_id is specified, reads that role's report.
        Otherwise, reads the most recently modified report.
        """
        try:
            if not os.path.isdir(self.reports_dir):
                return None

            if role_id:
                path = os.path.join(self.reports_dir, f"{role_id}_latest.json")
                if os.path.isfile(path):
                    with open(path, "r", encoding="utf-8") as f:
                        return json.load(f)
                return None

            # Find the most recent *_latest.json
            latest_path = None
            latest_mtime = 0

            for fname in os.listdir(self.reports_dir):
                if fname.endswith("_latest.json"):
                    fpath = os.path.join(self.reports_dir, fname)
                    mtime = os.path.getmtime(fpath)
                    if mtime > latest_mtime:
                        latest_mtime = mtime
                        latest_path = fpath

            if latest_path:
                with open(latest_path, "r", encoding="utf-8") as f:
                    return json.load(f)

        except Exception:
            pass
        return None

    async def poll_salute_updates(
        self,
        task: tr.Task,
        callback,
    ) -> None:
        """Poll SALUTE reports and call back with updates until task completes.

        Args:
            task: The A2A task being monitored
            callback: async callable(task, salute_dict) for each update
        """
        last_salute_ts = ""
        start_time = time.monotonic()

        while task.state not in tr.TERMINAL_STATES:
            # Timeout guard
            elapsed = time.monotonic() - start_time
            if elapsed > self.task_timeout:
                break

            await asyncio.sleep(self.poll_interval)

            salute = self.read_latest_salute()
            if not salute:
                continue

            # Check if this is a new report
            ts = salute.get("time", {}).get("timestamp", "")
            if ts == last_salute_ts:
                continue
            last_salute_ts = ts

            # Update task with SALUTE data
            task.last_salute = salute

            # Check PACE level
            pace = salute.get("status", {}).get("pace_level", "primary")
            task.pace_level = pace

            await callback(task, salute)

    async def cancel_agent_task(self, task: tr.Task) -> bool:
        """Attempt to cancel a running task in Agent-Zero.

        Uses the intervention mechanism by sending a cancel message.
        """
        if not task.agent_context_id:
            return False

        session = await self._get_session()
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-API-KEY"] = self.api_key

        # Send a cancellation intervention
        try:
            async with session.post(
                f"{self.base_url}/api_message",
                json={
                    "text": "CANCEL: Stop the current task immediately.",
                    "context": task.agent_context_id,
                },
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                return resp.status == 200
        except Exception:
            return False


class AgentBridgeError(Exception):
    """Raised when communication with Agent-Zero fails."""
    pass
