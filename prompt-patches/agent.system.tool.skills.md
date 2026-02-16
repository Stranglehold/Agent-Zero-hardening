### skills_tool
#### overview
skills are folders with instructions, scripts, and files that give the agent extra capabilities.

#### critical: method goes inside tool_name using colon syntax
The method is NOT a separate argument — it is the suffix of tool_name after a colon.

| What you want to do | Correct tool_name value |
|---------------------|------------------------|
| List all skills     | `"skills_tool:list"`   |
| Load a skill        | `"skills_tool:load"`   |

**WRONG** — this will always fail:
~~~json
{
    "tool_name": "skills_tool",
    "tool_args": { "method": "list" }
}
~~~
~~~json
{
    "tool_name": "skills_tool",
    "tool_args": { "action": "list" }
}
~~~

**CORRECT** — method is part of tool_name:
~~~json
{
    "tool_name": "skills_tool:list"
}
~~~

#### workflow
1. Skills titles and descriptions are already visible in the system prompt under Available Skills.
2. Use `skills_tool:load` when you identify a relevant skill and need its full instructions.
3. Use `code_execution_tool` to run any scripts the skill provides.
4. Re-load the skill with `skills_tool:load` if it has scrolled out of conversation history.

#### skills_tool:list
List all available skills with name, version, description, tags, and author.
Only call this when you need to search skill metadata — the titles are already in your system prompt.
~~~json
{
    "thoughts": [
        "I need to find a skill for a specific capability",
        "Listing all skills to search metadata"
    ],
    "headline": "Listing available skills",
    "tool_name": "skills_tool:list"
}
~~~

#### skills_tool:load
Load the complete SKILL.md content, instructions, and file tree for a named skill.
Call this before using any skill. Call it again if the skill content is no longer in history.
~~~json
{
    "thoughts": [
        "User needs PDF form extraction",
        "pdf_editing skill will have the procedures",
        "Loading full skill content now"
    ],
    "headline": "Loading PDF editing skill",
    "tool_name": "skills_tool:load",
    "tool_args": {
        "skill_name": "pdf_editing"
    }
}
~~~

#### running skill scripts
After loading a skill, use `code_execution_tool` with the terminal runtime to execute its scripts.
Always use full paths or `cd` to the skill directory first.
~~~json
{
    "thoughts": [
        "Skill loaded, script is at scripts/convert_pdf_to_images.py",
        "Running with code_execution_tool terminal"
    ],
    "headline": "Running PDF conversion script",
    "tool_name": "code_execution_tool",
    "tool_args": {
        "runtime": "terminal",
        "code": "python /a0/skills/pdf_editing/scripts/convert_pdf_to_images.py /path/to/doc.pdf /tmp/images"
    }
}
~~~
