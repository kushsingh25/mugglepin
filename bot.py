import time
import json
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import FastAPI
from pydantic import BaseModel

CATEGORY_NOUN = {
    "dentists": "patients",
    "salons": "clients",
    "gyms": "members",
    "restaurants": "guests",
    "pharmacies": "customers",
}


def identity(merchant):
    return merchant.get("identity", {})


def biz_name(merchant):
    return identity(merchant).get("name", "there")


def owner_name(merchant):
    ident = identity(merchant)
    return ident.get("owner_first_name") or ident.get("pharmacist_name") or biz_name(merchant)


def hi_pref(merchant, customer=None):
    langs = identity(merchant).get("languages", [])
    if "hi" in langs:
        return True
    if customer:
        lp = customer.get("identity", {}).get("language_pref", "")
        if "hi" in lp:
            return True
    return False


def noun(category, merchant):
    slug = category.get("slug") or merchant.get("category_slug")
    return CATEGORY_NOUN.get(slug, "customers")


def active_offer(merchant):
    for o in merchant.get("offers", []):
        if o.get("status") == "active":
            return o
    return None


def catalog_pitch_offer(category):
    for o in category.get("offer_catalog", []):
        if o.get("type") == "service_at_price":
            return o
    catalog = category.get("offer_catalog", [])
    return catalog[0] if catalog else None


def digest_by_id(category, item_id):
    if not item_id:
        return None
    for d in category.get("digest", []):
        if d.get("id") == item_id:
            return d
    return None


def signals(merchant):
    return merchant.get("signals", [])


def has_signal(merchant, prefix):
    return any(s == prefix or s.startswith(prefix + ":") for s in signals(merchant))


def peer_ctr(category):
    return category.get("peer_stats", {}).get("avg_ctr")


def pct(x):
    if x is None:
        return None
    return f"{abs(round(x * 100))}%"


def opener(name, hi):
    if hi:
        return f"{name},"
    return f"{name},"


def cta_close(kind, hi, extra=""):
    if kind == "binary_yes_stop":
        return f"Reply YES to go ahead or STOP to skip.{(' ' + extra) if extra else ''}"
    if kind == "multi_choice":
        return extra
    return extra or ("Chahenge to bata dijiye, main aage badha doon?" if hi else "Want me to take this forward?")


def make(body, cta, send_as, rationale):
    clean = " ".join(body.split())
    return {"body": clean, "cta": cta, "send_as": send_as, "rationale": rationale}


def h_research_digest(category, merchant, trigger, customer):
    payload = trigger.get("payload", {})
    item = digest_by_id(category, payload.get("top_item_id"))
    name = owner_name(merchant)
    hi = hi_pref(merchant, customer)
    if item:
        seg = item.get("patient_segment", "")
        seg_note = f" for your {seg.replace('_', ' ')}" if seg and has_signal(merchant, seg) else ""
        n = item.get("trial_n")
        n_note = f"{n}-{noun(category, merchant)[:-1]} " if n else ""
        body = (f"{owner_name(merchant)}, {item.get('source', 'this week\'s digest')} just landed. "
                f"One item relevant{seg_note}: {n_note}study found {item.get('title', '').lower()}. "
                f"{item.get('actionable', 'Worth a look')}. Want me to pull the full item and draft something you can share?")
    else:
        body = (f"{name}, this week's {category.get('display_name', 'category')} research digest is out. "
                f"Want me to pull the item most relevant to your {noun(category, merchant)} mix?")
    return make(body, "open_ended", "vera",
                f"External research_digest trigger; cites {item.get('id') if item else 'this week\'s digest'}, no invented data")


