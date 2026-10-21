#!/usr/bin/env python3
"""Find every recurring charge in bank and card exports. All the math lives here.

Usage:
  python3 find_recurring.py FILE.csv [FILE2.csv ...] [--out recurring.json] [--today YYYY-MM-DD]
  python3 find_recurring.py --total recurring.json --cancel S03,S07 [--refund S12]

What it does:
  1. Reads any CSV export: finds the date, description and amount columns by name,
     and works out which sign means money going out (the sign most rows share).
  2. Skips money coming in, card payments and transfers between your own accounts.
  3. Groups charges by cleaned-up merchant name and finds the ones that repeat on a
     schedule: weekly, every 2 weeks, monthly, quarterly, yearly.
  4. Flags: price increases, duplicate charges, recently started (often a free trial
     that turned paid), stopped, renewing in the next 30 days, cryptic names
     (APPLE.COM/BILL, PAYPAL *, GOOGLE *) and one-off charges that look like a yearly plan.
  5. --total adds up what cancelling a list of series saves, per month and per year,
     plus one-time refunds. Never do this math by hand.

Standard library only. It never changes, sends or cancels anything.
"""
import argparse
import csv
import json
import re
import statistics
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

DATE_FORMATS = ["%m/%d/%Y", "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%y", "%d.%m.%Y", "%Y/%m/%d", "%d-%m-%Y", "%b %d, %Y"]
SKIP = re.compile(r"PAYMENT THANK|AUTOPAY PAYMENT|PAYMENT TO .*(VISA|CARD|AMEX|MASTERCARD|DISCOVER)|"
                  r"TRANSFER (TO|FROM)|ONLINE TRANSFER|CREDIT CARD PAYMENT|INTERNAL TRANSFER|"
                  r"ATM WITHDRAWAL|CASH WITHDRAWAL|^ATM ", re.I)
PROCESSORS = re.compile(r"APPLE\.COM/BILL|ITUNES|PAYPAL|GOOGLE \*|GOOGLE\*|^SQ \*|SQ\*|AMZN DIGITAL|"
                        r"AMAZON DIGITAL|MSFT|MICROSOFT\*|2CO\.COM|PADDLE|FS \*|DRI\*", re.I)
ANNUAL_HINT = re.compile(r"ANNUAL|YEARLY|RENEWAL|1YR|12 ?MO|NORTON|MCAFEE|CALM|RING |COSTCO|SAM'?S CLUB|"
                         r"PRIME|AAA |DOMAIN|GODADDY|SQUARESPACE|ADOBE|MICROSOFT|OFFICE|TURBOTAX", re.I)
SAVING = re.compile(r"PREPAID COLLEGE|529|COLLEGE PLAN|SAVINGS|SAV \.|VANGUARD|FIDELITY|SCHWAB|BROKERAGE|"
                    r"ROTH|\bIRA\b|BETTERMENT|WEALTHFRONT|ACORNS|INVEST", re.I)
CADENCES = [  # name, min days, max days, per-month factor
    ("weekly", 6, 8, 52 / 12),
    ("biweekly", 13, 16, 26 / 12),
    ("monthly", 26, 35, 1.0),
    ("quarterly", 84, 98, 1 / 3),
    ("yearly", 350, 380, 1 / 12),
]


def parse_date(s):
    s = s.strip()
    for f in DATE_FORMATS:
        try:
            return datetime.strptime(s, f).date()
        except ValueError:
            pass
    return None


def parse_amount(s):
    s = (s or "").strip().replace("$", "").replace(",", "").replace("₪", "").replace("€", "")
    if not s:
        return None
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    try:
        v = float(s)
    except ValueError:
        return None
    return -v if neg else v


def pick(cols, *needles, avoid=()):
    low = {c: c.lower() for c in cols}
    for n in needles:
        for c, l in low.items():
            if n in l and not any(a in l for a in avoid):
                return c
    return None


