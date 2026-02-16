# Agent-Zero Hardening Layer

A persistent scaffolding stack for [Agent-Zero](https://github.com/frdel/agent-zero) that compensates for local model limitations and survives upstream Docker image updates.

**Validated runtime:** Qwen2.5-14B-Instruct-1M

---

## What This Does

Agent-Zero assumes a frontier model (GPT-4/Claude Opus) with strong instruction-following and structured output capabilities. Local models like Qwen2.5-14B need additional scaffolding to execute reliably. This repo provides:

| Layer | What It Fixes |
|-------|---------------|
| **FW replacements** | Recovery messages are vague and don't provide corrective action |
| **Extensions** | No context monitoring, no tiered tool injection, no failure reflection loop |
| **Prompt patches** | Default routing sends task requests to conversational path; no tool schema grounding |
| **Skill overrides** | create-skill wizard loops on multi-turn interview instead of building immediately |

---

## Structure

```
/
├── install_all.sh              # Run everything at once
├── update.sh                   # Git pull + install_all in one command
├── setup_github.sh             # One-time GitHub remote setup
│
├── fw-replacements/            # Recovery message overrides
│   ├── fw.msg_misformat.md
│   ├── fw.msg_repeat.md
│   ├── fw.msg_nudge.md
│   ├── fw.error.md
│   ├── fw.tool_not_found.md
│   ├── fw.warning.md
│   ├── install_fw_replacements.sh
│   └── check_fw_upstream.sh
│
├── extensions/                 # Agent-zero extension point overrides
│   ├── before_main_llm_call/
│   │   └── _20_context_watchdog.py     # Warns at 70%/85% context utilization
│   ├── error_format/
│   │   ├── _20_structured_retry.py     # Injects inline schema on format errors
│   │   └── _30_failure_tracker.py      # Forces reflection after N consecutive failures
│   ├── message_loop_prompts_after/
│   │   └── _95_tiered_tool_injection.py # ~6,250 token savings per turn
│   ├── tool_execute_after/
│   │   └── _20_reset_failure_counter.py # Resets failure counter on success
│   ├── install_extensions.sh
│   ├── install_failure_tracker.sh
│   └── check_extensions_upstream.sh
│
├── prompt-patches/             # System prompt overrides
│   ├── agent.system.main.solving.md   # Classification gate + task/conversational routing
│   ├── agent.system.main.tips.md      # Tool schema grounding + scope rules
│   ├── agent.system.tool.response.md  # Response tool reframed for direct answers
│   ├── install_prompt_patches.sh
│   └── check_prompt_patches_upstream.sh
│
└── skills/                     # Curated skill overrides
    └── create-skill/
        └── SKILL.md            # Rewritten wizard: build-first, no interview loop
```

---

## Quick Start

### First-time setup (new container or after docker pull)

```bash
cd /a0/usr/hardening
bash setup_github.sh     # connects to GitHub, pushes local state
bash install_all.sh      # deploys everything to /a0/
```

### Daily workflow

```bash
bash update.sh           # git pull + full redeploy in one command
```

### Check for upstream agent-zero changes before reinstalling

```bash
bash install_all.sh --check-only
```

### Push local changes to GitHub

```bash
cd /a0/usr/hardening
git add .
git commit -m "your message"
git push
```

---

## After Docker Pull

Agent-zero updates can overwrite files in `/a0/prompts/` and `/a0/python/extensions/`. The check scripts diff your backed-up originals against what's currently installed, so you know what changed upstream before deciding whether to reconcile or overwrite.

```bash
bash update.sh           # pulls from GitHub and redeploys
```

Backed-up originals are stored at:
- `/a0/prompts/.fw_originals/`
- `/a0/python/extensions/.hardening_originals/`
- `/a0/skills/.hardening_originals/`

---

## Token Impact

| Before | After |
|--------|-------|
| ~6,700 tokens/turn (all tool specs) | ~970 tokens/turn (response + code_execution_tool always; active tool conditionally) |
| No context monitoring | Warning at 70%, critical at 85% |
| No failure analysis | Reflection prompt after 2 consecutive failures on same tool |
