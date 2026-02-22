# Translation Layer — Belief State Tracker (BST)

Compensates for local model ambiguity resolution limitations by implementing a
Task-Oriented Dialogue (TOD) architecture in front of the model. Every user
message is classified, structured, and enriched before the model ever sees it.

---

## What it does

```
User message enters agent history
    │
    ▼
[before_main_llm_call hook — _11_belief_state_tracker.py]
    │
    ├─ [1] Underspecified check
    │       Is this "fix it" / "do that again" type input?
    │       → If yes AND prior belief state exists: re-attach context, enrich, continue
    │
    ├─ [2] Domain classification
    │       Trigger-keyword matching against slot_taxonomy.json domains
    │       → domain + raw confidence score (0–1)
    │
    ├─ [3] Slot resolution
    │       For each required/optional slot: run resolver chain
    │       → keyword_map, file inference, path extraction, history scan, context inference
    │
    ├─ [4] Confidence scoring
    │       (trigger confidence × 0.4) + (slot fill rate × 0.6)
    │
    ├─ BELOW threshold + missing required slots
    │       │
    │       ▼
    │   [CLARIFY] Inject clarifying question as AI message into history
    │             Model relays it to user; user answer re-enters pipeline next turn
    │
    └─ AT OR ABOVE threshold
            │
            ▼
        [ENRICH] Replace last user message in history with enriched version:
                 [TASK CONTEXT]   resolved slot values
                 [INSTRUCTION]    domain-specific preamble
                 [USER MESSAGE]   original message verbatim
    │
    ▼
[before_main_llm_call hook — _20_context_watchdog.py]  ← existing, unmodified
    │
    ▼
LLM call
```

---

## Files

| File | Purpose |
|------|---------|
| `_11_belief_state_tracker.py` | Extension logic — target hook: `before_main_llm_call` (v2 corrected) |
| `slot_taxonomy.json` | Intent domains (18 domains), slots, resolvers, thresholds — v1.1.0 |
| `install_translation_layer.sh` | Installation script with backup |
| `install_all_snippet.sh` | Code to add to your main `install_all.sh` |

---

## Installation

### Quick install (standalone)

```bash
cd /a0/usr/hardening/translation-layer
chmod +x install_translation_layer.sh
./install_translation_layer.sh
```

### Integration with install_all.sh (recommended)

Add this to `/a0/usr/hardening/install_all.sh` after your other layers:

```bash
echo ""
echo "========================================"
echo "Layer 5: Translation Layer (BST)"
echo "========================================"
if [[ -d "$HARDENING_DIR/translation-layer" ]]; then
    bash "$HARDENING_DIR/translation-layer/install_translation_layer.sh"
else
    echo "⚠ translation-layer/ not found, skipping"
fi
```

Then run:

```bash
cd /a0/usr/hardening
bash install_all.sh
```

### Installed files

```
/a0/python/extensions/before_main_llm_call/_11_belief_state_tracker.py
/a0/python/extensions/before_main_llm_call/slot_taxonomy.json
```

The `_10_` prefix ensures BST runs before the existing `_20_context_watchdog.py`.

---

## Verification

Start a fresh agent chat and send: `refactor agent.py`

Then check the logs:

```bash
newest=$(ls -t /a0/logs/*.html | head -1)
python3 -c "
import re
with open('$newest') as f:
    text = re.sub(r'<[^>]+>', '', f.read())
for line in text.splitlines():
    if 'BST' in line:
        print(line.strip())
"
```

**Expected output:**

```
[BST] Domain: refactor | Confidence: 0.72 | Slots: ['target_file', 'operation']
```

**If you see nothing:**

1. Check files are installed:
   ```bash
   ls -lh /a0/python/extensions/before_main_llm_call/_11_belief_state_tracker.py
   ls -lh /a0/python/extensions/before_main_llm_call/slot_taxonomy.json
   ```

2. Clear Python cache and retry:
   ```bash
   rm -rf /a0/python/extensions/before_main_llm_call/__pycache__
   ```

3. Check for import errors in the latest log (HTML-decoded):
   ```bash
   python3 -c "
   import re
   with open('$(ls -t /a0/logs/*.html | head -1)') as f:
       text = re.sub(r'<[^>]+>', '', f.read())
   for line in text.splitlines():
       if any(k in line for k in ['Error', 'Traceback', 'belief', 'BST']):
           print(line.strip())
   " | tail -30
   ```

---

## Adding new domains

Edit `slot_taxonomy.json` only. No Python changes needed.

Minimum viable domain entry:

```json
"my_new_domain": {
    "description": "What this domain handles",
    "triggers": ["keyword1", "keyword2"],
    "required_slots": ["slot_a"],
    "optional_slots": [],
    "slot_definitions": {
        "slot_a": {
            "question": "What should I use for slot_a?",
            "resolvers": ["context_inference"],
            "type": "string",
            "nullable": false
        }
    },
    "confidence_threshold": 0.7,
    "preamble": "Instruction injected before the model sees this message."
}
```

---

## Tuning thresholds

Each domain has its own `confidence_threshold`. Lower = more permissive (enriches
more, clarifies less). Higher = more cautious (asks more questions).

| Domain type | Threshold |
|-------------|-----------|
| Destructive ops (file delete, agentic) | 0.75–0.85 |
| Code generation / refactor | 0.65–0.75 |
| Analysis / explanation | 0.55–0.65 |
| Conversational | 0.0 (always pass through) |

---

## How resolver chain works

For each slot, resolvers are tried in order. First non-null result wins.

| Resolver | What it does |
|----------|-------------|
| `keyword_map` | Maps surface trigger words to canonical values |
| `file_extension_inference` | Derives language from `.py`, `.js` etc. in context |
| `last_mentioned_file` | Regex scan for `filename.ext` in recent messages |
| `last_mentioned_path` | Regex scan for `/path/to/file` patterns |
| `last_mentioned_entity` | Last backtick-quoted or parenthetical entity |
| `history_scan` | Scan last 8 messages for slot-relevant content |
| `context_inference` | Lightweight keyword matching on message text |

---

## Belief state persistence

The resolved slot state persists across turns via an attribute on the agent object.
TTL is controlled by `global.belief_state_ttl_turns` (default: 6 turns).

Multi-turn slot filling example:
- Turn 1: "refactor the auth module" → domain=refactor, target_file=None → asks question
- Turn 2: "agent/auth.py" → fills target_file → enriched message sent to model

---

## Debug logging

All BST activity appears in agent-zero's log panel:

```
[BST] Enriched — Domain: codegen | Confidence: 0.82 | Slots: ['operation', 'language']
[BST] Clarify  — Missing slot: target_file in domain codegen
[BST] Non-fatal error — ...
```

The tracker **never blocks the agent on failure** — all exceptions degrade to passthrough.

---

## Architecture reference

This implements concepts from:
- Frame-based dialogue systems (GUS, Bobrow et al. 1977)
- Task-Oriented Dialogue (TOD) with Dialogue State Tracking (DST)
- Slot filling + intent classification (MultiWOZ benchmark)
- STORM: asymmetric information dynamics in dialogue (2024)
- ICLR 2025: Clarifying question generation via double-turn preferences
