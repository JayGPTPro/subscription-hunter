#!/usr/bin/env python3
"""Sample statements for trying the skill without your own bank files.

Writes a year of made-up bank and card exports for a typical American family into a folder:
  checking_first-coast-bank.csv   Date, Description, Amount, Balance
  visa-4417_first-coast-bank.csv  Transaction Date, Post Date, Description, Category, Type, Amount

The family, the bank and every charge are invented. The usual leaks are in there on purpose:
streaming services stacked up, a gym that kept billing, a trial that turned paid, a double
charge, price increases, a yearly renewal coming up, a plan sitting on checking.

Same seed, same family and amounts every time; the dates move so the year always ends a few
days before today.  Run:  python3 make_sample_data.py [folder]   (default: the current folder)
"""
import csv
import json
import random
from datetime import date, timedelta
from pathlib import Path

SEED = 20261021
START = date(2025, 10, 1)
END = date(2026, 10, 10)   # a few days before the webinar (21.10), never "in the future"
OPENING_BALANCE = 7480.18

import sys
DATA = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
# every date is written shifted, so the made-up year always ends 11 days before today
SHIFT = (date.today() - timedelta(days=11)) - END

rng = random.Random(SEED)
card = []      # dicts: date, desc, cat, amount (positive = charge, negative = credit)
checking = []  # dicts: date, desc, amount (positive = in, negative = out)
key = []       # planted findings


def days():
    d = START
    while d <= END:
        yield d
        d += timedelta(days=1)


def monthly_dates(day, start=START, end=END):
    y, m = start.year, start.month
    while True:
        try:
            d = date(y, m, day)
        except ValueError:
            d = date(y, m, 28)
        if d > end:
            return
        if d >= start:
            yield d
        m += 1
        if m == 13:
            y, m = y + 1, 1


def add_card(d, desc, cat, amount):
    card.append({"date": d, "desc": desc, "cat": cat, "amount": round(amount, 2)})


def add_chk(d, desc, amount):
    checking.append({"date": d, "desc": desc, "amount": round(amount, 2)})


