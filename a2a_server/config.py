"""
A2A Server Configuration
========================
Loads server configuration from a2a_config.json with sensible defaults.
"""

import json
import os
from pathlib import Path

DEFAULT_CONFIG = {
    "host": "0.0.0.0",
    "port": 8200,
    "authentication": {
        "scheme": "none",
        "api_key": None,
    },
    "agent_connection": {
        "base_url": "http://localhost:5000",
        "api_key": "",
    },
    "task_queue": {
        "max_concurrent": 1,
        "max_queued": 10,
        "task_timeout_seconds": 600,
    },
    "salute_poll_interval_seconds": 2,
    "org_dir": "/a0/usr/organizations",
    "reports_dir": "/a0/usr/organizations/reports",
    "roles_dir": "/a0/usr/organizations/roles",
    "plan_library_path": "/a0/python/extensions/before_main_llm_call/htn_plan_library.json",
}


def load_config(config_path: str | None = None) -> dict:
    """Load config from file, merging with defaults."""
    config = dict(DEFAULT_CONFIG)

    if config_path and os.path.isfile(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                user_config = json.load(f)
            _deep_merge(config, user_config)
        except Exception:
            pass

    # Also try the default location
    if not config_path:
        default_path = os.path.join(config.get("org_dir", ""), "a2a_config.json")
        if os.path.isfile(default_path):
            try:
                with open(default_path, "r", encoding="utf-8") as f:
                    user_config = json.load(f)
                _deep_merge(config, user_config)
            except Exception:
                pass

    return config


def _deep_merge(base: dict, override: dict):
    """Merge override into base in-place, recursing into dicts."""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
