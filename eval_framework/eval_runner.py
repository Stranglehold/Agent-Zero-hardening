"""
Model Evaluation Framework â€" Agent-Zero Hardening Layer
========================================================
Standalone test harness that profiles any model loaded in LM Studio
against the hardening layers and produces a configuration profile.

v1.1 â€" Added chat_raw() to LMStudioClient for tool format compatibility.
       Backward compatible: existing modules using chat() are unaffected.

Usage:
    python eval_runner.py \
        --api-base http://localhost:1234/v1 \
        --model-name "your-model-name" \
        --output-dir ./profiles \
        --verbose

    python eval_runner.py --modules bst tool_reliability --verbose
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
FIXTURES_DIR = SCRIPT_DIR / "fixtures"
MODULES_DIR = SCRIPT_DIR / "modules"
DEFAULT_CONFIG = SCRIPT_DIR / "config.json"

# ---------------------------------------------------------------------------
# Module registry â€" maps config name â†' (module_file, class_name)
# ---------------------------------------------------------------------------
MODULE_REGISTRY = {
    "bst":                  ("bst_eval",     "BSTEval"),
    "tool_reliability":     ("tool_eval",    "ToolEval"),
    "graph_compliance":     ("graph_eval",   "GraphEval"),
    "pace_calibration":     ("pace_eval",    "PACEEval"),
    "context_sensitivity":  ("context_eval", "ContextEval"),
    "memory_utilization":   ("memory_eval",  "MemoryEval"),
}

# ---------------------------------------------------------------------------
# LM Studio API client
# ---------------------------------------------------------------------------

class LMStudioClient:
    """Minimal OpenAI-compatible chat completion client for LM Studio."""

    def __init__(self, api_base: str, timeout: int = 120):
        import requests  # local import to keep top-level import-free
        self._session = requests.Session()
        self._base = api_base.rstrip("/")
        self._timeout = timeout

    # â€"â€" Core call (returns content string â€" backward compatible) â€"â€"â€"â€"â€"â€"â€"â€"â€"
    def chat(
        self,
        messages: list[dict],
        model: str = "",
        temperature: float = 0.1,
        max_tokens: int = 2048,
    ) -> str:
        """Send a chat completion request and return the assistant text."""
        data = self._send_request(messages, model, temperature, max_tokens)
        return data["choices"][0]["message"]["content"]

    # â€"â€" Raw call (returns full message dict â€" for format adapter) â€"â€"â€"â€"â€"â€"â€"â€"
    def chat_raw(
        self,
        messages: list[dict],
        model: str = "",
        temperature: float = 0.1,
        max_tokens: int = 2048,
    ) -> dict:
        """Send a chat completion request and return the full message dict.

        Returns the complete message object from the API response, including:
        - content: str (always present)
        - tool_calls: list[dict] (if model returned tool calls)
        - reasoning_content: str (if model returned reasoning/thinking)
        - role: str
        """
        data = self._send_request(messages, model, temperature, max_tokens)
        return data["choices"][0]["message"]

    # â€"â€" Internal request method â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"
    def _send_request(
        self,
        messages: list[dict],
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> dict:
        """Send the HTTP request and return parsed response data."""
        import requests

        payload = {
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if model:
            payload["model"] = model

        url = f"{self._base}/chat/completions"
        try:
            resp = self._session.post(url, json=payload, timeout=self._timeout)
            if resp.status_code == 400:
                body = resp.json() if resp.headers.get(
                    "content-type", ""
                ).startswith("application/json") else {}
                err_msg = body.get("error", resp.text[:200])
                raise RuntimeError(
                    f"LM Studio 400 error: {err_msg}. "
                    "Ensure a model is fully loaded in LM Studio."
                )
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.ConnectionError:
            raise RuntimeError(
                f"Cannot connect to LM Studio at {self._base}. "
                "Is LM Studio running with a model loaded?"
            )
        except requests.exceptions.Timeout:
            raise RuntimeError(
                f"LM Studio request timed out after {self._timeout}s."
            )
        except RuntimeError:
            raise
        except (KeyError, IndexError) as exc:
            raise RuntimeError(f"Unexpected API response format: {exc}")

    # â€"â€" Health check â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"
    def check_connection(self) -> dict:
        """Hit /v1/models to verify connectivity and get model info."""
        import requests

        url = f"{self._base}/models"
        try:
            resp = self._session.get(url, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            models = data.get("data", [])
            if models:
                return {"ok": True, "model": models[0].get("id", "unknown")}
            return {"ok": True, "model": "unknown"}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Module loader
# ---------------------------------------------------------------------------

def _load_module(module_key: str):
    """Dynamically import an evaluation module and return its class."""
    if module_key not in MODULE_REGISTRY:
        raise ValueError(f"Unknown module: {module_key}")

    mod_file, cls_name = MODULE_REGISTRY[module_key]

    # Add modules/ to path temporarily
    mod_dir = str(MODULES_DIR)
    if mod_dir not in sys.path:
        sys.path.insert(0, mod_dir)

    mod = __import__(mod_file)
    return getattr(mod, cls_name)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_evaluation(
    api_base: str,
    model_name: str,
    modules: list[str],
    output_dir: str,
    max_retries: int = 2,
    runs_per_test: int = 3,
    timeout: int = 120,
    verbose: bool = False,
) -> dict:
    """Run the full evaluation battery and return aggregated metrics."""

    client = LMStudioClient(api_base, timeout=timeout)

    # Verify connectivity
    health = client.check_connection()
    if not health["ok"]:
        print(f"[ERROR] Cannot connect to LM Studio: {health.get('error')}")
        sys.exit(1)

    detected_model = health.get("model", "unknown")
    effective_model = model_name or detected_model
    print(f"[EVAL] Connected to LM Studio")
    print(f"[EVAL] Detected model: {detected_model}")
    print(f"[EVAL] Profile target: {effective_model}")
    print(f"[EVAL] Modules: {', '.join(modules)}")
    print(f"[EVAL] Runs per test: {runs_per_test}")
    print()

    all_metrics = {}
    total_api_calls = 0
    start_time = time.time()

    for mod_key in modules:
        print(f"[EVAL] --- Running module: {mod_key} ---")
        mod_start = time.time()

        try:
            EvalClass = _load_module(mod_key)
            evaluator = EvalClass(
                client=client,
                model_name=effective_model,
                fixtures_dir=str(FIXTURES_DIR),
                max_retries=max_retries,
                runs_per_test=runs_per_test,
                verbose=verbose,
            )
            metrics, api_calls = evaluator.run()
            all_metrics[mod_key] = metrics
            total_api_calls += api_calls
            elapsed = time.time() - mod_start
            print(f"[EVAL]   Completed in {elapsed:.1f}s ({api_calls} API calls)")

            if verbose:
                for k, v in metrics.items():
                    print(f"[EVAL]     {k}: {v}")
                print()
        except Exception as exc:
            print(f"[EVAL]   FAILED: {exc}")
            all_metrics[mod_key] = {"error": str(exc)}

    total_elapsed = time.time() - start_time
    print()
    print(f"[EVAL] --- Evaluation Complete ---")
    print(f"[EVAL] Total time: {total_elapsed:.1f}s")
    print(f"[EVAL] Total API calls: {total_api_calls}")

    # Generate profile
    from profile_generator import generate_profile

    profile = generate_profile(
        model_name=effective_model,
        raw_metrics=all_metrics,
    )

    # Write output
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    safe_name = effective_model.replace("/", "_").replace("\\", "_")
    profile_path = out_path / f"{safe_name}.json"

    with open(profile_path, "w", encoding="utf-8") as f:
        json.dump(profile, f, indent=2, ensure_ascii=False)

    print(f"[EVAL] Profile written to: {profile_path}")

    return profile


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Model Evaluation Framework for Agent-Zero Hardening Layers"
    )
    parser.add_argument(
        "--api-base",
        default=None,
        help="LM Studio API base URL (default: from config.json)",
    )
    parser.add_argument(
        "--model-name",
        default=None,
        help="Model identifier for the profile (auto-detected if omitted)",
    )
    parser.add_argument(
        "--modules",
        nargs="+",
        default=None,
        help="Run only these modules (default: all)",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory for output profile (default: from config.json)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print detailed per-test output",
    )
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG),
        help="Path to config.json",
    )

    args = parser.parse_args()

    # Load config file
    config = {}
    if os.path.isfile(args.config):
        with open(args.config, "r", encoding="utf-8") as f:
            config = json.load(f)

    # Merge CLI args over config
    api_base = args.api_base or config.get("api_base", "http://localhost:1234/v1")
    model_name = args.model_name or config.get("model_name", "")
    output_dir = args.output_dir or config.get("output_dir", "./profiles")
    timeout = config.get("timeout_seconds", 120)
    max_retries = config.get("max_retries_per_test", 2)
    runs_per_test = config.get("runs_per_test", 3)

    modules = args.modules or config.get("test_modules", list(MODULE_REGISTRY.keys()))

    # Validate modules
    for m in modules:
        if m not in MODULE_REGISTRY:
            print(f"[ERROR] Unknown module: {m}")
            print(f"[ERROR] Available: {', '.join(MODULE_REGISTRY.keys())}")
            sys.exit(1)

    # Add parent dir to path for profile_generator import
    if str(SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR))

    run_evaluation(
        api_base=api_base,
        model_name=model_name,
        modules=modules,
        output_dir=output_dir,
        max_retries=max_retries,
        runs_per_test=runs_per_test,
        timeout=timeout,
        verbose=args.verbose,
    )


if __name__ == "__main__":
    main()