# ---------------------------------------------------------------------------
# Subscriptions on the Visa. (descriptor, category, day, schedule)
# schedule: list of (from_date, to_date_or_None, amount)
# ---------------------------------------------------------------------------
SUBS = [
    # name, descriptor, card category, day of month, [(from, to, amount)], finding, note
    ("Netflix", "NETFLIX.COM 866-579-7172 CA", "Entertainment", 6,
     [(START, date(2025, 12, 31), 22.99), (date(2026, 1, 1), None, 24.99)],
     "price_increase", "Premium plan went from $22.99 to $24.99 in January."),
    ("Hulu", "HULU 877-8244858 CA", "Entertainment", 11,
     [(START, None, 18.99)], "overlap_streaming", "One of six streaming services."),
    ("Disney+", "DISNEYPLUS 888-905-7888 CA", "Entertainment", 14,
     [(START, None, 15.99)], "overlap_streaming", "Paid separately from Hulu."),
    ("Max", "MAX.COM 855-442-6629 NY", "Entertainment", 3,
     [(date(2026, 2, 3), None, 16.99)], "overlap_streaming", "Started February, never stopped."),
    ("Peacock", "PEACOCK 9C2B1 PREMIUM NY", "Entertainment", 21,
     [(START, date(2026, 6, 30), 7.99), (date(2026, 7, 1), None, 10.99)],
     "price_increase", "Went from $7.99 to $10.99 in July."),
    ("Paramount+", "PARAMOUNT+ 888-274-5343 CA", "Entertainment", 12,
     [(date(2026, 6, 12), None, 12.99)], "trial_converted",
     "Free trial in May turned into a paid plan on June 12. No charge before that."),
    ("Spotify Family", "SPOTIFY USA 877-7781161 NY", "Entertainment", 9,
     [(START, date(2026, 5, 31), 16.99), (date(2026, 6, 1), None, 19.99)],
     "price_increase", "Family plan from $16.99 to $19.99 in June."),
    ("Apple Music", "APPLE.COM/BILL 866-712-7753 CA", "Shopping", 9,
     [(START, None, 10.99)], "overlap_music", "Second music service next to Spotify. Hidden behind APPLE.COM/BILL."),
    ("iCloud+ 2TB", "APPLE.COM/BILL 866-712-7753 CA", "Shopping", 3,
     [(START, None, 9.99)], "overlap_storage", "Cloud storage #1. Same APPLE.COM/BILL descriptor."),
    ("Kids app (Apple)", "APPLE.COM/BILL 866-712-7753 CA", "Shopping", 17,
     [(START, None, 4.99)], "cryptic", "A third APPLE.COM/BILL amount. Only the Apple receipt says what it is."),
    ("Google One 2TB", "GOOGLE *Google One g.co/helppay#", "Services", 20,
     [(START, None, 9.99)], "overlap_storage", "Cloud storage #2."),
    ("Dropbox Plus", "DROPBOX*Q7KX2 DBX.CO/BILL CA", "Services", 25,
     [(START, None, 11.99)], "overlap_storage", "Cloud storage #3."),
    ("Amazon Prime", "AMAZON PRIME*2K4T81 Amzn.com/bill WA", "Shopping", 14,
     [(START, None, 14.99)], "keep", "Used: steady Amazon orders all year."),
    ("Audible", "PAYPAL *AUDIBLE 402-935-7733 NJ", "Shopping", 2,
     [(START, None, 14.95)], "cryptic", "Billed through PayPal, so the card line does not say Audible clearly."),
    ("Planet Fitness", "PLANET FITNESS CLUB FEES NH", "Health & Wellness", 17,
     [(START, None, 24.99)], "overlap_fitness", "Kept paying after Orangetheory started in January."),
    ("Orangetheory", "ORANGETHEORY FITNESS TAMPA FL", "Health & Wellness", 5,
     [(date(2026, 1, 5), None, 169.00)], "overlap_fitness", "New Year membership, still active."),
    ("ABCmouse", "ABCMOUSE.COM 866-249-0115 CA", "Entertainment", 23,
     [(START, None, 12.99)], "question", "Pre-K learning app. Noah is 6, Emma is 9. Still used?"),
    ("Roblox Premium", "ROBLOX CORP 888-858-2569 CA", "Entertainment", 8,
     [(START, None, 9.99)], "keep", "Kid subscription, looks intentional."),
    ("NYTimes", "NYT*NYTIMES DIGITAL 800-698-4637 NY", "Shopping", 15,
     [(START, date(2026, 3, 31), 4.00), (date(2026, 4, 1), None, 25.00)],
     "price_increase", "Intro price ended in April: $4.00 became $25.00."),
    ("Chewy Autoship", "CHEWY.COM 800-672-4399 FL", "Shopping", 10,
     [(START, None, 64.98)], "keep", "Dog food autoship. A good subscription."),
    ("BarkBox", "BARKBOX 855-500-2275 NY", "Shopping", 19,
     [(START, None, 35.00)], "question", "Monthly dog toy box on top of Chewy."),
    ("LinkedIn Premium", "LINKEDIN PRE 7869*JK31 CA", "Services", 27,
     [(date(2026, 1, 27), None, 39.99)], "forgotten",
     "Started in January for a job search. Mike got a raise in March and stayed, yet it keeps billing."),
    ("DashPass", "DOORDASH DASHPASS SAN FRANCISCO CA", "Food & Drink", 4,
     [(START, None, 9.99)], "overlap_delivery", "Delivery membership #1."),
    ("Uber One", "UBER *ONE MEMBERSHIP SAN FRANCISCO CA", "Travel", 16,
     [(date(2025, 12, 16), None, 9.99)], "overlap_delivery", "Delivery membership #2, started December."),
    ("Canva Pro", "CANVA* I04471-88213 SURRY HILLS AU", "Services", 7,
     [(START, None, 14.99)], "keep", "Sarah uses it for the Etsy candle shop."),
    ("Adobe Photography", "ADOBE *PHOTOGPHY PLAN 800-833-6687 CA", "Services", 24,
     [(START, None, 19.99)], "question", "Second design tool for the Etsy shop next to Canva."),
]

for name, desc, cat, day, schedule, finding, note in SUBS:
    for d in monthly_dates(day):
        for frm, to, amt in schedule:
            if d >= frm and (to is None or d <= to):
                add_card(d, desc, cat, amt)
                break

# Duplicate charge: Amazon Prime billed twice on July 14, 2026.
add_card(date(2026, 7, 14), "AMAZON PRIME*2K4T81 Amzn.com/bill WA", "Shopping", 14.99)

