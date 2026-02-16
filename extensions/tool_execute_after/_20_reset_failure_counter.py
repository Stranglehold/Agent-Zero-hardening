from python.helpers.extension import Extension
from python.helpers.tool import Response

# Must match the key used in error_format/_30_failure_tracker.py
TRACKER_KEY = "_failure_tracker"


class ResetFailureCounter(Extension):
    async def execute(self, response: Response | None = None, **kwargs):
        """Reset the consecutive failure counter for a tool on successful execution."""
        if not response:
            return

        # tool_name is passed as kwarg from tool_execute_after hook
        tool_name = kwargs.get("tool_name", "")
        if not tool_name:
            return

        tracker = self.agent.get_data(TRACKER_KEY)
        if not isinstance(tracker, dict):
            return

        if tool_name in tracker and tracker[tool_name] > 0:
            tracker[tool_name] = 0
            self.agent.set_data(TRACKER_KEY, tracker)
