#!/usr/bin/env python3
"""Render subscription-report.html from recurring.json + verdicts.json.

Usage:
  python3 render_report.py recurring.json verdicts.json [--out subscription-report.html] [--currency ILS]

One page shows one currency. When recurring.json has more than one, run it once per currency
with --currency, e.g. --currency ILS --out subscription-report-ILS.html. Shekels and dollars
are never added into one number.

recurring.json comes from find_recurring.py. verdicts.json is the only thing Claude writes:
per id a verdict, a display name and a one-line why (schema in SKILL.md, Step 6).
Every number on the page is computed here from recurring.json, and the big number uses the
same compute_total() as `find_recurring.py --total`, so the two can never disagree.
Cancel buttons come from references/cancel-links.json (official pages only).

Standard library only. It never cancels, logs in or sends anything.
"""
import argparse
import calendar
import colorsys
import hashlib
import html
import json
import re
import sys
import time
from datetime import date
from pathlib import Path
from urllib.parse import quote_plus, urlparse

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
from find_recurring import compute_total, currency_of, norm_currency  # noqa: E402  (the one place the total is calculated)

VERDICTS = ["CANCEL", "GET IT BACK", "NEGOTIATE", "DOWNGRADE", "ASK", "KEEP"]
BUCKETS = {"subscription": "Subscription", "bill": "Bill", "saving": "Saving", "yearly": "Yearly"}
VCLASS = {"CANCEL": "cut", "GET IT BACK": "cut", "NEGOTIATE": "neg", "DOWNGRADE": "neg", "ASK": "ask", "KEEP": "keep"}
BRAND = [  # monogram colors, matched on the start of the name or the cancel-link key
    ("netflix", "#E50914"), ("hulu", "#1CE783"), ("disney", "#113CCF"), ("max", "#002BE7"), ("hbo", "#5822B4"),
    ("paramount", "#0064FF"), ("peacock", "#111111"), ("apple", "#1D1D1F"), ("spotify", "#1DB954"),
    ("youtube", "#FF0000"), ("amazon", "#FF9900"), ("audible", "#F7991C"), ("kindle", "#232F3E"),
    ("google", "#4285F4"), ("dropbox", "#0061FE"), ("microsoft", "#0078D4"), ("xbox", "#107C10"),
    ("adobe", "#FA0F00"), ("canva", "#00C4CC"), ("linkedin", "#0A66C2"), ("new york times", "#121212"),
    ("nyt", "#121212"), ("wall street", "#121212"), ("washington post", "#121212"), ("uber", "#111111"),
    ("dashpass", "#FF3008"), ("doordash", "#FF3008"), ("instacart", "#0AAD0A"), ("grubhub", "#FF8000"),
    ("planet fitness", "#5C2D91"), ("orangetheory", "#F26722"), ("peloton", "#181A1D"), ("classpass", "#0055FF"),
    ("norton", "#FFC20E"), ("mcafee", "#C01818"), ("duolingo", "#58CC02"), ("calm", "#3A7BD5"),
    ("headspace", "#F47D31"), ("chatgpt", "#10A37F"), ("playstation", "#003791"), ("nintendo", "#E60012"),
    ("costco", "#E31837"), ("walmart", "#0071DC"), ("ring", "#1998D5"), ("siriusxm", "#0000EB"),
    ("chewy", "#1C49C2"), ("barkbox", "#0096D6"), ("hellofresh", "#91C11E"), ("roblox", "#232527"),
    ("abcmouse", "#F15A29"), ("verizon", "#CD040B"), ("spectrum", "#0071BC"), ("progressive", "#0077C8"),
    ("rocket", "#C8102E"), ("toyota", "#EB0A1E"), ("ymca", "#5C2E91"), ("teco", "#0057A8"),
]


# ---------- small helpers ----------

def esc(s):
    return html.escape(str(s if s is not None else ""), quote=True)


SYMBOLS = {"USD": "$", "ILS": "₪", "EUR": "€", "GBP": "£", "CAD": "CA$", "AUD": "A$"}
SYMBOL = "$"  # set per page in render()


def money(x):
    return f"{SYMBOL}{x:,.2f}"


def d(s):
    return date.fromisoformat(s) if s else None


def nice(dt):
    return f"{dt:%b} {dt.day}, {dt.year}" if dt else ""


def add_month(dt):
    y, m = (dt.year + 1, 1) if dt.month == 12 else (dt.year, dt.month + 1)
    return date(y, m, min(dt.day, calendar.monthrange(y, m)[1]))


def norm(s):
    return " ".join(re.sub(r"[^A-Z0-9]+", " ", str(s).upper()).split())


def initials(name):
    words = [w for w in re.split(r"[\s/]+", name) if w and w[0].isalpha()]
    if not words:
        return "?"
    first = words[0][0].upper()
    if len(words) > 1 and words[1][0].isupper():
        return first + words[1][0]
    return first


def brand_color(name, key=None):
    low = name.lower()
    for k, c in BRAND:
        if low.startswith(k) or (key and key.startswith(k.replace(" ", ""))):
            return c
    h = int(hashlib.md5(low.encode()).hexdigest()[:6], 16) / 0xFFFFFF
    r, g, b = colorsys.hls_to_rgb(h, 0.42, 0.55)
    return "#%02X%02X%02X" % (int(r * 255), int(g * 255), int(b * 255))