# Annual subscriptions.
add_card(date(2025, 11, 8), "NORTON *AP1AE3D0 844-488-4540 AZ", "Services", 129.99)   # renews 2026-11-08
add_card(date(2026, 2, 19), "CALM.COM SAN FRANCISCO CA", "Health & Wellness", 69.99)
add_card(date(2026, 3, 22), "RING YEARLY PLAN 800-656-1918 CA", "Services", 99.99)
add_card(date(2026, 2, 17), "PLANET FITNESS ANNUAL FEE NH", "Health & Wellness", 49.99)
add_card(date(2026, 9, 12), "COSTCO *ANNUAL RENEWAL 800-774-2678 WA", "Shopping", 65.00)

# HelloFresh: weekly box on Mondays from Nov 3, skipping some weeks.
d = date(2025, 11, 3)
while d <= END:
    if rng.random() > 0.22:
        add_card(d, "HELLOFRESH 646-846-3663 NY", "Food & Drink", 79.96)
    d += timedelta(days=7)

# ---------------------------------------------------------------------------
# Everyday card spending
# ---------------------------------------------------------------------------
RESTAURANTS = ["CHIPOTLE 1842", "CHICK-FIL-A #02341", "PANERA BREAD #601147", "OLIVE GARDEN 0172",
               "TST* COLUMBIA RESTAURANT", "TST* ULELE TAMPA", "FIRST WATCH 0219", "PDQ TAMPA 004",
               "TACO BUS - TAMPA", "BRGR KITCHEN SOUTH TAMPA"]

for d in days():
    wd = d.weekday()
    month = d.month
    # Groceries: Publix twice a week, Aldi sometimes, Costco twice a month.
    if wd in (2, 6):
        add_card(d, "PUBLIX SUPER MARKETS #1287", "Groceries", rng.uniform(78, 168))
    if wd == 4 and rng.random() < 0.35:
        add_card(d, "ALDI 72031", "Groceries", rng.uniform(38, 92))
    if d.day in (6, 21):
        add_card(d, "COSTCO WHSE #1042", "Groceries", rng.uniform(165, 340))
    # Gas.
    if wd in (1, 5) and rng.random() < 0.8:
        add_card(d, rng.choice(["WAWA 5231", "RACETRAC 2207", "SHELL OIL 57444"]), "Gas", rng.uniform(38, 66))
    # Coffee: the latte line.
    if wd < 5 and rng.random() < 0.55:
        add_card(d, "STARBUCKS STORE 09612", "Food & Drink", rng.choice([5.45, 6.25, 6.95, 7.45, 11.90]))
    # Dining out.
    if rng.random() < (0.30 if wd >= 4 else 0.12):
        add_card(d, rng.choice(RESTAURANTS), "Food & Drink", rng.uniform(18, 96))
    # DoorDash and Uber Eats orders.
    if rng.random() < 0.10:
        add_card(d, "DOORDASH*" + rng.choice(["CHIPOTLE", "PANDA EXPRESS", "WINGSTOP", "THAI THANI"]),
                 "Food & Drink", rng.uniform(24, 61))
    if d >= date(2025, 12, 16) and rng.random() < 0.05:
        add_card(d, "UBER *EATS PENDING", "Food & Drink", rng.uniform(22, 55))
    # Amazon orders.
    if rng.random() < (0.30 if month in (11, 12) else 0.15):
        add_card(d, "AMZN Mktp US*" + "".join(rng.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(9)),
                 "Shopping", rng.uniform(9, 140 if month in (11, 12) else 75))
    # Target.
    if wd == 6 and rng.random() < 0.5:
        add_card(d, "TARGET 00011452", "Shopping", rng.uniform(24, 155))
    # Pharmacy.
    if rng.random() < 0.04:
        add_card(d, "CVS/PHARMACY #05211", "Health & Wellness", rng.uniform(9, 48))