def h_regulation_change(category, merchant, trigger, customer):
    payload = trigger.get("payload", {})
    item = digest_by_id(category, payload.get("top_item_id"))
    name = owner_name(merchant)
    deadline = payload.get("deadline_iso", "")
    if item:
        body = (f"{name}, heads up on a compliance change: {item.get('title', '')} "
                f"({item.get('source', '')}). {item.get('summary', '')} "
                f"{item.get('actionable', '')}{(' Deadline: ' + deadline + '.') if deadline else ''} "
                f"Want me to send a one-page checklist so your setup is audit-ready?")
    else:
        body = f"{name}, a regulation update just dropped for {category.get('display_name', 'your category')}{(' with a ' + deadline + ' deadline') if deadline else ''}. Want the details?"
    return make(body, "open_ended", "vera", "External regulation_change trigger, urgency reflects compliance deadline")


def h_cde_opportunity(category, merchant, trigger, customer):
    payload = trigger.get("payload", {})
    item = digest_by_id(category, payload.get("digest_item_id"))
    name = owner_name(merchant)
    credits = payload.get("credits")
    fee = payload.get("fee", "")
    if item:
        body = (f"{name}, {item.get('title', 'a CDE session')} is coming up"
                f"{(' on ' + item.get('date', '')[:10]) if item.get('date') else ''}. "
                f"{item.get('summary', '')} {(str(credits) + ' credits, ') if credits else ''}{fee}. "
                f"Want me to block the slot on your calendar?")
    else:
        body = f"{name}, a CDE opportunity just opened up ({fee}). Want the details?"
    return make(body, "binary_yes_stop", "vera", "External cde_opportunity trigger, references catalog digest item directly")


def h_chronic_refill_due(category, merchant, trigger, customer):
    payload = trigger.get("payload", {})
    hi = hi_pref(merchant, customer)
    cname = customer.get("identity", {}).get("name", "there") if customer else "there"
    molecules = payload.get("molecule_list", [])
    runs_out = payload.get("stock_runs_out_iso", "")[:10]
    mol_note = ", ".join(molecules) if molecules else "your regular medicines"
    if runs_out:
        body = (f"Hi {cname}, {biz_name(merchant)} here. Apka {mol_note} ka stock {runs_out} tak khatam ho sakta hai. "
                f"Chahein to hum refill pack ready rakh dein, delivery bhi ho jayegi.") if hi else \
               (f"Hi {cname}, this is {biz_name(merchant)}. Your {mol_note} refill runs out around {runs_out}. "
                f"Want us to prep the refill and arrange delivery?")
    else:
        body = f"Hi {cname}, {biz_name(merchant)} here. Time for your usual refill — want us to get it ready for pickup or delivery?"
    return make(body, "binary_yes_stop", "merchant_on_behalf", "Internal chronic_refill_due trigger, personalised to the customer's actual molecule list")


def h_competitor_opened(category, merchant, trigger, customer):
    payload = trigger.get("payload", {})
    name = owner_name(merchant)
    comp = payload.get("competitor_name")
    dist = payload.get("distance_km")
    offer = payload.get("their_offer")
    if comp:
        peer = pct(peer_ctr(category))
        body = (f"{name}, quick heads up — {comp} opened {dist}km from you"
                f"{(' running ' + offer) if offer else ''}."
                f"{(' Category peer avg CTR runs around ' + peer + '.') if peer else ''} "
                f"Want me to show 2 quick wins to keep your listing ahead?")
    else:
        body = f"{name}, a new competitor opened up nearby. Want me to check how your listing compares?"
    return make(body, "open_ended", "vera", "External competitor_opened trigger, uses named competitor + distance from payload")


def h_curious_ask_due(category, merchant, trigger, customer):
    payload = trigger.get("payload", {})
    name = owner_name(merchant)
    template = payload.get("ask_template", "")
    if template == "what_service_in_demand_this_week":
        q = f"what's been your most-asked-for service this week?"
    else:
        q = f"what's one thing {noun(category, merchant)} keep asking you about lately?"
    body = f"Quick one, {name} — {q} Tell me and I'll turn it into a post."
    return make(body, "open_ended", "vera", "Internal curious_ask_due trigger, asking the merchant directly (compulsion lever: reciprocity)")