def ink_on(hexc):
    r, g, b = (int(hexc[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return "#0B1220" if 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.6 else "#FFFFFF"


def mono(name, key=None, size=""):
    c = brand_color(name, key)
    return (f'<span class="mono {size}" style="--c:{c};--ci:{ink_on(c)}" aria-hidden="true">'
            f'{esc(initials(name))}</span>')


def pill(verdict):
    if not verdict:
        return '<span class="pill v-none">Not reviewed</span>'
    return f'<span class="pill v-{VCLASS[verdict]}">{esc(verdict.title())}</span>'


def ids_tag(ids):
    return f'<span class="ids">{esc(" + ".join(ids))}</span>'


ARROW = ('<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path d="M5 11 11 5M6 5h5v5" '
         'fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>')
COPY = ('<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><rect x="5" y="5" width="8" height="8" '
        'rx="2" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M3 10V4a1 1 0 0 1 1-1h6" fill="none" '
        'stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>')


# ---------- cancel links ----------

class Links:
    def __init__(self, path):
        self.services, self.by_key, self.aliases = [], {}, []
        self.missing = not (path and Path(path).exists())
        if not self.missing:
            self.services = json.loads(Path(path).read_text(encoding="utf-8")).get("services", [])
        for s in self.services:
            key = s.get("key") or norm(s.get("name", "")).lower().replace(" ", "-")
            s["key"] = key
            self.by_key[key] = s
            for a in [s.get("name", "")] + list(s.get("aliases", [])):
                if norm(a):
                    self.aliases.append((norm(a), s))
        self.aliases.sort(key=lambda x: -len(x[0]))  # longest alias wins ("GOOGLE ONE" before "GOOGLE")

    def find(self, item):
        forced = item.get("link")
        if forced:
            return None if forced == "none" else self.by_key.get(forced)
        name = norm(item["name"])
        for a, s in self.aliases:  # 1. the display name is the service name or an alias
            if a == name:
                return s
        for text in (item.get("descriptor", ""), item.get("merchant", ""), item["name"]):
            padded = f" {norm(text)} "
            for a, s in self.aliases:  # 2. an alias appears as whole words in the descriptor
                if f" {a} " in padded:
                    return s
        return None


def action_link(item, label_cancel="Cancel", fallback_search=True):
    """Button to the official page, or a click path + clearly labelled search when there is none."""
    s = item.get("svc")
    if s and s.get("url"):
        label = "How to cancel" if s.get("kind") == "help" else label_cancel
        title = f'Opens {s["url"]}'
        return (f'<a class="btn btn-primary" href="{esc(s["url"])}" target="_blank" rel="noopener noreferrer" '
                f'title="{esc(title)}">{esc(label)} {ARROW}</a>')
    if not fallback_search:
        return ""
    q = quote_plus(f"how to cancel {item['name']}")
    return (f'<a class="btn" href="https://www.google.com/search?q={q}" target="_blank" rel="noopener noreferrer">'
            f'Search how to cancel {ARROW}</a>')


def how_text(item):
    how = item.get("how") or (item.get("svc") or {}).get("how")
    return f'<p class="how"><span>Where:</span> {esc(how)}</p>' if how else ""


def site(url):
    host = (urlparse(url or "").hostname or "").lower()
    return ".".join(host.split(".")[-2:]) if host else ""


def email_meta(item):
    """Optional facts from email receipts: which inbox the account is on, the plan name on the receipt."""
    bits = []
    if item.get("email_account"):
        bits.append(f'on <b>{esc(item["email_account"])}</b>')
    if item.get("plan_from_email"):
        bits.append(f'receipt says <b>{esc(item["plan_from_email"])}</b>')
    if not bits:
        return ""
    icon = ('<svg viewBox="0 0 16 16" width="13" height="13" aria-hidden="true"><rect x="1.8" y="3.2" width="12.4" '
            'height="9.6" rx="2" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="m2.5 4.5 5.5 4 5.5-4" '
            'fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/></svg>')
    return f'<p class="meta">{icon}<span>{" &middot; ".join(bits)}</span></p>'


# ---------- data ----------

def load_items(data, verdicts, links):
    vitems = verdicts.get("items", {})
    known = {s["id"] for s in data["recurring"]} | {a["id"] for a in data["possible_annual"]}
    unknown = [k for k in vitems if k not in known]
    if unknown:
        sys.exit(f"verdicts.json has id(s) that are not in recurring.json: {', '.join(unknown)}")
    items, missing = [], []
    for s in data["recurring"]:
        v = vitems.get(s["id"], {})
        flags = {f["flag"]: f for f in s["flags"]}  # one per kind; flag_list keeps repeats (duplicates)
        saving = s["bucket"] == "saving" or v.get("bucket") == "saving"
        verdict = (v.get("verdict") or ("KEEP" if saving else "")).upper().strip() or None
        bucket = "saving" if saving else (v.get("bucket") or ("bill" if s["bucket"] == "bill" else "subscription")).lower()
        items.append({
            "id": s["id"], "kind": "S", "merchant": s["merchant"], "descriptor": s.get("example_descriptor", ""),
            "name": v.get("name") or s["merchant"].title(), "verdict": verdict, "bucket": bucket,
            "why": v.get("why", ""), "group": v.get("group"), "how": v.get("how"), "link": v.get("link"),
            "message": v.get("message"), "script": v.get("script"),
            "email_account": v.get("email_account"), "plan_from_email": v.get("plan_from_email"),
            "cadence": s["cadence"], "amount": s["amount_now"], "monthly": s["monthly_cost"],
            "yearly": s["yearly_cost"], "next": d(s["next_expected"]), "flags": flags,
            "stopped": "stopped" in flags, "soon": "renews_soon" in flags, "flag_list": s["flags"],
            "saving_series": s["bucket"] == "saving",
        })
    for a in data["possible_annual"]:
        v = vitems.get(a["id"], {})
        verdict = (v.get("verdict") or "").upper().strip() or None
        items.append({
            "id": a["id"], "kind": "A", "merchant": a["merchant"], "descriptor": a.get("example_descriptor", ""),
            "name": v.get("name") or a["merchant"].title(), "verdict": verdict, "bucket": "yearly",
            "why": v.get("why", ""), "group": v.get("group"), "how": v.get("how"), "link": v.get("link"),
            "message": v.get("message"), "script": v.get("script"),
            "email_account": v.get("email_account"), "plan_from_email": v.get("plan_from_email"),
            "cadence": "yearly", "amount": a["amount"], "monthly": round(a["amount"] / 12, 2),
            "yearly": a["amount"], "next": d(a["next_if_yearly"]), "flags": {}, "stopped": False,
            "soon": bool(a.get("renews_within_30_days")), "charged": d(a.get("charged")), "flag_list": [],
            "saving_series": False,
        })
    for it in items:
        if it["verdict"] and it["verdict"] not in VERDICTS:
            sys.exit(f"{it['id']}: verdict must be one of {', '.join(VERDICTS)} (got {it['verdict']!r})")
        if it["bucket"] not in BUCKETS:
            sys.exit(f"{it['id']}: bucket must be subscription, bill or saving (got {it['bucket']!r})")
        if not it["verdict"]:
            missing.append(it["id"])
        it["svc"] = links.find(it)
    return items, missing


def check_texts(items):
    """Warn when a script or message does not carry the real prices from recurring.json."""
    warn = []
    for it in items:
        pi = it["flags"].get("price_increase")
        if it["verdict"] in ("NEGOTIATE", "DOWNGRADE") and pi and it.get("script"):
            for p in (pi["from"], pi["to"]):
                if f"{p:,.2f}" not in it["script"]:
                    warn.append(f"{it['id']} {it['name']}: call script does not mention {money(p)}")
        if it["verdict"] == "GET IT BACK" and it.get("message"):
            dup = [f for f in it["flag_list"] if f.get("flag") == "duplicate_charge"]
            amt = round(sum(f["amount"] for f in dup), 2) if dup else it["amount"]
            if f"{amt:,.2f}" not in it["message"]:
                warn.append(f"{it['id']} {it['name']}: refund message does not mention {money(amt)}")
        if it["verdict"] in ("CANCEL", "GET IT BACK") and (it["stopped"] or it["saving_series"] or it["bucket"] == "saving"):
            why = "a series that already stopped" if it["stopped"] else "a saving series"
            warn.append(f"{it['id']} {it['name']}: {it['verdict']} on {why} adds money that is not really back. Use KEEP or ASK.")
    return warn


# ---------- sections ----------

def section(sid, eyebrow, title, sub, body, extra_cls=""):
    sub_html = f'<p class="sec-sub">{sub}</p>' if sub else ""
    return (f'<section class="card {extra_cls}" id="{sid}" aria-labelledby="{sid}-h">'
            f'<header class="sec-head"><p class="eyebrow">{esc(eyebrow)}</p>'
            f'<h2 id="{sid}-h">{esc(title)}</h2>{sub_html}</header>{body}</section>')


def receipt(items, t, cut_yearly):
    """The big number, itemized: every cut and refund, biggest first, summing to the total."""
    by_name = {}
    for it in items:
        if it["verdict"] == "CANCEL":
            by_name.setdefault(it["name"], [0.0, it])[0] += cut_yearly[it["id"]]
    once = {ln["id"]: ln["once"] for ln in t["lines"] if ln["kind"] == "refund"}
    cuts = sorted(([round(v, 2), it, "cancel"] for v, it in by_name.values()), key=lambda x: -x[0])
    refs = [[round(once[i["id"]], 2), i, "refund"] for i in items if i["verdict"] == "GET IT BACK"]
    if not cuts and not refs:
        return ""
    shown, rest = (cuts, []) if len(cuts) + len(refs) <= 7 else (cuts[:5], cuts[5:])
    row = lambda v, it, unit: (f'<li>{mono(it["name"], (it.get("svc") or {}).get("key"), "mono-sm")}'
                               f'<span class="rc-name">{esc(it["name"])}<small>{esc(unit)}</small></span><b>{money(v)}</b></li>')
    lis = "".join(row(*x) for x in shown)
    if rest:
        lis += (f'<li class="rc-more"><span class="rc-name">{len(rest)} more to cancel</span>'
                f'<b>{money(round(sum(v for v, _, _ in rest), 2))}</b></li>')
    lis += "".join(row(*x) for x in refs)
    return (f'<aside class="receipt" aria-label="What makes up the number"><p class="rc-title">What makes up the number</p>'
            f'<ul>{lis}</ul><p class="rc-total"><span>Total</span><b>{money(t["total"])}</b></p></aside>')


def hero(data, items, t, cut_rows, refunds, cut_yearly):
    active = [i for i in items if i["kind"] == "S" and i["bucket"] != "saving" and not i["stopped"]]
    monthly_total = round(sum(i["monthly"] for i in active), 2)
    yearly_plans = [i for i in items if i["kind"] == "A"]
    neg = [i for i in items if i["verdict"] in ("NEGOTIATE", "DOWNGRADE")]
    went_up = [i for i in neg if "price_increase" in i["flags"]]
    neg_extra = round(sum(i["flags"]["price_increase"]["extra_per_year"] for i in went_up), 2)
    n_cut, n_ref = len(cut_rows), len(refunds)
    plural = lambda n, w: f"{n} {w}{'' if n == 1 else 's'}"
    parts = []
    if t["monthly"]:
        parts.append(f"{money(t['monthly'])} a month in plans you cut ({money(t['monthly'] * 12)} a year)")
    if t["yearly_only"]:
        parts.append(f"{money(t['yearly_only'])} in yearly fees")
    if t["once"]:
        parts.append(f"{money(t['once'])} back as {'a refund' if n_ref == 1 else 'refunds'}")
    made_of = ""
    if parts:
        joined = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]
        made_of = f'<p class="hero-made">That is {joined}.</p>'
    act = []
    if n_cut:
        act.append(f"cut {n_cut}")
    if n_ref:
        act.append(f"claim {plural(n_ref, 'refund')}")
    act_txt = (" and ".join(act)).capitalize()
    lead = (f"You pay <b>{money(monthly_total)} a month</b> across {plural(len(active), 'recurring charge')}"
            f"{', plus ' + plural(len(yearly_plans), 'yearly plan') if yearly_plans else ''}. ")
    lead += f"{act_txt}, and this money stays with you." if act else "Nothing to cut this time."
    on_top = ""
    if went_up:
        on_top = (f'<p class="hero-ontop"><span class="dot dot-neg"></span>Not counted: '
                  f'{plural(len(went_up), "price")} went up by {money(neg_extra)} a year combined. '
                  f'A phone call may win some of it back.</p>')
    elif neg:
        on_top = (f'<p class="hero-ontop"><span class="dot dot-neg"></span>Not counted: '
                  f'{plural(len(neg), "bill")} worth a phone call.</p>')
    p0, p1 = d(data["period"][0]), d(data["period"][1])
    long_cls = " hero-num-long" if t["total"] >= 10000 else ""
    sym_attr = f' data-symbol="{esc(SYMBOL)}"' if SYMBOL != "$" else ""
    return f'''
<section class="hero" aria-label="The result">
  <div class="hero-glow" aria-hidden="true"></div>
  <div class="hero-main">
  <p class="hero-eyebrow">Subscription Hunt &middot; {esc(nice(p0))} to {esc(nice(p1))}</p>
  <p class="hero-kicker">You can get back</p>
  <p class="hero-num{long_cls}"><span class="countup" data-value="{t['total']:.2f}"{sym_attr}>{money(t['total'])}</span></p>
  <p class="hero-kicker hero-kicker-after">this year</p>
  <p class="hero-lead">{lead}</p>
  {made_of}
  {on_top}
  </div>
  {receipt(items, t, cut_yearly)}
</section>''', monthly_total


def spend_bar(items, monthly_total, t):
    rows = []
    sets = [("All recurring charges", [i for i in items if i["kind"] == "S" and i["bucket"] != "saving" and not i["stopped"]]),
            ("Subscriptions only", [i for i in items if i["kind"] == "S" and i["bucket"] == "subscription" and not i["stopped"]])]
    legend_names = {"keep": "Keep", "neg": "Negotiate", "ask": "Your call", "cut": "Cut"}
    for label, group in sets:
        if not group:
            continue
        sums = {"keep": 0.0, "neg": 0.0, "ask": 0.0, "cut": 0.0}
        for i in group:
            cls = "cut" if i["verdict"] == "CANCEL" else ("keep" if i["verdict"] in (None, "KEEP", "GET IT BACK")
                                                         else VCLASS[i["verdict"]])
            sums[cls] += i["monthly"]
        tot = sum(sums.values())
        segs, legend = [], []
        for k in ("keep", "neg", "ask", "cut"):
            v = round(sums[k], 2)
            if v <= 0:
                continue
            pct = max(v / tot * 100, 0.8)
            segs.append(f'<span class="seg seg-{k}" style="width:{pct:.3f}%" title="{legend_names[k]}: {money(v)} a month"></span>')
            legend.append(f'<li><span class="dot dot-{k}"></span>{legend_names[k]} <b>{money(v)}</b></li>')
        rows.append(f'''
<div class="bar-row">
  <div class="bar-label"><span>{esc(label)}</span><b>{money(round(tot, 2))}<small> / month</small></b></div>
  <div class="bar" role="img" aria-label="{esc(label)}: {money(round(tot, 2))} a month">{"".join(segs)}</div>
  <ul class="legend">{"".join(legend)}</ul>
</div>''')
    if not rows:
        return ""
    sub = (f"Cutting takes {money(t['monthly'])} a month off. The gray part is what stays, and that is fine."
           if t["monthly"] else "")
    return section("spend", "Every month", "Where your recurring money goes", esc(sub), "".join(rows))


def chip_state(members):
    vs = {m["verdict"] for m in members}
    if "CANCEL" in vs:
        return "cut"
    if "ASK" in vs:
        return "ask"
    return "keep"


def price_text(members):
    s = [m for m in members if m["kind"] == "S"]
    a = [m for m in members if m["kind"] == "A"]
    parts = [f"{money(m['amount'] if m['cadence'] == 'monthly' else m['monthly'])}/mo" for m in s]
    parts += [f"{money(m['amount'])}/yr" for m in a]
    return " + ".join(parts)


def overlap_groups(items, cut_yearly):
    groups = {}
    for it in items:
        if it["group"] and it["bucket"] != "saving":
            groups.setdefault(it["group"], {}).setdefault(it["name"], []).append(it)
    cards = []
    for g, by_name in groups.items():
        if len(by_name) < 2:
            continue
        chips, saves, total = [], 0.0, 0.0
        order = {"keep": 0, "ask": 1, "cut": 2}
        entries = sorted(by_name.items(), key=lambda kv: (order[chip_state(kv[1])], -sum(m["yearly"] for m in kv[1])))
        for name, members in entries:
            st = chip_state(members)
            yearly = round(sum(m["yearly"] for m in members), 2)
            total += yearly
            ids = [m["id"] for m in members]
            tag = {"keep": "Keep", "ask": "Your call", "cut": "Cut"}[st]
            foot = f'<span class="chip-save">saves {money(round(sum(cut_yearly.get(i, 0) for i in ids), 2))}/yr</span>' if st == "cut" else ""
            if st == "cut":
                saves += sum(cut_yearly.get(i, 0) for i in ids)
            chips.append(f'''
<li class="chip chip-{st}">
  {mono(name, (members[0].get("svc") or {}).get("key"))}
  <div class="chip-body"><span class="chip-name">{esc(name)}</span><span class="chip-price">{esc(price_text(members))}</span>{foot}</div>
  <span class="chip-tag">{tag}</span>
</li>''')
        n = len(by_name)
        saves = round(saves, 2)
        verdict_line = (f'<span class="save-pill">Cut {sum(1 for _, m in entries if chip_state(m) == "cut")}, '
                        f'save {money(saves)} a year</span>') if saves else '<span class="save-pill save-none">Your call, see the questions</span>'
        wide = " group-wide" if n > 3 else ""
        cards.append((saves, f'''
<article class="group{wide}">
  <header class="group-head"><h3>{esc(g)}</h3><p>{n} services, {money(round(total, 2))} a year</p></header>
  <ul class="chips">{"".join(chips)}</ul>
  <footer class="group-foot">{verdict_line}</footer>
</article>'''))
    if not cards:
        return ""
    cards.sort(key=lambda c: -c[0])
    return section("overlap", "Doing the same job", "You pay twice for the same thing",
                   "Grouped by the job they do, not by name. The highlighted one stays.",
                   f'<div class="groups">{"".join(c for _, c in cards)}</div>')


def cut_list(items, t, cut_yearly):
    by_name = {}
    for it in items:
        if it["verdict"] == "CANCEL":
            by_name.setdefault(it["name"], []).append(it)
    rows = []
    for name, members in by_name.items():
        yearly = round(sum(cut_yearly[m["id"]] for m in members), 2)
        s = [m for m in members if m["kind"] == "S"]
        a = [m for m in members if m["kind"] == "A"]
        per_month = " + ".join([money(m["monthly"]) for m in s] + [f"{money(m['amount'])} yearly" for m in a]) \
            if s else "yearly"
        lead = s[0] if s else members[0]
        rows.append((yearly, f'''
<li class="row">
  {mono(name, (lead.get("svc") or {}).get("key"), "mono-lg")}
  <div class="row-main"><p class="row-name">{esc(name)} {ids_tag([m["id"] for m in members])}</p>
    <p class="row-why">{esc(lead["why"])}</p>{how_text(lead)}{email_meta(lead)}</div>
  <p class="num" data-label="Per month">{esc(per_month)}</p>
  <p class="num num-strong" data-label="Per year">{money(yearly)}</p>
  <div class="row-act">{action_link(lead)}</div>
</li>''', len(members)))
    rows.sort(key=lambda r: -r[0])
    body = "".join(r[1] for r in rows)
    refunds = [i for i in items if i["verdict"] == "GET IT BACK"]
    once_by_id = {ln["id"]: ln["once"] for ln in t["lines"] if ln["kind"] == "refund"}
    for it in refunds:
        msg_id = f"msg-{it['id']}"
        msg = it.get("message") or ""
        copy_btn = (f'<button class="btn btn-money" type="button" data-copy="{msg_id}">{COPY}<span>Copy message</span></button>'
                    if msg else "")
        details = (f'<details class="script"><summary>Show the message</summary><p id="{msg_id}">{esc(msg)}</p></details>'
                   if msg else "")
        open_link = ""  # no link here: the official link is a cancel page, and a refund keeps the plan
        body += f'''
<li class="row row-refund">
  {mono(it["name"], (it.get("svc") or {}).get("key"), "mono-lg")}
  <div class="row-main"><p class="row-name">{esc(it["name"])} {ids_tag([it["id"]])} <span class="pill v-cut">Refund</span></p>
    <p class="row-why">{esc(it["why"])}</p>{email_meta(it)}</div>
  <p class="num" data-label="Per month">one time</p>
  <p class="num num-strong" data-label="Back">{money(once_by_id[it["id"]])}</p>
  <div class="row-act">{copy_btn}{open_link}</div>
  {f'<div class="row-extra">{details}</div>' if details else ""}
</li>'''
    if not body:
        return "", [], []
    head = ('<li class="row row-head" aria-hidden="true"><span></span><span>Service</span>'
            '<span class="num">Per month</span><span class="num">Per year</span><span></span></li>')
    foot = (f'<div class="list-total"><span>Total you get back this year</span>'
            f'<b>{money(t["total"])}</b></div>')
    official = any((i.get("svc") or {}).get("url") for i in items if i["verdict"] == "CANCEL")
    html_ = section("cut", "Cut list", "Cancel these, keep the money",
                    "Each Cancel button opens the company's own page in a new tab. You click, you confirm."
                    if official else "Each button opens a search for how to cancel. You click, you confirm.",
                    f'<ul class="rows">{head}{body}</ul>{foot}')
    return html_, rows, refunds


def negotiate(items):
    neg = [i for i in items if i["verdict"] in ("NEGOTIATE", "DOWNGRADE")]
    neg.sort(key=lambda i: -(i["flags"].get("price_increase", {}).get("extra_per_year", 0)))
    rows = []
    for it in neg:
        pi = it["flags"].get("price_increase")
        if pi:
            change = f'<span class="from">{money(pi["from"])}</span><span class="arrow">&rarr;</span><b>{money(pi["to"])}</b>'
            since = esc(nice(d(pi["since"])))
            extra = f'+{money(pi["extra_per_year"])}'
        else:
            change, since, extra = f'<b>{money(it["amount"])}</b>', "", ""
        sid = f"script-{it['id']}"
        script = it.get("script") or ""
        copy_btn = (f'<button class="btn btn-neg" type="button" data-copy="{sid}">{COPY}<span>Copy call script</span></button>'
                    if script else "")
        details = (f'<details class="script"><summary>Show the call script</summary><p id="{sid}">{esc(script)}</p></details>'
                   if script else "")
        manage = ""
        if it.get("svc") and it["svc"].get("url"):
            manage = (f'<a class="link" href="{esc(it["svc"]["url"])}" target="_blank" rel="noopener noreferrer">'
                      f'Open account {ARROW}</a>')
        rows.append(f'''
<li class="row row-neg">
  {mono(it["name"], (it.get("svc") or {}).get("key"), "mono-lg")}
  <div class="row-main"><p class="row-name">{esc(it["name"])} {ids_tag([it["id"]])} {pill(it["verdict"])}</p>
    <p class="row-why">{esc(it["why"])}</p>{email_meta(it)}</div>
  <p class="num price-change" data-label="Price">{change}</p>
  <p class="num" data-label="Since">{since}</p>
  <p class="num num-neg" data-label="Extra per year">{extra}</p>
  <div class="row-act">{copy_btn}{manage}</div>
  {f'<div class="row-extra">{details}</div>' if details else ""}
</li>''')
    also = []
    for it in items:
        pi = it["flags"].get("price_increase")
        if pi and it["verdict"] == "KEEP":
            also.append(f'{esc(it["name"])} ({money(pi["from"])} to {money(pi["to"])}, +{money(pi["extra_per_year"])} a year)')
    also_html = f'<p class="note">Also went up, and still worth it: {"; ".join(also)}.</p>' if also else ""
    if not rows and not also:
        return ""
    head = ('<li class="row row-neg row-head" aria-hidden="true"><span></span><span>Bill</span><span class="num">Price</span>'
            '<span class="num">Since</span><span class="num">Extra per year</span><span></span></li>')
    body = f'<ul class="rows">{head}{"".join(rows)}</ul>' if rows else ""
    return section("negotiate", "Call and negotiate", "Prices that went up",
                   "Not in the big number. Call, ask for the loyalty or retention rate, or shop around.",
                   body + also_html)


def renewals(items, today):
    yr = [i for i in items if (i["kind"] == "A" or i["cadence"] in ("yearly", "quarterly")) and not i["stopped"] and i["next"]]
    if not yr:
        return ""
    yr.sort(key=lambda i: i["next"])
    span = 365
    # Month ticks
    ticks = []
    m = date(today.year + (today.month == 12), today.month % 12 + 1, 1)
    while (m - today).days < span:
        pct = (m - today).days / span * 100
        lab = f"{m:%b}" + (f" {m.year}" if m.month == 1 else "")
        if pct < 6:  # too close to the Today marker
            m = date(m.year + (m.month == 12), m.month % 12 + 1, 1)
            continue
        ticks.append(f'<span class="tl-tick" style="left:{pct:.2f}%"><i></i>{esc(lab)}</span>')
        m = date(m.year + (m.month == 12), m.month % 12 + 1, 1)
    # Place labels in lanes so they never overlap (width estimate in % of the track)
    lanes = {}  # lane index -> right edge pct
    dots, lane_max = [], 0
    for it in yr:
        days = (it["next"] - today).days
        pct = min(max(days / span * 100, 0), 100)
        w = 15.0
        lane = 0
        order = [0, 1, 2, 3, 4, 5]  # 0,2,4 above; 1,3,5 below
        for ln in order:
            if lanes.get(ln, -100) < pct - w / 2:
                lane = ln
                break
        lanes[lane] = pct + w / 2
        lane_max = max(lane_max, lane)
        side = "up" if lane % 2 == 0 else "down"
        level = lane // 2
        st = "cut" if it["verdict"] == "CANCEL" else ("soon" if 0 <= days <= 30 else "later")
        anchor = "left" if pct < 7 else ("right" if pct > 93 else "mid")
        dots.append(f'''<div class="tl-dot tl-{st} tl-{side} tl-l{level} tl-a-{anchor}" style="left:{pct:.2f}%">
  <span class="tl-pin"></span><span class="tl-label"><b>{esc(it["name"])}</b><small>{esc(f"{it['next']:%b} {it['next'].day}")} &middot; {money(it["amount"])}</small></span></div>''')
    levels = lane_max // 2 + 1
    track = (f'<div class="tl" style="--levels:{levels}"><div class="tl-line"></div>'
             f'<span class="tl-today"><i></i>Today</span>{"".join(ticks)}{"".join(dots)}</div>')
    rows = []
    for it in yr:
        days = (it["next"] - today).days
        if days < 0:
            when = f'<span class="when when-past">date passed, check</span>'
        elif days <= 30:
            when = f'<span class="when when-soon">in {days} day{"s" if days != 1 else ""}</span>'
        else:
            when = f'<span class="when">in {days} days</span>'
        rows.append(f'''
<li class="rn {'rn-soon' if 0 <= days <= 30 else ''}">
  <p class="rn-date"><b>{esc(f"{it['next']:%b} {it['next'].day}")}</b><small>{it['next'].year}</small></p>
  {mono(it["name"], (it.get("svc") or {}).get("key"))}
  <div class="rn-main"><p class="row-name">{esc(it["name"])} {ids_tag([it["id"]])} {pill(it["verdict"])}</p>
    <p class="row-why">{esc(it["why"])}</p>{email_meta(it)}</div>
  <p class="num num-strong">{money(it["amount"])}{when}</p>
</li>''')
    soon = [i for i in yr if 0 <= (i["next"] - today).days <= 30]
    sub = (f"{len(soon)} {'plan renews' if len(soon) == 1 else 'plans renew'} in the next 30 days. Decide before the date, not after."
           if soon else "Nothing renews in the next 30 days.")
    if any(i["kind"] == "A" for i in yr):
        sub += " A yearly plan seen once is expected on the same date next year."
    return section("renewals", "Renewing soon", "Yearly plans, the next 12 months", esc(sub),
                   f'{track}<ul class="rn-list">{"".join(rows)}</ul>')


def questions(items, extra):
    ask = [i for i in items if i["verdict"] == "ASK"]
    lis = []
    for it in ask:
        if it["kind"] == "A":
            price = f"{money(it['amount'])} a year, next {nice(it['next'])}"
        else:
            price = f"{money(it['monthly'])} a month"
        link = action_link(it, "Manage", fallback_search=False)
        lis.append(f'''
<li class="q">
  {mono(it["name"], (it.get("svc") or {}).get("key"))}
  <div class="q-main"><p class="row-name">{esc(it["name"])} {ids_tag([it["id"]])} <span class="q-price">{esc(price)}</span></p>
    <p class="row-why">{esc(it["why"])}</p>{email_meta(it)}</div>
  <div class="row-act">{link}</div>
</li>''')
    for q in extra or []:
        q = q.get("text", "") if isinstance(q, dict) else q
        lis.append(f'<li class="q q-text"><span class="q-icon" aria-hidden="true">?</span><div class="q-main"><p class="row-why">{esc(q)}</p></div></li>')
    if not lis:
        return ""
    return section("questions", "Questions for you", "Only you know these",
                   "I do not guess what a charge is. One answer each and the list is done.",
                   f'<ul class="qs">{"".join(lis)}</ul>')


def found_in_email(entries, links):
    """Plans seen only in email receipts. Never in the total: the statements are the source of truth."""
    if not entries:
        return ""
    lis = []
    for e in entries:
        name = e.get("name") or "Unknown service"
        svc = links.find({"name": name, "descriptor": e.get("plan", ""), "merchant": ""})
        item = {"name": name, "svc": svc}
        btn = action_link(item, "Manage")  # official links file only; a link copied from an email is never used
        price = e.get("price")
        # A receipt keeps its own currency: "₪49.90" on a dollar page stays ₪49.90.
        sym = next((c for c in "$₪€£" if c in str(price or "")), None) or (
            SYMBOLS.get(norm_currency(str(e["currency"])) or "") if e.get("currency") else None)
        try:
            price = float(re.sub(r"[$₪€£,\s]", "", str(price))) if price not in (None, "") else None
        except ValueError:
            pass
        per = {"monthly": "month", "yearly": "year", "annual": "year", "annually": "year", "weekly": "week"}.get(
            str(e.get("cadence") or "month").lower(), str(e.get("cadence") or "month"))
        shown = (f"{sym}{price:,.2f}" if sym else money(price)) if isinstance(price, float) else ""
        price_txt = f"{shown} a {per} on the receipt" if shown else str(price or "")
        when = ""
        if e.get("date"):
            try:
                when = f"last receipt {nice(date.fromisoformat(str(e['date'])[:10]))}"
            except ValueError:
                when = f"last receipt {e['date']}"
        bits = [x for x in (price_txt, when) if x]
        meta = email_meta({"email_account": e.get("inbox"), "plan_from_email": e.get("plan")})
        lis.append(f'''
<li class="q">
  {mono(name, (svc or {}).get("key"))}
  <div class="q-main"><p class="row-name">{esc(name)} <span class="pill v-ask">Ask</span> <span class="q-price">{esc(", ".join(bits))}</span></p>
    <p class="row-why">{esc(e.get("why") or "Not on the statements I read. Probably billed to another card.")}</p>{meta}</div>
  <div class="row-act">{btn}</div>
</li>''')
    return section("email", "Found in your email", "Plans on another card",
                   "These receipts match none of the statements I read, so they are not in the big number. Still yours?",
                   f'<ul class="qs">{"".join(lis)}</ul>')


def keeping(items, note):
    subs = [i for i in items if i["verdict"] == "KEEP" and i["bucket"] in ("subscription", "yearly")]
    bills = [i for i in items if i["verdict"] in ("KEEP",) and i["bucket"] == "bill"]
    saving = [i for i in items if i["bucket"] == "saving"]
    seen, chips = set(), []
    for it in sorted(subs, key=lambda i: -i["yearly"]):
        if it["name"] in seen:
            continue
        seen.add(it["name"])
        price = f"{money(it['amount'])}/yr" if it["kind"] == "A" else f"{money(it['monthly'])}/mo"
        chips.append(f'<li class="kchip">{mono(it["name"], (it.get("svc") or {}).get("key"), "mono-sm")}'
                     f'<span>{esc(it["name"])}</span><small>{esc(price)}</small></li>')
    parts = []
    if note:
        parts.append(f'<p class="keep-note">{esc(note)}</p>')
    if chips:
        parts.append(f'<ul class="kchips">{"".join(chips)}</ul>')
    if bills:
        parts.append(f'<p class="note"><b>Bills checked, no change:</b> {esc(", ".join(b["name"] for b in bills))}.</p>')
    if saving:
        sv = round(sum(s["monthly"] for s in saving), 2)
        names = ", ".join(s["name"] for s in saving)
        parts.append(f'<p class="best"><span class="best-tag">Best money on the statement</span>'
                     f'{esc(names)}: {money(sv)} a month into savings. Keep it going.</p>')
    if not parts:
        return ""
    return section("keeping", "Keeping", "These earn their place", "", "".join(parts))


def everything(items, today):
    rows = []
    for it in items:
        if it["stopped"]:
            nxt_txt, nxt_sort = "stopped", "9999-12-31"
        else:
            nxt_txt, nxt_sort = nice(it["next"]), str(it["next"])
        every = "yearly, one charge seen" if it["kind"] == "A" else it["cadence"]
        vorder = len(VERDICTS) - VERDICTS.index(it["verdict"]) if it["verdict"] else 0
        rows.append(f'''<tr>
<td data-sort="{esc(it['name'].lower())}"><span class="cell-name">{mono(it["name"], (it.get("svc") or {}).get("key"), "mono-sm")}<span>{esc(it["name"])}<small>{esc(it["id"])} &middot; {esc(it["descriptor"])}{(" &middot; on " + esc(it["email_account"])) if it.get("email_account") else ""}</small></span></span></td>
<td data-sort="{esc(it['bucket'])}">{esc(BUCKETS[it['bucket']])}</td>
<td data-sort="{esc(every)}">{esc(every)}</td>
<td class="num" data-sort="{it['monthly']:.2f}">{money(it['monthly'])}</td>
<td class="num" data-sort="{it['yearly']:.2f}">{money(it['yearly'])}</td>
<td class="num" data-sort="{nxt_sort}">{esc(nxt_txt)}</td>
<td data-sort="{vorder}">{pill(it['verdict'])}</td>
</tr>''')
    cols = [("Service", "text"), ("Type", "text"), ("Every", "text"), ("Per month", "num"), ("Per year", "num"),
            ("Next charge", "text"), ("Verdict", "num")]
    ths = "".join(f'<th scope="col" class="{"num" if k == "num" and n not in ("Verdict",) else ""}"><button type="button" data-col="{i}" data-type="{k}">{esc(n)}<span class="sort-ind" aria-hidden="true"></span></button></th>'
                  for i, (n, k) in enumerate(cols))
    table = (f'<div class="table-wrap"><table class="all" id="all-table"><thead><tr>{ths}</tr></thead>'
             f'<tbody>{"".join(rows)}</tbody></table></div>')
    n = len(items)
    return (f'<details class="card everything" id="everything"><summary><span><span class="eyebrow">Everything I found</span>'
            f'<span class="sum-title">All {n} recurring charges and yearly plans</span><span class="sec-sub">Click a column to sort. '
            f'Per month for a yearly plan is the yearly price divided by 12.</span></span><span class="chev" aria-hidden="true"></span></summary>'
            f'{table}</details>')


# ---------- main ----------

def for_currency(data, verdicts, currency):
    """Keep only what belongs on this currency's page. Questions, email finds and the keeping line
    may carry a "currency" to sit on one page; without one they show on every page."""
    all_ids = {e["id"] for e in data["recurring"] + data["possible_annual"]}
    unknown = [k for k in verdicts.get("items", {}) if k not in all_ids]
    if unknown:
        sys.exit(f"verdicts.json has id(s) that are not in recurring.json: {', '.join(unknown)}")
    mine = lambda e: currency_of(e) == currency  # noqa: E731
    data = dict(data, recurring=[s for s in data["recurring"] if mine(s)],
                possible_annual=[a for a in data["possible_annual"] if mine(a)],
                near_misses=[n for n in data.get("near_misses", []) if mine(n)])
    sub = (data.get("by_currency") or {}).get(currency)
    if sub:
        data.update(period=sub["period"], transactions=sub["transactions"], files=sub["files"])
    ids = {e["id"] for e in data["recurring"] + data["possible_annual"]}
    cur_of = lambda c: norm_currency(str(c)) or str(c).upper()  # noqa: E731  ("NIS", "₪", "ils" -> ILS)
    here = lambda e: not isinstance(e, dict) or not e.get("currency") or cur_of(e["currency"]) == currency  # noqa: E731
    keep = verdicts.get("keeping")
    if isinstance(keep, dict):
        keep = {cur_of(k): v for k, v in keep.items()}
    verdicts = dict(verdicts, items={k: v for k, v in verdicts.get("items", {}).items() if k in ids},
                    questions=[q for q in verdicts.get("questions") or [] if here(q)],
                    found_in_email=[e for e in verdicts.get("found_in_email") or [] if here(e)],
                    keeping=keep.get(currency) if isinstance(keep, dict) else keep)
    return data, verdicts


def render(recurring_path, verdicts_path, out_path, links_path, currency=None):
    global SYMBOL
    t0 = time.perf_counter()
    data = json.loads(Path(recurring_path).read_text(encoding="utf-8"))
    verdicts = json.loads(Path(verdicts_path).read_text(encoding="utf-8"))
    if isinstance(verdicts.get("questions"), str):
        verdicts["questions"] = [verdicts["questions"]]
    curs = data.get("currencies") or sorted({currency_of(e) for e in data["recurring"] + data["possible_annual"]}) or ["USD"]
    if currency:
        currency = currency.upper()
        if currency not in curs:
            sys.exit(f"--currency {currency}: recurring.json only has {', '.join(curs)}")
    elif len(curs) > 1:
        sys.exit(f"recurring.json has {len(curs)} currencies ({', '.join(curs)}). They are never added together, "
                 f"so render one page per currency, e.g. --currency {curs[0]} --out subscription-report-{curs[0]}.html")
    else:
        currency = curs[0]
    data, verdicts = for_currency(data, verdicts, currency)
    SYMBOL = SYMBOLS.get(currency, f"{currency} ")
    links = Links(links_path)
    items, missing = load_items(data, verdicts, links)
    today = d(data.get("today")) or d(data["period"][1])

    cancel_ids = [i["id"] for i in items if i["verdict"] == "CANCEL"]
    refund_ids = [i["id"] for i in items if i["verdict"] == "GET IT BACK"]
    t = compute_total(data, cancel_ids, refund_ids)
    cut_yearly = {ln["id"]: ln["yearly"] for ln in t["lines"] if ln["kind"] == "cancel"}

    cut_html, cut_rows, refunds = cut_list(items, t, cut_yearly)
    hero_html, monthly_total = hero(data, items, t, cut_rows, refunds, cut_yearly)
    nav = [("cut", "Cut list"), ("overlap", "Same job"), ("negotiate", "Negotiate"), ("renewals", "Renewals"),
           ("questions", "Questions"), ("email", "Email"), ("everything", "Everything")]
    body_parts = [
        hero_html,
        spend_bar(items, monthly_total, t),
        overlap_groups(items, cut_yearly),
        cut_html,
        negotiate(items),
        renewals(items, today),
        questions(items, verdicts.get("questions")),
        found_in_email(verdicts.get("found_in_email"), links),
        keeping(items, verdicts.get("keeping")),
        everything(items, today),
    ]
    body = "\n".join(p for p in body_parts if p)
    nav_html = "".join(f'<a href="#{k}">{esc(v)}</a>' for k, v in nav if f'id="{k}"' in body)
    p0, p1 = d(data["period"][0]), d(data["period"][1])
    files = ", ".join(data.get("files", []))
    foot = (f'Subscription Hunter never cancels, logs in, calls or pays anything. You act, it prepares. '
            f'Every number on this page comes from find_recurring.py ({esc(data.get("transactions", ""))} transactions in {esc(files)}). '
            f'Hunt date {esc(nice(today))}. Next hunt {esc(nice(add_month(today)))}.')
    tpl = (ROOT / "assets" / "report-template.html").read_text(encoding="utf-8")
    period = f"{nice(p0)} to {nice(p1)}" + (f" \u00b7 {currency}" if len(curs) > 1 else "")
    fill = {"PERIOD": esc(period), "NAV": nav_html, "BODY": body, "FOOTER": foot}
    page = re.sub(r"\{\{(PERIOD|NAV|BODY|FOOTER)\}\}", lambda m: fill[m.group(1)], tpl)
    Path(out_path).write_text(page, encoding="utf-8")
    ms = (time.perf_counter() - t0) * 1000

    print(f"Wrote {out_path} in {ms:.0f} ms")
    if links.missing:
        print(f"WARNING no cancel links file at {links_path}, so every button is a search link", file=sys.stderr)
    tag = f" ({currency})" if len(curs) > 1 else ""
    print(f"TOTAL RECOVERABLE (first year){tag}: {t['total']:.2f}  (same compute_total as --total, "
          f"cancel {','.join(cancel_ids) or '-'} refund {','.join(refund_ids) or '-'})")
    no_link = sorted({i["name"] for i in items if i["verdict"] == "CANCEL" and not (i.get("svc") or {}).get("url")})
    if no_link:
        print(f"No official cancel link for: {', '.join(no_link)} (shows a search link instead)")
    if missing:
        print(f"WARNING no verdict for: {', '.join(missing)} (shown as 'Not reviewed')", file=sys.stderr)
    for w in check_texts(items):
        print(f"WARNING {w}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(description="Render the subscription report page.")
    ap.add_argument("recurring")
    ap.add_argument("verdicts")
    ap.add_argument("--out", default="subscription-report.html")
    ap.add_argument("--links", default=str(ROOT / "references" / "cancel-links.json"))
    ap.add_argument("--currency", help="which currency this page shows (needed when recurring.json has several)")
    a = ap.parse_args()
    render(a.recurring, a.verdicts, a.out, a.links, a.currency)


if __name__ == "__main__":
    main()
