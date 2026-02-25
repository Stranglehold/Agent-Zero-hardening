"""
Base class for all evaluation modules.
Provides common API call helpers, fixture loading, and scoring utilities.

v1.2 — Added eval_context parameter for provider-aware module behavior.
"""

import json
from collections import Counter
from pathlib import Path


class BaseEval:
    """Base evaluation module — subclass and implement run()."""

    FIXTURE_FILE = ""  # Override in subclass

    def __init__(
        self,
        client,
        model_name: str,
        fixtures_dir: str,
        max_retries: int = 2,
        runs_per_test: int = 3,
        verbose: bool = False,
        eval_context: dict = None,
    ):
        self.client = client
        self.model_name = model_name
        self.fixtures_dir = Path(fixtures_dir)
        self.max_retries = max_retries
        self.runs_per_test = runs_per_test
        self.verbose = verbose
        self.eval_context = eval_context or {}
        self._api_calls = 0

    # — Eval context helpers ————————————————————————————————————————————————
    @property
    def provider(self) -> str:
        return self.eval_context.get("provider", "")

    @property
    def force_harmony(self) -> bool:
        return self.eval_context.get("force_harmony", False)

    # — Fixture loading ————————————————————————————————————————————————————
    def load_fixtures(self) -> dict:
        path = self.fixtures_dir / self.FIXTURE_FILE
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    # — API call with retry ————————————————————————————————————————————————
    def call_model(
        self,
        messages: list[dict],
        temperature: float = 0.1,
        max_tokens: int = 2048,
    ) -> str:
        """Call the model with retries on failure. Returns content string."""
        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                self._api_calls += 1
                return self.client.chat(
                    messages=messages,
                    model=self.model_name,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            except Exception as exc:
                last_error = exc
                if self.verbose:
                    print(f"    [RETRY] Attempt {attempt + 1} failed: {exc}")
        raise last_error

    def call_model_raw(
        self,
        messages: list[dict],
        temperature: float = 0.1,
        max_tokens: int = 2048,
    ) -> dict:
        """Call the model with retries. Returns full message dict."""
        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                self._api_calls += 1
                return self.client.chat_raw(
                    messages=messages,
                    model=self.model_name,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            except Exception as exc:
                last_error = exc
                if self.verbose:
                    print(f"    [RETRY] Attempt {attempt + 1} failed: {exc}")
        raise last_error

    # — Majority vote across runs ——————————————————————————————————————————
    def majority_vote(self, results: list) -> any:
        """Return the most common result from multiple runs."""
        if not results:
            return None
        counter = Counter(str(r) for r in results)
        most_common = counter.most_common(1)[0][0]
        for r in results:
            if str(r) == most_common:
                return r
        return results[0]

    # — Scoring helpers ————————————————————————————————————————————————————
    @staticmethod
    def check_contains_any(text: str, keywords: list[str]) -> bool:
        text_lower = text.lower()
        return any(kw.lower() in text_lower for kw in keywords)

    @staticmethod
    def check_contains_all(text: str, keywords: list[str]) -> bool:
        text_lower = text.lower()
        return all(kw.lower() in text_lower for kw in keywords)

    @staticmethod
    def check_is_question(text: str) -> bool:
        first_chunk = text[:300]
        return "?" in first_chunk

    @staticmethod
    def check_has_code_block(text: str) -> bool:
        return "```" in text

    @staticmethod
    def try_parse_json(text: str) -> tuple[bool, dict | None]:
        try:
            return True, json.loads(text)
        except json.JSONDecodeError:
            pass

        if "```" in text:
            blocks = text.split("```")
            for i in range(1, len(blocks), 2):
                block = blocks[i]
                if block.startswith("json"):
                    block = block[4:]
                block = block.strip()
                try:
                    return True, json.loads(block)
                except json.JSONDecodeError:
                    continue

        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            try:
                return True, json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass

        return False, None

    @staticmethod
    def try_parse_python(code: str) -> bool:
        import ast
        try:
            ast.parse(code)
            return True
        except SyntaxError:
            return False

    # — Required override ——————————————————————————————————————————————————
    def run(self) -> tuple[dict, int]:
        raise NotImplementedError

    def _log(self, msg: str):
        if self.verbose:
            print(f"    {msg}")