def h_winback_eligible(category, merchant, trigger, customer):
    payload = trigger.get("payload", {})
    name = owner_name(merchant)
    lapsed = payload.get("lapsed_customers_added_since_expiry")
    dip = payload.get("perf_dip_pct")
    offer = active_offer(merchant) or catalog_pitch_offer(category)
    body = (f"{name}, since your plan lapsed {payload.get('days_since_expiry', 'recently')} days ago"
            f"{(', ' + str(lapsed) + ' more ' + noun(category, merchant) + ' have gone quiet') if lapsed else ''}"
            f"{(' and visibility is down ' + pct(dip)) if dip else ''}. "
            f"Renewing gets your {offer.get('title') if offer else 'listing'} back in front of them. Reply YES to renew or STOP to skip.")
    return make(body, "binary_yes_stop", "vera", "Internal winback_eligible trigger, loss-aversion framed on real lapse/dip numbers")


def h_ipl_match_today(category, merchant, trigger, customer):
    payload = trigger.get("payload", {})
    name = owner_name(merchant)
    match = payload.get("match")
    offer = active_offer(merchant) or catalog_pitch_offer(category)
    body = (f"{name}, {match or 'tonight\'s match'} kicks off tonight — match nights usually run 1.5x your weekday avg. "
            f"Want me to push a quick post for {offer.get('title') if offer else 'tonight'} before kickoff?")
    return make(body, "binary_yes_stop", "vera", "External ipl_match_today trigger, category tone_example for restaurants used directly")


def h_review_theme_emerged(category, merchant, trigger, customer):
    payload = trigger.get("payload", {})
    name = owner_name(merchant)
    theme = payload.get("theme", "").replace("_", " ")
    n = payload.get("occurrences_30d")
    quote = payload.get("common_quote")
    body = (f"{name}, {n or 'a few'} reviews this month mention \"{theme}\""
            f"{(' — one says: ' + chr(34) + quote + chr(34)) if quote else ''}. "
            f"Worth a quick reply on those + a one-line fix in your next post? I can draft both.")
    return make(body, "open_ended", "vera", "Internal review_theme_emerged trigger, quotes the actual recurring theme from reviews")


def h_milestone_reached(category, merchant, trigger, customer):
    payload = trigger.get("payload", {})
    name = owner_name(merchant)
    metric = payload.get("metric", "").replace("_", " ")
    now_v = payload.get("value_now")
    target = payload.get("milestone_value")
    if payload.get("is_imminent") and now_v and target:
        body = f"{name}, you're at {now_v} {metric} — {target - now_v} away from {target}. Want me to nudge your last few visitors for a review to close the gap?"
    elif now_v and metric:
        body = f"{name}, you just crossed {now_v} {metric}. Want a quick post celebrating it?"
    else:
        body = f"{name}, looks like you've hit a milestone worth marking. Want me to check exactly which one and put a quick post together?"
    return make(body, "binary_yes_stop", "vera", "Internal milestone_reached trigger, distance-to-milestone is the specific hook")


def h_active_planning_intent(category, merchant, trigger, customer):
    payload = trigger.get("payload", {})
    name = owner_name(merchant)
    topic = payload.get("intent_topic", "").replace("_", " ")
    offer = active_offer(merchant)
    body = (f"On it, {name} — for {topic}, based on your current offers I'd structure it around "
            f"{offer.get('title') if offer else 'a simple service+price hook'}. "
            f"I'll draft the full copy now — want it in English or Hindi-English?")
    return make(body, "open_ended", "vera", "Internal active_planning_intent trigger; merchant already said yes, so bot moves to action not another qualifying question")


def h_seasonal_perf_dip(category, merchant, trigger, customer):
    payload = trigger.get("payload", {})
    name = owner_name(merchant)
    metric = payload.get("metric", "views")
    delta = payload.get("delta_pct")
    note = payload.get("season_note", "").replace("_", " ")
    body = (f"{name}, your {metric} are down {pct(delta) or 'a bit'} this week"
            f"{(' — expected for the ' + note) if note else ''}, should recover on its own. "
            f"Want me to schedule 2 posts now so you're first back when demand returns?")
    return make(body, "binary_yes_stop", "vera", "Internal seasonal_perf_dip trigger, framed as expected not alarming since is_expected_seasonal")