# Seasonal and one-off.
ONE_OFFS = [
    (date(2025, 10, 18), "HOME DEPOT #6312", "Home", 214.37),
    (date(2025, 10, 30), "PARTY CITY 0577", "Shopping", 86.12),
    (date(2025, 11, 26), "DELTA AIR LINES ATLANTA", "Travel", 1186.40),
    (date(2025, 11, 28), "BEST BUY 00010587", "Shopping", 649.99),
    (date(2025, 12, 5), "KOHLS #0912", "Shopping", 238.54),
    (date(2025, 12, 12), "OLD NAVY ON-LINE", "Shopping", 156.80),
    (date(2025, 12, 18), "MACYS INTERNATIONAL PLAZA", "Shopping", 312.45),
    (date(2025, 12, 20), "APPLE STORE R474", "Shopping", 429.00),
    (date(2026, 1, 9), "TAMPA BAY YOUTH SOCCER", "Kids", 145.00),
    (date(2026, 1, 21), "BAYCARE HEALTH SYSTEM", "Health & Wellness", 186.40),
    (date(2026, 2, 7), "DISCOUNT TIRE #FLT21", "Auto", 612.88),
    (date(2026, 2, 14), "BERN'S STEAK HOUSE", "Food & Drink", 238.60),
    (date(2026, 3, 14), "BANFIELD PET HOSPITAL", "Pets", 268.00),
    (date(2026, 4, 2), "DELTA AIR LINES ATLANTA", "Travel", 1486.40),
    (date(2026, 4, 25), "HOME DEPOT #6312", "Home", 389.12),
    (date(2026, 5, 9), "JIFFY LUBE #2214", "Auto", 89.99),
    (date(2026, 5, 30), "BAYCARE HEALTH SYSTEM", "Health & Wellness", 75.00),
    (date(2026, 7, 6), "MARRIOTT ORLANDO WORLD CTR", "Travel", 1212.88),
    (date(2026, 7, 6), "ENTERPRISE RENT-A-CAR", "Travel", 386.20),
    (date(2026, 7, 8), "WALT DISNEY WORLD TICKETS", "Travel", 1034.00),
    (date(2026, 8, 4), "OLD NAVY ON-LINE", "Shopping", 211.37),
    (date(2026, 8, 6), "TARGET 00011452", "Shopping", 184.90),
    (date(2026, 8, 12), "TAMPA BAY YOUTH SOCCER", "Kids", 145.00),
    (date(2026, 8, 29), "JIFFY LUBE #2214", "Auto", 94.99),
    (date(2026, 9, 18), "BANFIELD PET HOSPITAL", "Pets", 142.00),
    (date(2026, 10, 3), "GREAT CLIPS #4410", "Personal Care", 58.00),
]
for d, desc, cat, amt in ONE_OFFS:
    add_card(d, desc, cat, amt)

# Haircuts every ~6 weeks.
d = date(2025, 10, 11)
while d <= END:
    add_card(d, "GREAT CLIPS #4410", "Personal Care", rng.choice([44.0, 58.0, 62.0]))
    d += timedelta(days=42)

# One refund, to keep the export honest.
add_card(date(2025, 12, 29), "AMZN Mktp US RETURN", "Shopping", -64.99)

# ---------------------------------------------------------------------------
# Checking account
# ---------------------------------------------------------------------------
d = date(2025, 10, 3)
while d <= END:
    add_chk(d, "ACME LOGISTICS PAYROLL PPD ID: 9111222333", 2486.40 if d < date(2026, 3, 13) else 2598.10)
    d += timedelta(days=14)
d = date(2025, 10, 10)
while d <= END:
    add_chk(d, "BRIGHTSMILE DENTAL DIR DEP PPD ID: 4455667788", 1412.75)
    d += timedelta(days=14)

ETSY = {10: 186.40, 11: 412.75, 12: 688.20, 1: 142.10, 2: 205.35, 3: 168.90, 4: 221.60,
        5: 254.15, 6: 176.80, 7: 133.45, 8: 198.70, 9: 241.30}
for d in monthly_dates(5):
    if d.month in ETSY:
        add_chk(d, "ETSY INC PAYOUT ACH", ETSY[d.month])
add_chk(date(2026, 3, 11), "IRS TREAS 310 TAX REF", 1846.00)

for d in monthly_dates(1):
    add_chk(d, "ROCKET MORTGAGE PAYMENT", -2148.33)
for d in monthly_dates(15):
    add_chk(d, "TOYOTA FINANCIAL SVCS AUTOPAY", -412.67)
ELECTRIC = {10: 212.4, 11: 154.1, 12: 141.8, 1: 149.6, 2: 138.9, 3: 151.2, 4: 186.7,
            5: 238.4, 6: 284.9, 7: 309.6, 8: 302.2, 9: 268.5}
for d in monthly_dates(19):
    add_chk(d, "TECO TAMPA ELECTRIC BILLPAY", -ELECTRIC[d.month])
for d in monthly_dates(24):
    add_chk(d, "CITY OF TAMPA UTILITIES WEB PMT", -round(rng.uniform(64, 96), 2))
