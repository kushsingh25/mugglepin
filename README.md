# Vera Challenge Submission — Kush Singh

## Approach

`compose()` is a deterministic, rule-based composer — one handler function per `trigger.kind` (25 kinds covered, plus a safe generic fallback for anything unrecognised). Each handler pulls its facts only from the four contexts it's given: category voice/offer_catalog/digest/peer_stats, merchant identity/performance/offers/signals/conversation_history, the trigger's own payload, and the optional customer relationship/preferences/state. No LLM call is made at request time.

This was a deliberate tradeoff, not a shortcut:
- **Determinism** is a hard requirement (§7.1). A template composer is deterministic by construction — no temperature=0 flag to get right, no model drift between runs.
- **Half of the 30 canonical test triggers ship with placeholder payloads** (`{"placeholder": true, ...}` — the dataset generator only gives real payloads to the 25 seed triggers; everything it generates on top is a stub). An LLM prompted on a placeholder payload has nothing to work with either, so the real engineering problem here is *graceful fallback to merchant/customer context when the trigger payload is empty*, not natural-language generation. Every handler in `bot.py` has an explicit real-payload path and a context-only fallback path (see `h_recall_due`, `h_customer_lapsed`, `h_milestone_reached` for the clearest examples) and never invents a number, date, or name that isn't in one of the four contexts.
- **No API key to manage, no per-call latency or cost, trivially inside the 30s budget, and no rate-limit risk during a 60-minute test window with 10 req/s from the judge.** Deployment is just "run a Python process."

The engagement-compulsion levers from §10 of the brief (specificity, loss aversion, social proof, reciprocity, curiosity, asking the merchant, single binary commitment) are baked into the per-kind templates rather than left to a prompt to remember — e.g. `curious_ask_due` always asks the merchant a direct question, `winback_eligible`/`renewal_due` always end in a single YES/STOP ask, `competitor_opened` always anchors on the real distance + peer CTR.

`bot.py` also implements all 5 required HTTP endpoints (context push with idempotent versioning, tick, reply, healthz, metadata) plus an optional `/v1/teardown`. `conversation_handlers.py` implements the multi-turn `respond()` used by `/v1/reply`: auto-reply detection (canned-phrase list + repeated-message detection, one retry then graceful exit), intent-transition handling (explicit agreement routes straight to action mode instead of re-qualifying — the brief's Pattern D anti-pattern), a hostile/off-topic branch that stays calm and redirects, a `wait` branch for "call me later," and a 3-nudge cap before the bot stops on its own.

## Tradeoffs

- Language matching is done at the phrase level (Hindi-English connective phrases swapped in when `hi` is in the merchant's or customer's language field), not full bilingual generation per message. It's authentic-looking Hinglish for the common cases in the brief's own examples, but won't produce a fully fluent Hindi sentence for an edge case the templates didn't anticipate.
- Because there's no LLM, the bot can't answer a genuinely novel merchant question in `/v1/reply` (e.g. "what if I want a different photographer for the wedding shoot") — it recognizes intent/auto-reply/hostility/wait patterns but a truly open-ended query falls through to a generic continued-nudge response rather than a bespoke answer.
- Trend/seasonal/digest citations only fire when the referenced `digest`/`top_item_id` is actually present in the pushed category context; if the judge's post-submission context injection adds a new digest item under a new id, the relevant handler already reads it live off the context store (no re-deploy needed) — it just won't be citable until it's pushed.

## What would have helped most

Confirmation of the exact enum values expected for `cta` (the brief uses `"open_ended"` and implies `"binary_yes_stop"`/`"none"` but never states the full closed set) and a note on whether `available_slots`/similar rich sub-objects are guaranteed present for every trigger kind that logically needs them (several generated triggers currently arrive as bare placeholders even when the `kind` implies specific data like a slot time or an exact appointment hour).

## Files

- `bot.py` — the composer (`compose`) + FastAPI server (5 endpoints + teardown)
- `conversation_handlers.py` — `respond()` for multi-turn `/v1/reply`
- `submission.jsonl` — 30 canonical test-pair outputs
- `requirements.txt` — the only two dependencies