def h_customer_lapsed(category, merchant, trigger, customer, hard=False):
    payload = trigger.get("payload", {})
    hi = hi_pref(merchant, customer)
    cname = customer.get("identity", {}).get("name", "there") if customer else "there"
    rel = customer.get("relationship", {}) if customer else {}
    last_visit = rel.get("last_visit")
    focus = payload.get("previous_focus", "").replace("_", " ")
    days = payload.get("days_since_last_visit")
    offer = active_offer(merchant)
    focus_note = f" on {focus}" if focus else ""
    since_note = f"It's been {days} days" if days else (f"It's been a while since {last_visit}" if last_visit else "It's been a while")
    if hi:
        body = (f"Hi {cname}, {biz_name(merchant)} se. {since_note} aapki last visit ko{focus_note}. "
                f"{('Abhi ' + offer.get('title') + ' chal raha hai — ') if offer else ''}Wapas ek slot book karna chahenge?")
    else:
        body = (f"Hi {cname}, this is {biz_name(merchant)}. {since_note} since your last visit{focus_note}. "
                f"{(offer.get('title') + ' is on right now — ') if offer else ''}Want to book a slot back in?")
    return make(body, "binary_yes_stop", "merchant_on_behalf",
                f"Internal customer_lapsed_{'hard' if hard else 'soft'} trigger, uses real relationship/focus data" if (days or focus) else
                f"Internal customer_lapsed_{'hard' if hard else 'soft'} trigger; payload had no specifics, fell back to relationship history only")


def h_dormant_with_vera(category, merchant, trigger, customer):
    payload = trigger.get("payload", {})
    name = owner_name(merchant)
    days = payload.get("days_since_last_merchant_message")
    topic = payload.get("last_topic", "").replace("_", " ")
    if days:
        body = (f"{name}, haven't heard from you in {days} days"
                f"{(' since we talked about ' + topic) if topic else ''}. "
                f"No pressure — just say the word if you want me to pick that back up, or STOP if you'd rather I go quiet.")
    else:
        body = f"{name}, it's been a while since we last spoke. Want me to pick things back up, or should I go quiet for now?"
    return make(body, "binary_yes_stop", "vera", "Internal dormant_with_vera trigger, one gentle re-engagement with an explicit opt-out")


def h_festival_upcoming(category, merchant, trigger, customer):
    payload = trigger.get("payload", {})
    name = owner_name(merchant)
    festival = payload.get("festival")
    days_until = payload.get("days_until")
    offer = active_offer(merchant) or catalog_pitch_offer(category)
    if festival:
        body = (f"{name}, {festival} is {days_until} days out. "
                f"Want me to draft a {festival}-themed post around {offer.get('title') if offer else 'one of your offers'} now, before the rush?")
    else:
        body = f"{name}, a festival window is coming up that fits your category. Want a post drafted for it?"
    return make(body, "binary_yes_stop", "vera", "External festival_upcoming trigger, uses category_relevance + real days_until")


def h_gbp_unverified(category, merchant, trigger, customer):
    payload = trigger.get("payload", {})
    name = owner_name(merchant)
    uplift = payload.get("estimated_uplift_pct")
    path = payload.get("verification_path", "").replace("_", " or ")
    body = (f"{name}, your Google profile is still unverified — verified listings in your category see "
            f"about {pct(uplift) or 'noticeably'} more views. Verification is quick, via {path}. Want me to start it for you?")
    return make(body, "binary_yes_stop", "vera", "Internal gbp_unverified trigger, specific uplift estimate from payload")


def h_supply_alert(category, merchant, trigger, customer):
    payload = trigger.get("payload", {})
    name = owner_name(merchant)
    molecule = payload.get("molecule")
    batches = payload.get("affected_batches", [])
    mfr = payload.get("manufacturer")
    body = (f"{name}, recall alert: {mfr or 'a manufacturer'}'s {molecule or 'a molecule'} — batches "
            f"{', '.join(batches) if batches else 'affected'} are flagged. Want me to pull the checklist for pulling and reporting stock?")
    return make(body, "binary_yes_stop", "vera", "External supply_alert trigger, exact batch numbers from payload, no invented detail")


