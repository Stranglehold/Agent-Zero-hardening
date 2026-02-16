from python.helpers.extension import Extension
from agent import Agent, LoopData

# Default context window for local models
# Override per-agent: agent.set_data("context_window_size", 131072)
DEFAULT_CONTEXT_WINDOW = 100000

# Warning thresholds as fraction of total window
WARN_THRESHOLD = 0.70     # log warning at 70%
CRITICAL_THRESHOLD = 0.85 # log critical at 85%

# Keys for storing utilization in params_temporary
# Other extensions (e.g. future summarizer) can read these
UTILIZATION_KEY = "context_utilization"
TOKEN_COUNT_KEY = "context_token_count"


class ContextWatchdog(Extension):
    async def execute(self, loop_data: LoopData = LoopData(), **kwargs):
        # Read token count from agent-zero's own ctx_window store
        # Computed by prepare_prompt() on the previous iteration from the
        # actual assembled prompt — more accurate than approximating components
        ctx_window_data = self.agent.get_data(Agent.DATA_NAME_CTX_WINDOW)

        if not ctx_window_data:
            return  # No data yet (first iteration) — skip

        total_tokens = ctx_window_data.get("tokens", 0)
        if not total_tokens:
            return

        window_size = (
            self.agent.get_data("context_window_size") or DEFAULT_CONTEXT_WINDOW
        )

        utilization = total_tokens / window_size

        # Store for other extensions to read this iteration
        loop_data.params_temporary[UTILIZATION_KEY] = utilization
        loop_data.params_temporary[TOKEN_COUNT_KEY] = total_tokens

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
