from python.helpers.extension import Extension
from python.helpers import tokens, log
from agent import LoopData
import json

# Default context window for local models
# Override per-agent: agent.set_data("context_window_size", 131072)
DEFAULT_CONTEXT_WINDOW = 100000

# Warning thresholds as fraction of total window
WARN_THRESHOLD = 0.70   # log warning at 70%
CRITICAL_THRESHOLD = 0.85  # log critical at 85%

# Key for storing token count in params_temporary
# Other extensions (e.g. future summarizer) can read this
TOKEN_COUNT_KEY = "context_token_count"
WINDOW_SIZE_KEY = "context_window_size"


def _serialize_component(component) -> str:
    """Best-effort serialization of a loop_data component for token counting."""
    if component is None:
        return ""
    if isinstance(component, str):
        return component
    try:
        return json.dumps(component, default=str)
    except Exception:
        return str(component)


class ContextWatchdog(Extension):
    async def execute(self, loop_data: LoopData = LoopData(), **kwargs):
        # Get configured window size, fall back to default
        window_size = (
            self.agent.get_data("context_window_size") or DEFAULT_CONTEXT_WINDOW
        )

        # Count tokens across all prompt components
        # loop_data.system: list of system prompt segments
        # loop_data.history_output: list of history messages
        # loop_data.extras_temporary / extras_persistent: injected context blocks
        components = [
            loop_data.system,
            loop_data.history_output,
            list(loop_data.extras_temporary.values()),
            list(loop_data.extras_persistent.values()),
        ]

        total_tokens = sum(
            tokens.approximate_tokens(_serialize_component(c))
            for c in components
        )

        utilization = total_tokens / window_size

        # Store in params_temporary for other extensions to read this iteration
        loop_data.params_temporary[TOKEN_COUNT_KEY] = total_tokens
        loop_data.params_temporary[WINDOW_SIZE_KEY] = window_size

        # Log based on threshold
        if utilization >= CRITICAL_THRESHOLD:
            msg = (
                f"[CONTEXT CRITICAL] {total_tokens:,} / {window_size:,} tokens "
                f"({utilization:.0%}) — approaching limit. "
                f"Responses may degrade. Consider /reset or summarizing history."
            )
            self.agent.context.log.log(type="warning", content=msg)
            from python.helpers.print_style import PrintStyle
            PrintStyle(font_color="red", padding=True).print(msg)

        elif utilization >= WARN_THRESHOLD:
            msg = (
                f"[CONTEXT WARNING] {total_tokens:,} / {window_size:,} tokens "
                f"({utilization:.0%}) — context filling."
            )
            self.agent.context.log.log(type="warning", content=msg)
            from python.helpers.print_style import PrintStyle
            PrintStyle(font_color="orange", padding=False).print(msg)