def h_category_seasonal(category, merchant, trigger, customer):
    payload = trigger.get("payload", {})
    name = owner_name(merchant)
    trends = payload.get("trends", [])
    top = trends[0].replace("_", " ") if trends else None
    body = (f"{name}, seasonal shift kicking in"
            f"{(' — ' + top) if top else ''}. "
            f"Want me to flag the shelf/stock changes worth making this week?") if top else \
           f"{name}, a seasonal demand shift is starting for {category.get('display_name', 'your category')}. Want the details?"
    return make(body, "open_ended", "vera", "External category_seasonal trigger, first listed trend used as the specific hook")


def h_trial_followup(category, merchant, trigger, customer):
    payload = trigger.get("payload", {})
    hi = hi_pref(merchant, customer)
    cname = customer.get("identity", {}).get("name", "there") if customer else "there"
    options = payload.get("next_session_options", [])
    slot = options[0].get("label") if options else None
    if slot:
        body = (f"Hi {cname}, {biz_name(merchant)} yahan se. Trial kaisa raha? Agla session {slot} par rakha hai — "
                f"chalega ya koi aur time better hoga?") if hi else \
               (f"Hi {cname}, this is {biz_name(merchant)}. How was the trial? We've held {slot} for your next session — "
                f"works for you, or want a different time?")
    else:
        body = f"Hi {cname}, this is {biz_name(merchant)}. How was your trial? Want to lock in your next session?"
    return make(body, "multi_choice", "merchant_on_behalf", "Internal trial_followup trigger, offers the actual held slot from payload")


def h_wedding_package_followup(category, merchant, trigger, customer):
    payload = trigger.get("payload", {})
    cname = customer.get("identity", {}).get("name", "there") if customer else "there"
    days = payload.get("days_to_wedding")
    step = payload.get("next_step_window_open", "").replace("_", " ")
    body = (f"Hi {cname}, {biz_name(merchant)} here. {days} days to the big day! "
            f"Your {step} window is open now — want me to hold a slot before it fills up?")
    return make(body, "binary_yes_stop", "merchant_on_behalf", "Internal wedding_package_followup trigger, countdown + next-step window from payload")


def h_renewal_due(category, merchant, trigger, customer):
    payload = trigger.get("payload", {})
    name = owner_name(merchant)
    days = payload.get("days_remaining") or merchant.get("subscription", {}).get("days_remaining")
    amount = payload.get("renewal_amount")
    plan = payload.get("plan") or merchant.get("subscription", {}).get("plan")
    body = (f"{name}, your {plan or ''} plan renews in {days} days"
            f"{(' (₹' + str(amount) + ')') if amount else ''}. Reply YES to renew now or STOP if you're deciding later.")
    return make(body, "binary_yes_stop", "vera", "Internal renewal_due trigger, real days_remaining + renewal_amount, single binary CTA")


def h_perf_dip(category, merchant, trigger, customer):
    payload = trigger.get("payload", {})
    name = owner_name(merchant)
    metric = payload.get("metric")
    delta = payload.get("delta_pct")
    baseline = payload.get("vs_baseline")
    perf = merchant.get("performance", {})
    if metric and delta is not None:
        body = (f"{name}, your {metric} dropped {pct(delta)} this week"
                f"{(' vs your usual ' + str(baseline)) if baseline else ''}. Want me to check what changed and suggest a fix?")
    else:
        d7 = perf.get("delta_7d", {})
        worst = min(d7.items(), key=lambda kv: kv[1]) if d7 else None
        if worst and worst[1] < 0:
            body = f"{name}, your {worst[0].replace('_pct', '')} is down {pct(worst[1])} over the last week. Want me to look into why?"
        else:
            body = f"{name}, noticed a dip in your numbers this week. Want me to dig into which metric and why?"
    return make(body, "open_ended", "vera", "Internal perf_dip trigger; used payload metric where present, merchant performance.delta_7d as fallback")


