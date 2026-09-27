from bot import (
    is_auto_reply, is_not_interested, is_intent, is_hostile,
    owner_name, biz_name, active_offer,
)

FOLLOWUPS = [
    "Just checking — want me to go ahead with this?",
    "No pressure, but this window won't stay open long. Should I proceed?",
    "One more nudge from me on this — yes to go ahead, or should I drop it?",
]

HOSTILE_REPLY = "Understood, I'll keep it short. {topic}Want me to continue or should I stop reaching out?"

OFFTOPIC_REPLY = "That's outside what I handle here, so I can't help with that directly. {topic}Should I continue with this, or would you rather I check back another time?"


def respond(state, merchant_message):
    state["turn_number"] = state.get("turn_number", 0) + 1
    state.setdefault("merchant_messages", []).append(merchant_message)
    merchant = state.get("merchant", {}) or {}
    customer = state.get("customer")
    name = owner_name(merchant) if merchant else "there"

    if is_auto_reply(state, merchant_message):
        if not state.get("auto_reply_warned"):
            state["auto_reply_warned"] = True
            body = f"Samajh gayi — before this goes to your team, want to take 2 minutes yourself? Reply YES if so, or I'll wait for them."
            state["sent_bodies"].append(body)
            return {"action": "send", "body": body, "cta": "binary_yes_stop",
                    "rationale": "First auto-reply detected; one direct attempt before backing off"}
        return {"action": "end",
                "rationale": "Second auto-reply confirms this is a canned response; exiting gracefully instead of burning more turns"}

    if is_not_interested(merchant_message):
        return {"action": "end", "rationale": "Merchant signalled not interested; exiting gracefully"}

    if is_hostile(merchant_message):
        body = HOSTILE_REPLY.format(topic="")
        state["sent_bodies"].append(body)
        return {"action": "send", "body": body, "cta": "open_ended",
                "rationale": "Hostile message detected; stayed calm and kept the door open without escalating"}

    if is_intent(merchant_message):
        offer = active_offer(merchant)
        state["mode"] = "action"
        body = (f"Great — starting now. {('I\'ll use ' + offer.get('title') + ' as the anchor. ') if offer else ''}"
                f"I'll have the first draft ready shortly, no further input needed from you unless you want changes.")
        state["sent_bodies"].append(body)
        return {"action": "send", "body": body, "cta": "none",
                "rationale": "Explicit merchant agreement detected; switched straight to action instead of asking another qualifying question"}

    if state.get("mode") == "action":
        body = f"Noted, {name} — updating that now, I'll confirm once it's live."
        if body in state.get("sent_bodies", []):
            body = f"On it — I'll ping you the moment it's done."
        state["sent_bodies"].append(body)
        return {"action": "send", "body": body, "cta": "none",
                "rationale": "Already in action mode; acknowledging the follow-up without re-pitching"}

    if any(w in merchant_message.lower() for w in ["busy", "later", "call me after", "not now"]):
        return {"action": "wait", "wait_seconds": 1800,
                "rationale": "Merchant asked for time; backing off 30 minutes instead of pushing"}

    turn = state["turn_number"]
    idx = min(turn - 1, len(FOLLOWUPS) - 1)
    body = FOLLOWUPS[idx]
    tries = sum(1 for b in state.get("sent_bodies", []) if b in FOLLOWUPS)
    if tries >= len(FOLLOWUPS):
        return {"action": "end", "rationale": "3 unanswered nudges sent; stopping instead of spamming further"}
    state["sent_bodies"].append(body)
    return {"action": "send", "body": body, "cta": "binary_yes_stop",
            "rationale": "Neutral/curious reply; continuing with the next compulsion lever in sequence"}
