### response
deliver answer to user
use for:
- conversational questions, greetings, explanations answerable from own knowledge
- final answer after completing a task
- any response that does not require tools to produce

do not use other tools before this when the answer is already known
put result in text arg
usage:
~~~json
{
    "thoughts": [
        "I can answer this directly without tools",
    ],
    "headline": "Responding to user",
    "tool_name": "response",
    "tool_args": {
        "text": "Answer to the user",
    }
}
~~~
{{ include "agent.system.response_tool_tips.md" }}