def h_perf_spike(category, merchant, trigger, customer):
    payload = trigger.get("payload", {})
    name = owner_name(merchant)
    metric = payload.get("metric")
    delta = payload.get("delta_pct")
    driver = payload.get("likely_driver", "").replace("_", " ")
    if metric and delta is not None:
        body = (f"{name}, your {metric} are up {pct(delta)} this week"
                f"{(', looks driven by your ' + driver) if driver else ''}. "
                f"Want me to double down with another post in the same style while it's working?")
    else:
        body = f"{name}, your numbers ticked up this week. Want me to check what's driving it so we can repeat it?"
    return make(body, "binary_yes_stop", "vera", "Internal perf_spike trigger, ties the spike to likely_driver so the merchant can repeat it")


def h_recall_due(category, merchant, trigger, customer):
    payload = trigger.get("payload", {})
    hi = hi_pref(merchant, customer)
    cname = customer.get("identity", {}).get("name", "there") if customer else "there"
    rel = customer.get("relationship", {}) if customer else {}
    service = payload.get("service_due", "").replace("_", " ")
    slots = payload.get("available_slots", [])
    offer = active_offer(merchant)
    slot_text = " ya ".join(s.get("label", "") for s in slots) if hi else " or ".join(s.get("label", "") for s in slots)
    last_visit = rel.get("last_visit")
    if hi:
        body = (f"Hi {cname}, {biz_name(merchant)} se — aapka {service or 'recall'} due hai"
                f"{(' (last visit ' + last_visit + ')') if last_visit else ''}. ")
        if slot_text:
            body += f"Slots ready hain: {slot_text}."
        if offer:
            body += f" {offer.get('title')} bhi chal raha hai."
        body += " Reply 1 ya 2 karke bata dijiye, ya koi aur time bata dein." if slots else " Koi time bata dein jo aapke liye theek ho."
    else:
        body = (f"Hi {cname}, {biz_name(merchant)} here — your {service or 'recall'} is due"
                f"{(' (last visit ' + last_visit + ')') if last_visit else ''}. ")
        if slot_text:
            body += f"Slots ready: {slot_text}."
        if offer:
            body += f" {offer.get('title')} is also active right now."
        body += " Reply 1 or 2, or tell us a time that works." if slots else " Tell us a time that works for you."
    rationale = "Internal recall_due trigger, real due service + actual open slots + active offer" if slots else \
                "Internal recall_due trigger; payload had no slots listed, fell back to service_due + relationship history only"
    return make(body, "multi_choice" if slots else "open_ended", "merchant_on_behalf", rationale)


def h_appointment_tomorrow(category, merchant, trigger, customer):
    hi = hi_pref(merchant, customer)
    cname = customer.get("identity", {}).get("name", "there") if customer else "there"
    slot_pref = customer.get("preferences", {}).get("preferred_slots", "").replace("_", " ") if customer else ""
    if hi:
        body = (f"Hi {cname}, {biz_name(merchant)} se — kal aapki visit hai"
                f"{(' apke usual ' + slot_pref + ' slot par') if slot_pref else ''}. Sab confirm hai, koi change chahiye to bata dijiye.")
    else:
        body = (f"Hi {cname}, this is {biz_name(merchant)} — quick reminder about your visit tomorrow"
                f"{(' in your usual ' + slot_pref + ' slot') if slot_pref else ''}. All set — let us know if anything's changed.")
    return make(body, "binary_yes_stop", "merchant_on_behalf", "Internal appointment_tomorrow trigger; payload had no exact time, so used the customer's known slot preference instead of inventing one")


