Your last response was not valid JSON. Output ONLY a JSON object. No text before or after it.

Required structure:
~~~json
{
  "thoughts": "your reasoning",
  "tool_name": "name of tool to use",
  "tool_args": {
    "arg_name": "arg_value"
  }
}
~~~

Rules:
- No markdown outside the JSON
- No explanation text before or after
- No trailing commas
- tool_name must be one of the available tools listed in your system prompt
