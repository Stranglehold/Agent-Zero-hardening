"""
Tool Reliability Evaluation Module
====================================
Measures tool call correctness: JSON validity, parameter accuracy,
tool selection, failure patterns, and recovery.

v1.1 â€" Uses ToolFormatAdapter for model-family-aware response parsing.
       Falls back to original content-only parsing for backward compat.
"""

import sys
from pathlib import Path

from base_eval import BaseEval

# Add parent dir for adapter import
_parent = str(Path(__file__).resolve().parent.parent)
if _parent not in sys.path:
    sys.path.insert(0, _parent)

try:
    from tool_format_adapter import ToolFormatAdapter, detect_model_family
    HAS_ADAPTER = True
except ImportError:
    HAS_ADAPTER = False


class ToolEval(BaseEval):
    FIXTURE_FILE = "tool_tests.json"

    def run(self) -> tuple[dict, int]:
        fixtures = self.load_fixtures()
        tests = fixtures["tests"]
        recovery_tests = fixtures.get("recovery_tests", [])
        system_prompt = fixtures["system_prompt"]

        # Initialize format adapter if available
        adapter = None
        if HAS_ADAPTER:
            family = detect_model_family(self.model_name)
            adapter = ToolFormatAdapter(model_family=family)
            self._log(f"[ADAPTER] Model family detected: {family}")
        else:
            self._log("[ADAPTER] tool_format_adapter not found, using legacy parsing")

        # Check if client supports raw responses
        has_raw = hasattr(self.client, 'chat_raw')

        json_valid = 0
        param_accurate = 0
        tool_correct = 0
        total = 0
        failure_types = {
            "syntax": 0, "not_found": 0, "missing_param": 0,
            "hallucinated_tool": 0, "wrong_runtime": 0, "other": 0,
        }

        for test in tests:
            tid = test["test_id"]
            self._log(f"[{tid}] {test['category']}")

            run_results = []
            for _ in range(self.runs_per_test):
                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": test["user_message"]},
                ]

                if adapter and has_raw:
                    # New path: get full response, use adapter
                    raw_resp = self.call_model_raw(messages)
                    result = self._score_tool_call_adapted(raw_resp, test, adapter)
                else:
                    # Legacy path: content string only
                    resp = self.call_model(messages)
                    result = self._score_tool_call(resp, test)

                run_results.append(result)

            # Majority vote on each dimension
            best = self.majority_vote(run_results)
            total += 1

            if best["json_valid"]:
                json_valid += 1
            if best["params_correct"]:
                param_accurate += 1
            if best["tool_correct"]:
                tool_correct += 1
            if best["failure_type"]:
                ft = best["failure_type"]
                if ft in failure_types:
                    failure_types[ft] += 1
                else:
                    failure_types["other"] += 1

            self._log(f"  json={best['json_valid']} tool={best['tool_correct']} "
                       f"params={best['params_correct']} fail={best['failure_type']}")

        # â€"â€" Recovery tests â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"
        recovery_successes = 0
        recovery_total = 0

        for rtest in recovery_tests:
            rtid = rtest["test_id"]
            self._log(f"[{rtid}] recovery test")
            recovery_total += 1

            run_recoveries = []
            for _ in range(self.runs_per_test):
                # First: send the initial message
                resp1 = self.call_model([
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": rtest["initial_message"]},
                ])
                # Then: send the error and check recovery
                messages2 = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": rtest["initial_message"]},
                    {"role": "assistant", "content": resp1},
                    {"role": "user", "content": rtest["error_response"]},
                ]

                if adapter and has_raw:
                    raw_resp2 = self.call_model_raw(messages2)
                    recovered = self._check_recovery_adapted(raw_resp2, rtest, adapter)
                else:
                    resp2 = self.call_model(messages2)
                    recovered = self._check_recovery(resp2, rtest)

                run_recoveries.append(recovered)

            if self.majority_vote(run_recoveries):
                recovery_successes += 1

        # â€"â€" Aggregate â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"
        json_rate = json_valid / total if total else 0
        param_rate = param_accurate / total if total else 0
        tool_rate = tool_correct / total if total else 0
        recovery_rate = recovery_successes / recovery_total if recovery_total else 0

        # Normalize failure distribution
        total_failures = sum(failure_types.values())
        failure_dist = {}
        if total_failures > 0:
            for k, v in failure_types.items():
                if v > 0:
                    failure_dist[k] = round(v / total_failures, 2)

        # Priority patterns â€" top failures
        priority = sorted(failure_dist, key=failure_dist.get, reverse=True)[:3]

        # Meta-gate strictness
        if json_rate < 0.80:
            strictness = "aggressive"
        elif json_rate < 0.95:
            strictness = "moderate"
        else:
            strictness = "permissive"

        metrics = {
            "tool_json_validity_rate": round(json_rate, 3),
            "tool_parameter_accuracy": round(param_rate, 3),
            "tool_selection_accuracy": round(tool_rate, 3),
            "tool_failure_distribution": failure_dist,
            "tool_recovery_rate": round(recovery_rate, 3),
            "meta_gate_strictness": strictness,
            "tool_fallback_priority_patterns": priority,
        }

        if adapter:
            metrics["_adapter_model_family"] = adapter.model_family

        return metrics, self._api_calls

    # â€"â€" Adapted scoring (new path) â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"

    def _score_tool_call_adapted(self, raw_response: dict, test: dict,
                                  adapter: 'ToolFormatAdapter') -> dict:
        """Score a tool call using the format adapter for extraction."""
        result = {
            "json_valid": False,
            "tool_correct": False,
            "params_correct": False,
            "failure_type": None,
        }

        canonical = adapter.extract_tool_call(raw_response)

        if canonical is None:
            # Adapter couldn't extract anything â€" fall back to legacy
            content = raw_response.get("content", "") or ""
            return self._score_tool_call(content, test)

        result["json_valid"] = True

        # Check tool name
        tool_name = canonical.get("tool_name", "")
        expected_tool = test["expected_tool"]
        if tool_name == expected_tool:
            result["tool_correct"] = True
        elif tool_name:
            result["failure_type"] = "hallucinated_tool"
        else:
            result["failure_type"] = "missing_param"

        # Check parameters
        args = canonical.get("tool_args", {})
        if not isinstance(args, dict):
            result["failure_type"] = "syntax"
            return result

        required = test.get("required_fields", [])
        missing = [f for f in required if f not in args]
        if missing:
            result["failure_type"] = "missing_param"
            return result

        # Check expected args if provided
        expected_args = test.get("expected_args", {})
        params_ok = True
        for key, expected_val in expected_args.items():
            actual_val = args.get(key)
            if actual_val is None:
                continue  # Already checked required
            if isinstance(expected_val, str):
                if actual_val != expected_val:
                    params_ok = False
                    if key == "runtime":
                        result["failure_type"] = "wrong_runtime"

        result["params_correct"] = params_ok and result["tool_correct"]

        return result

    def _check_recovery_adapted(self, raw_response: dict, rtest: dict,
                                 adapter: 'ToolFormatAdapter') -> bool:
        """Check recovery using the format adapter."""
        expected = rtest["expected_behavior"]
        canonical = adapter.extract_tool_call(raw_response)

        if expected == "corrects_json_format":
            return canonical is not None

        if expected == "adds_missing_parameter":
            if canonical is None:
                return False
            args = canonical.get("tool_args", {})
            return isinstance(args, dict) and len(args) >= 2

        if expected == "uses_correct_tool_name":
            if canonical is None:
                return False
            tool = canonical.get("tool_name", "")
            return tool in ("code_execution_tool", "response", "call_subordinate",
                            "memory_save", "memory_load", "search_engine")

        return canonical is not None  # Default: extractable = recovered

    # â€"â€" Legacy scoring (backward compatible) â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"â€"

    def _score_tool_call(self, response: str, test: dict) -> dict:
        """Score a single tool call response (legacy content-string path)."""
        result = {
            "json_valid": False,
            "tool_correct": False,
            "params_correct": False,
            "failure_type": None,
        }

        ok, parsed = self.try_parse_json(response)
        if not ok or parsed is None:
            result["failure_type"] = "syntax"
            return result

        result["json_valid"] = True

        # Check tool name
        tool_name = parsed.get("tool_name", parsed.get("name", ""))
        expected_tool = test["expected_tool"]
        if tool_name == expected_tool:
            result["tool_correct"] = True
        elif tool_name:
            result["failure_type"] = "hallucinated_tool"
        else:
            result["failure_type"] = "missing_param"

        # Check parameters
        args = parsed.get("tool_args", parsed.get("args", parsed.get("arguments", {})))
        if not isinstance(args, dict):
            result["failure_type"] = "syntax"
            return result

        required = test.get("required_fields", [])
        missing = [f for f in required if f not in args]
        if missing:
            result["failure_type"] = "missing_param"
            return result

        # Check expected args if provided
        expected_args = test.get("expected_args", {})
        params_ok = True
        for key, expected_val in expected_args.items():
            actual_val = args.get(key)
            if actual_val is None:
                continue  # Already checked required
            if isinstance(expected_val, str):
                if actual_val != expected_val:
                    params_ok = False
                    if key == "runtime":
                        result["failure_type"] = "wrong_runtime"

        result["params_correct"] = params_ok and result["tool_correct"]

        return result

    def _check_recovery(self, response: str, rtest: dict) -> bool:
        """Check if the model recovered after an error (legacy path)."""
        expected = rtest["expected_behavior"]

        ok, parsed = self.try_parse_json(response)

        if expected == "corrects_json_format":
            return ok
        if expected == "adds_missing_parameter":
            if not ok or parsed is None:
                return False
            args = parsed.get("tool_args", parsed.get("args", {}))
            return isinstance(args, dict) and len(args) >= 2
        if expected == "uses_correct_tool_name":
            if not ok or parsed is None:
                return False
            tool = parsed.get("tool_name", parsed.get("name", ""))
            return tool in ("code_execution_tool", "response", "call_subordinate",
                            "memory_save", "memory_load", "search_engine")

        return ok  # Default: JSON parseable = recovered