TRIGGER_HANDLERS = {
    "research_digest": h_research_digest,
    "regulation_change": h_regulation_change,
    "cde_opportunity": h_cde_opportunity,
    "chronic_refill_due": h_chronic_refill_due,
    "competitor_opened": h_competitor_opened,
    "curious_ask_due": h_curious_ask_due,
    "winback_eligible": h_winback_eligible,
    "ipl_match_today": h_ipl_match_today,
    "review_theme_emerged": h_review_theme_emerged,
    "milestone_reached": h_milestone_reached,
    "active_planning_intent": h_active_planning_intent,
    "seasonal_perf_dip": h_seasonal_perf_dip,
    "customer_lapsed_soft": lambda c, m, t, cu: h_customer_lapsed(c, m, t, cu, hard=False),
    "customer_lapsed_hard": lambda c, m, t, cu: h_customer_lapsed(c, m, t, cu, hard=True),
    "dormant_with_vera": h_dormant_with_vera,
    "festival_upcoming": h_festival_upcoming,
    "gbp_unverified": h_gbp_unverified,
    "supply_alert": h_supply_alert,
    "category_seasonal": h_category_seasonal,
    "trial_followup": h_trial_followup,
    "wedding_package_followup": h_wedding_package_followup,
    "renewal_due": h_renewal_due,
    "perf_dip": h_perf_dip,
    "perf_spike": h_perf_spike,
    "recall_due": h_recall_due,
    "appointment_tomorrow": h_appointment_tomorrow,
}


def h_generic(category, merchant, trigger, customer):
    name = owner_name(merchant)
    kind = trigger.get("kind", "update").replace("_", " ")
    body = f"{name}, quick {kind} update on your account — want me to walk you through it?"
    return make(body, "open_ended", "vera" if not customer else "merchant_on_behalf", "Unrecognised trigger kind, generic but non-fabricated placeholder ask")


def compose(category, merchant, trigger, customer=None):
    handler = TRIGGER_HANDLERS.get(trigger.get("kind"), h_generic)
    result = handler(category, merchant, trigger, customer)
    result["suppression_key"] = trigger.get("suppression_key", "")
    return result


AUTO_REPLY_PHRASES = [
    "thank you for contacting",
    "we have received your message",
    "will get back to you",
    "aapki jaankari ke liye",
    "team tak pahuncha",
    "automated assistant",
    "this is an automated",
    "hamari team",
    "business hours",
    "currently unavailable",
]

NOT_INTERESTED_PHRASES = [
    "not interested", "stop", "no thanks", "nahi chahiye", "band karo", "unsubscribe",
]

INTENT_PHRASES = [
    "yes", "haan", "go ahead", "let's do it", "lets do it", "ok karo", "okay karo",
    "sure", "interested", "chalega", "kar do", "start karo", "proceed",
]

HOSTILE_WORDS = [
    "stupid", "useless", "bakwas", "chutiya", "nonsense", "scam", "fraud",
]


def is_auto_reply(state, message):
    lower = message.lower()
    if any(p in lower for p in AUTO_REPLY_PHRASES):
        return True
    history = [m for m in state.get("merchant_messages", [])]
    if len(history) >= 2 and history[-1] == message and history[-2] == message:
        return True
    return False


def is_not_interested(message):
    lower = message.lower()
    return any(p in lower for p in NOT_INTERESTED_PHRASES)


def is_intent(message):
    lower = message.lower().strip()
    return any(lower == p or lower.startswith(p + " ") or (" " + p) in (" " + lower) for p in INTENT_PHRASES)


def is_hostile(message):
    lower = message.lower()
    return any(w in lower for w in HOSTILE_WORDS)


def new_conversation_state(merchant_id, customer_id, category, merchant, trigger, customer):
    return {
        "merchant_id": merchant_id,
        "customer_id": customer_id,
        "category": category,
        "merchant": merchant,
        "trigger": trigger,
        "customer": customer,
        "turn_number": 0,
        "auto_reply_warned": False,
        "sent_bodies": [],
        "merchant_messages": [],
        "mode": "pitch",
    }


app = FastAPI()
START = time.time()

contexts: dict = {}
conversations: dict = {}
sent_suppression_keys: set = set()


def get_ctx(scope, context_id):
    entry = contexts.get((scope, context_id))
    return entry["payload"] if entry else None