def load(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return []
    cols = list(rows[0].keys())
    dcol = pick(cols, "transaction date", "trans date", "date", avoid=("post",)) or pick(cols, "date")
    ncol = pick(cols, "description", "merchant", "payee", "name", "details", "memo")
    acol = pick(cols, "amount")
    debit, credit = pick(cols, "debit", "withdrawal"), pick(cols, "credit", "deposit")
    tcol = pick(cols, "type")
    if not dcol or not ncol or not (acol or debit):
        raise ValueError(f"{path}: could not find date / description / amount columns in {cols}")
    out = []
    for r in rows:
        d = parse_date(r.get(dcol, ""))
        if not d:
            continue
        if acol:
            a = parse_amount(r.get(acol))
        else:
            dv, cv = parse_amount(r.get(debit)), parse_amount(r.get(credit))
            a = -abs(dv) if dv else (abs(cv) if cv else None)
        if a is None or a == 0:
            continue
        out.append({"date": d, "desc": (r.get(ncol) or "").strip(), "amount": a,
                    "type": (r.get(tcol) or "").strip() if tcol else "", "file": Path(path).name})
    # Money out = the sign most rows share (cards and checking both have more charges than credits).
    neg = sum(1 for t in out if t["amount"] < 0)
    out_sign = -1 if neg >= len(out) - neg else 1
    for t in out:
        t["out"] = round(t["amount"] * out_sign, 2)  # positive = money out
    return out


def merchant(desc):
    s = desc.upper().replace("*", " ")
    s = re.sub(r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b", " ", s)       # phone numbers
    s = re.sub(r"#\s*\w+", " ", s)                               # store numbers
    s = re.sub(r"[•*xX]{2,}\s*\d+", " ", s)                       # masked card / account numbers (••0066)
    tokens = [t for t in s.split() if not re.search(r"\d", t)]   # reference codes with digits
    while tokens and re.fullmatch(r"[A-Z]{2}", tokens[-1]):      # trailing state / country
        tokens.pop()
    return " ".join(tokens).strip() or desc.upper().strip()


def cadence_of(gaps):
    """A schedule only counts if the gaps are regular. Coffee runs and Costco trips are not."""
    if not gaps:
        return None
    # Weekly with skipped weeks: every gap a multiple of 7.
    if len(gaps) >= 3 and min(gaps) == 7 and all(g % 7 == 0 and g <= 35 for g in gaps):
        return "weekly", 52 / 12
    med = statistics.median(gaps)
    if med <= 0:  # several charges on the same day (processor fees, split orders) are not a schedule
        return None
    # Every gap must be a whole number of periods (a paused month is two periods), within 15%.
    if len(gaps) >= 2 and any(abs(g - max(1, round(g / med)) * med) > 0.15 * med for g in gaps):
        return None
    for name, lo, hi, factor in CADENCES:
        if lo <= med <= hi:
            return name, factor
    return None


def series_from(charges):
    charges = sorted(charges, key=lambda t: t["date"])
    gaps = [(b["date"] - a["date"]).days for a, b in zip(charges, charges[1:])]
    return charges, gaps


def detect(txns, today):
    spend = [t for t in txns if t["out"] > 0 and not SKIP.search(t["desc"]) and t["type"].lower() != "payment"]
    by_m = defaultdict(list)
    for t in spend:
        by_m[merchant(t["desc"])].append(t)

    found, singles = [], []
    for m, ts in by_m.items():
        by_amt = defaultdict(list)
        for t in ts:
            by_amt[t["out"]].append(t)
        clusters = []
        for amt, cs in by_amt.items():
            cs, gaps = series_from(cs)
            # Pull out duplicates: a second identical charge within 3 days.
            dups, clean = [], [cs[0]]
            for t in cs[1:]:
                if (t["date"] - clean[-1]["date"]).days <= 3:
                    dups.append(t)
                else:
                    clean.append(t)
            cs, gaps = series_from(clean)
            cad = cadence_of(gaps) if len(cs) >= 3 or (len(cs) == 2 and gaps and gaps[0] > 300) else None
            if cad:
                clusters.append({"amount": amt, "charges": cs, "cadence": cad, "dups": dups})
            elif len(cs) == 1 and len(ts) <= 2 and ANNUAL_HINT.search(cs[0]["desc"]):
                singles.append(cs[0])
        # Merge clusters that follow each other on the same cadence = a price change.
        clusters.sort(key=lambda c: c["charges"][0]["date"])
        merged = []
        for c in clusters:
            prev = merged[-1] if merged else None
            if (prev and prev["cadence"][0] == c["cadence"][0]
                    and c["charges"][0]["date"] > prev["charges"][-1]["date"]
                    and (c["charges"][0]["date"] - prev["charges"][-1]["date"]).days <= 45):
                prev.setdefault("history", [(prev["amount"], prev["charges"][0]["date"])])
                prev["history"].append((c["amount"], c["charges"][0]["date"]))
                prev["charges"] += c["charges"]
                prev["dups"] += c["dups"]
                prev["amount"] = c["amount"]
            else:
                merged.append(c)
        same_merchant_series = len(merged)
        for c in merged:
            found.append((m, c, same_merchant_series))

        # Variable monthly bills (electric, water): one charge a month, amount changes.
        if not merged and len(ts) >= 4:
            cs, gaps = series_from(ts)
            cad = cadence_of(gaps)
            if cad and cad[0] == "monthly" and statistics.pstdev(gaps) <= 4:
                amts = [t["out"] for t in cs]
                found.append((m, {"amount": round(statistics.mean(amts), 2), "charges": cs, "cadence": cad,
                                  "dups": [], "variable": (min(amts), max(amts))}, 1))

    results = []
    end = max(t["date"] for t in txns)
    for i, (m, c, siblings) in enumerate(sorted(found, key=lambda x: -x[1]["amount"] * x[1]["cadence"][1]), 1):
        cs, gaps = series_from(c["charges"])
        name, factor = c["cadence"]
        step = round(statistics.median(gaps)) if gaps else 365
        last = cs[-1]["date"]
        nxt = last + timedelta(days=step)
        monthly = round(c["amount"] * factor, 2)
        skipped = sum(max(1, round(g / step)) - 1 for g in gaps) if gaps else 0
        if skipped and name in ("weekly", "biweekly"):
            span = (last - cs[0]["date"]).days + step
            monthly = round(sum(t["out"] for t in cs) / (span / 30.44), 2)
        flags = []
        if skipped:
            flags.append({"flag": "skips_or_pauses", "skipped_periods": skipped,
                          "note": "cost per month is the real pace, not the full schedule" if name in ("weekly", "biweekly")
                          else "paused some periods"})
        if c.get("history"):
            first_amt, first_d = c["history"][0]
            flags.append({"flag": "price_increase" if c["amount"] > first_amt else "price_decrease",
                          "from": first_amt, "to": c["amount"], "since": str(c["history"][-1][1]),
                          "extra_per_year": round((c["amount"] - first_amt) * factor * 12, 2)})
        if c.get("variable"):
            flags.append({"flag": "variable_amount", "min": c["variable"][0], "max": c["variable"][1]})
        for d in c["dups"]:
            flags.append({"flag": "duplicate_charge", "date": str(d["date"]), "amount": d["out"]})
        span_days = (end - min(t["date"] for t in txns)).days
        if span_days > 240 and (end - cs[0]["date"]).days <= 150:
            flags.append({"flag": "started_recently", "first_charge": str(cs[0]["date"])})
        if (end - last).days > step * 1.6:
            flags.append({"flag": "stopped", "last_charge": str(last)})
        elif name in ("quarterly", "yearly") and 0 <= (nxt - today).days <= 30:
            flags.append({"flag": "renews_soon", "next_expected": str(nxt)})
        if PROCESSORS.search(cs[0]["desc"]) or siblings > 1:
            flags.append({"flag": "cryptic_name", "note": f"{siblings} separate plans bill under this name"
                          if siblings > 1 else "billed through a payment processor"})
        results.append({
            "id": f"S{i:02d}", "merchant": m, "bucket": "saving" if SAVING.search(cs[0]["desc"]) else "spend", "example_descriptor": cs[-1]["desc"], "file": cs[-1]["file"],
            "cadence": name, "amount_now": c["amount"], "monthly_cost": monthly,
            "yearly_cost": round(monthly * 12, 2),
            "paid_last_12_months": round(sum(t["out"] for t in cs if (end - t["date"]).days < 365)
                                         + sum(d["out"] for d in c["dups"] if (end - d["date"]).days < 365), 2),
            "charges": len(cs), "first_charge": str(cs[0]["date"]),
            "last_charge": str(last), "next_expected": str(nxt), "flags": flags,
        })

    possible_annual = []
    for t in singles:
        nxt = date(t["date"].year + 1, t["date"].month, min(t["date"].day, 28))
        possible_annual.append({"id": f"A{len(possible_annual) + 1:02d}", "merchant": merchant(t["desc"]),
                                "example_descriptor": t["desc"], "file": t["file"], "amount": t["out"],
                                "charged": str(t["date"]), "next_if_yearly": str(nxt),
                                "renews_within_30_days": 0 <= (nxt - today).days <= 30})
    in_series={r["merchant"] for r in results}|{a["merchant"] for a in possible_annual}
    near=[]
    for m,ts in by_m.items():
        if m in in_series or len(ts)<2: continue
        amts=[t["out"] for t in ts]
        if len(ts)>=3 or (len(ts)==2 and max(amts)>=100 and abs(amts[0]-amts[1])<1):
            near.append({"merchant":m,"charges":len(ts),"total":round(sum(amts),2),"first":str(min(t["date"] for t in ts)),
                         "last":str(max(t["date"] for t in ts)),"amounts":sorted(set(amts))[:6]})
    near.sort(key=lambda x:-x["total"])
    return results, possible_annual, end, near


def compute_total(data, cancel, refund):
    """The one place the recoverable number is calculated. --total and render_report.py both use it.
    Returns per-id lines and the sums. Raises ValueError on an id that is not in the data."""
    idx = {s["id"]: s for s in data["recurring"]}
    idx.update({a["id"]: a for a in data["possible_annual"]})
    lines, monthly, once, yearly_only = [], 0.0, 0.0, 0.0
    unknown = [i for i in cancel + refund if i not in idx]
    if unknown:
        raise ValueError(", ".join(unknown))
    for i in cancel:
        s = idx[i]
        if "monthly_cost" in s:
            m = s["monthly_cost"]
            monthly += m
            lines.append({"kind": "cancel", "id": i, "merchant": s["merchant"], "monthly": m, "yearly": m * 12})
        else:
            yearly_only += s["amount"]
            lines.append({"kind": "cancel", "id": i, "merchant": s["merchant"], "monthly": None, "yearly": s["amount"]})
    for i in refund:
        s = idx[i]
        dup = [f for f in s.get("flags", []) if f["flag"] == "duplicate_charge"]
        amt = sum(f["amount"] for f in dup) if dup else s.get("amount", s.get("amount_now", 0))
        once += amt
        lines.append({"kind": "refund", "id": i, "merchant": s["merchant"], "once": amt})
    return {"lines": lines, "monthly": monthly, "yearly_only": yearly_only, "once": once,
            "total": monthly * 12 + yearly_only + once}


def total(path, cancel, refund):
    data = json.loads(Path(path).read_text())
    try:
        t = compute_total(data, cancel, refund)
    except ValueError as e:
        sys.exit(f"Unknown id(s): {e}. Use the S and A ids from {path}.")
    rows = []
    for ln in t["lines"]:
        i, name = ln["id"], ln["merchant"]
        if ln["kind"] == "refund":
            rows.append(f"refund {i:<4} {name:<34} {ln['once']:>9.2f} one time")
        elif ln["monthly"] is None:
            rows.append(f"cancel {i:<4} {name:<34} {'yearly':>12} {ln['yearly']:>10.2f}/yr")
        else:
            rows.append(f"cancel {i:<4} {name:<34} {ln['monthly']:>9.2f}/mo {ln['yearly']:>10.2f}/yr")
    monthly, yearly_only, once = t["monthly"], t["yearly_only"], t["once"]
    print("\n".join(rows))
    print(f"\nRecurring savings: {monthly:.2f} per month = {monthly * 12:.2f} per year")
    if yearly_only:
        print(f"Yearly plans cancelled: {yearly_only:.2f} per year")
    print(f"One-time money back: {once:.2f}")
    print(f"TOTAL RECOVERABLE (first year): {t['total']:.2f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*")
    ap.add_argument("--out", default="recurring.json")
    ap.add_argument("--today", help="YYYY-MM-DD, default = last date in the data")
    ap.add_argument("--total")
    ap.add_argument("--cancel", default="")
    ap.add_argument("--refund", default="")
    a = ap.parse_args()
    if a.total:
        total(a.total, [x for x in a.cancel.split(",") if x], [x for x in a.refund.split(",") if x])
        return
    if not a.files:
        ap.error("give at least one CSV file")
    txns = []
    for f in a.files:
        try:
            txns += load(f)
        except ValueError as e:  # not a statement (a stray CSV in the folder): say so, keep going
            print(f"Skipped {e}")
    if not txns:
        sys.exit("No transactions found.")
    end = max(t["date"] for t in txns)
    today = datetime.strptime(a.today, "%Y-%m-%d").date() if a.today else end
    rec, ann, end, near = detect(txns, today)
    start = min(t["date"] for t in txns)
    out = {"period": [str(start), str(end)], "today": str(today), "transactions": len(txns),
           "files": sorted({t["file"] for t in txns}),
           "recurring_monthly_total": round(sum(s["monthly_cost"] for s in rec if s["bucket"] == "spend" and not any(
               f["flag"] == "stopped" for f in s["flags"])), 2),
           "saving_monthly_total": round(sum(s["monthly_cost"] for s in rec if s["bucket"] == "saving"), 2),
           "recurring": rec, "possible_annual": ann,
           "near_misses": near[:40]}
    Path(a.out).write_text(json.dumps(out, indent=2))
    print(f"{len(txns)} transactions, {start} to {end}, from {', '.join(out['files'])}")
    print(f"{len(rec)} recurring series + {len(ann)} possible yearly charges. Saved to {a.out}\n")
    print(f"{'id':<4} {'merchant':<34} {'every':<9} {'now':>9} {'per mo':>9} {'per yr':>10} {'paid 12mo':>10}  flags")
    def show(f):
        k = f["flag"]
        if k in ("price_increase", "price_decrease"):
            return f"{k} {f['from']:.2f}->{f['to']:.2f} since {f['since']} ({f['extra_per_year']:+.2f}/yr)"
        if k == "duplicate_charge":
            return f"duplicate {f['amount']:.2f} on {f['date']}"
        if k == "started_recently":
            return f"started {f['first_charge']}"
        if k == "stopped":
            return f"stopped, last {f['last_charge']}"
        if k == "renews_soon":
            return f"renews {f['next_expected']}"
        if k == "variable_amount":
            return f"varies {f['min']:.2f}-{f['max']:.2f}"
        if k == "skips_or_pauses":
            return f"skipped {f['skipped_periods']} periods"
        return k
    for s in rec:
        fl = ", ".join((["SAVING"] if s["bucket"] == "saving" else []) + [show(f) for f in s["flags"]])
        print(f"{s['id']:<4} {s['merchant'][:34]:<34} {s['cadence']:<9} {s['amount_now']:>9.2f} "
              f"{s['monthly_cost']:>9.2f} {s['yearly_cost']:>10.2f} {s['paid_last_12_months']:>10.2f}  {fl}")
    for p in ann:
        soon = "  RENEWS WITHIN 30 DAYS" if p["renews_within_30_days"] else ""
        print(f"{p['id']:<4} {p['merchant'][:34]:<34} {'yearly?':<9} {p['amount']:>9.2f} "
              f"{p['amount'] / 12:>9.2f} {p['amount']:>10.2f} {p['amount']:>10.2f}  charged {p['charged']}{soon}")
    print("\nNot on a schedule, but repeated (check by hand: camps, clubs, seasonal fees, habits):")
    for n in near[:12]:
        print(f"     {n['merchant'][:34]:<34} {n['charges']:>3}x  {n['total']:>9.2f}  {n['first']} to {n['last']}")
    print(f"\nActive recurring spend: {out['recurring_monthly_total']:.2f} per month "
          f"= {out['recurring_monthly_total'] * 12:.2f} per year (saving and yearly one-offs not included)")
    if out["saving_monthly_total"]:
        print(f"Recurring saving (good money, never 'found'): {out['saving_monthly_total']:.2f} per month")


if __name__ == "__main__":
    main()