for d in monthly_dates(12):
    add_chk(d, "SPECTRUM 855-707-7328 AUTOPAY", -(79.99 if d < date(2026, 4, 1) else 89.99))
for d in monthly_dates(21):
    add_chk(d, "VERIZON WIRELESS PAYMENTS", -(168.42 if d < date(2026, 6, 1) else 183.42))
for d in monthly_dates(8):
    add_chk(d, "PROGRESSIVE INS PREM", -(187.50 if d < date(2026, 4, 1) else 214.80))
for d in monthly_dates(28):
    add_chk(d, "CHOICE HOME WARRANTY ACH", -54.00)
for d in monthly_dates(2):
    if d.month not in (12, 7):
        add_chk(d, "ONLINE TRANSFER TO SAV ...9021", -400.00)
for d in monthly_dates(10):
    add_chk(d, "FL PREPAID COLLEGE PLAN", -165.00)
for d in monthly_dates(1):
    if d.month in (6, 7):
        add_chk(d, "YMCA OF TAMPA SUMMER CAMP", -620.00)
    else:
        add_chk(d, "YMCA OF TAMPA AFTERCARE", -340.00)
for d in days():
    if rng.random() < 0.05:
        add_chk(d, "VENMO PAYMENT", -round(rng.choice([20, 25, 35, 40, 60, 85, 120]), 2))
    if rng.random() < 0.025:
        add_chk(d, "ATM WITHDRAWAL 4417 BAYSHORE BLVD", -float(rng.choice([60, 100, 140])))
    if rng.random() < 0.012:
        add_chk(d, "ZELLE FROM JESSICA MORALES", float(rng.choice([45, 60, 80])))

# Card payment on the 22nd = all card activity of the previous calendar month.
def month_key(d):
    return (d.year, d.month)

card_by_month = {}
for t in card:
    card_by_month[month_key(t["date"])] = card_by_month.get(month_key(t["date"]), 0) + t["amount"]
# The September 2025 statement (before this export starts) is paid in October.
add_chk(date(2025, 10, 22), "PAYMENT TO FCB VISA ENDING 4417", -4612.37)
add_card(date(2025, 10, 22), "PAYMENT THANK YOU", "Payment", -4612.37)
for d in monthly_dates(22):
    prev = (d.year, d.month - 1) if d.month > 1 else (d.year - 1, 12)
    if prev in card_by_month:
        amt = round(card_by_month[prev], 2)
        add_chk(d, "PAYMENT TO FCB VISA ENDING 4417", -amt)
        add_card(d, "PAYMENT THANK YOU", "Payment", -amt)

# ---------------------------------------------------------------------------
# Write files
# ---------------------------------------------------------------------------
DATA.mkdir(parents=True, exist_ok=True)
checking.sort(key=lambda t: (t["date"], -t["amount"]))
bal = OPENING_BALANCE
low = (bal, START)
with open(DATA / "checking_first-coast-bank.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["Date", "Description", "Amount", "Balance"])
    for t in checking:
        bal = round(bal + t["amount"], 2)
        if bal < low[0]:
            low = (bal, t["date"])
        w.writerow([(t["date"] + SHIFT).strftime("%m/%d/%Y"), t["desc"], f"{t['amount']:.2f}", f"{bal:.2f}"])

card.sort(key=lambda t: t["date"])
with open(DATA / "visa-4417_first-coast-bank.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["Transaction Date", "Post Date", "Description", "Category", "Type", "Amount"])
    for t in card:
        post = t["date"] + timedelta(days=1 if t["date"].weekday() < 4 else 3)
        typ = "Payment" if t["cat"] == "Payment" else ("Return" if t["amount"] < 0 else "Sale")
        # Card exports show charges as negative numbers.
        w.writerow([(t["date"] + SHIFT).strftime("%m/%d/%Y"), (post + SHIFT).strftime("%m/%d/%Y"), t["desc"],
                    "" if t["cat"] == "Payment" else t["cat"], typ, f"{-t['amount']:.2f}"])

print(f"Sample statements written to {DATA}: checking_first-coast-bank.csv ({len(checking)} rows), "
      f"visa-4417_first-coast-bank.csv ({len(card)} rows), "
      f"{(START + SHIFT).isoformat()} to {(END + SHIFT).isoformat()}. A made-up family, for trying the skill.")