def resolve_category_for_merchant(merchant):
    slug = merchant.get("category_slug")
    return get_ctx("category", slug) or {}


class CtxBody(BaseModel):
    scope: str
    context_id: str
    version: int
    payload: dict[str, Any]
    delivered_at: str


@app.post("/v1/context")
async def push_context(body: CtxBody):
    key = (body.scope, body.context_id)
    cur = contexts.get(key)
    if cur and cur["version"] >= body.version:
        return {"accepted": False, "reason": "stale_version", "current_version": cur["version"]}
    contexts[key] = {"version": body.version, "payload": body.payload}
    return {"accepted": True, "ack_id": f"ack_{body.context_id}_v{body.version}",
            "stored_at": datetime.now(timezone.utc).isoformat()}


class TickBody(BaseModel):
    now: str
    available_triggers: list[str] = []


@app.post("/v1/tick")
async def tick(body: TickBody):
    actions = []
    for trg_id in body.available_triggers:
        if len(actions) >= 20:
            break
        trigger = get_ctx("trigger", trg_id)
        if not trigger:
            continue
        if trigger.get("suppression_key") in sent_suppression_keys:
            continue
        merchant_id = trigger.get("merchant_id")
        merchant = get_ctx("merchant", merchant_id)
        if not merchant:
            continue
        category = resolve_category_for_merchant(merchant)
        customer_id = trigger.get("customer_id")
        customer = get_ctx("customer", customer_id) if customer_id else None
        composed = compose(category, merchant, trigger, customer)
        conversation_id = f"conv_{merchant_id}_{trg_id}"
        state = new_conversation_state(merchant_id, customer_id, category, merchant, trigger, customer)
        state["sent_bodies"].append(composed["body"])
        conversations[conversation_id] = state
        sent_suppression_keys.add(trigger.get("suppression_key"))
        actions.append({
            "conversation_id": conversation_id,
            "merchant_id": merchant_id,
            "customer_id": customer_id,
            "send_as": composed["send_as"],
            "trigger_id": trg_id,
            "template_name": f"vera_{trigger.get('kind')}_v1",
            "template_params": [owner_name(merchant)],
            "body": composed["body"],
            "cta": composed["cta"],
            "suppression_key": composed["suppression_key"],
            "rationale": composed["rationale"],
        })
    return {"actions": actions}


class ReplyBody(BaseModel):
    conversation_id: str
    merchant_id: Optional[str] = None
    customer_id: Optional[str] = None
    from_role: str
    message: str
    received_at: str
    turn_number: int


@app.post("/v1/reply")
async def reply(body: ReplyBody):
    from conversation_handlers import respond

    state = conversations.get(body.conversation_id)
    if not state:
        merchant = get_ctx("merchant", body.merchant_id) if body.merchant_id else None
        category = resolve_category_for_merchant(merchant) if merchant else {}
        customer = get_ctx("customer", body.customer_id) if body.customer_id else None
        state = new_conversation_state(body.merchant_id, body.customer_id, category, merchant or {}, {}, customer)
        conversations[body.conversation_id] = state
    result = respond(state, body.message)
    conversations[body.conversation_id] = state
    return result


@app.get("/v1/healthz")
async def healthz():
    counts = {"category": 0, "merchant": 0, "customer": 0, "trigger": 0}
    for (scope, _cid) in contexts.keys():
        counts[scope] = counts.get(scope, 0) + 1
    return {"status": "ok", "uptime_seconds": int(time.time() - START), "contexts_loaded": counts}


@app.get("/v1/metadata")
async def metadata():
    return {
        "team_name": "Kush Singh",
        "team_members": ["Kush Singh"],
        "model": "rule-based-composer-v1",
        "approach": "deterministic per-trigger-kind template composer over the 4-context framework, no external LLM call",
        "contact_email": "team@example.com",
        "version": "1.0.0",
        "submitted_at": datetime.now(timezone.utc).isoformat(),
    }


@app.post("/v1/teardown")
async def teardown():
    contexts.clear()
    conversations.clear()
    sent_suppression_keys.clear()
    return {"status": "ok"}
