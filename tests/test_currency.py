"""Regression tests: shekels and dollars are never added together, and Israeli bank
descriptors (card bill payments, transfers, checks) are read the way a person would.

Run:  python3 -m unittest discover -s tests -v
Standard library only. Every test builds its own statements in a temp folder.
"""
import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
import find_recurring as fr  # noqa: E402
import render_report as rr  # noqa: E402


def months(n, day=10, start=(2025, 11)):
    y, m = start
    for _ in range(n):
        yield date(y, m, day)
        m += 1
        if m == 13:
            y, m = y + 1, 1


def write_csv(path, header, rows):
    lines = [",".join(header)] + [",".join(f'"{c}"' if "," in str(c) else str(c) for c in r) for r in rows]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def israeli_checking(path):
    """Discount-style export with a Currency column, all in shekels."""
    rows = []
    for d in months(11):
        rows.append([d.isoformat(), "חיוב לכרטיס ויזה 1234", "-4300.00", "ILS"])  # card bill, not spend
        rows.append([d.isoformat(), "כ.א.ל חיוב", "-125.00", "ILS"])               # Cal card bill
        rows.append([d.isoformat(), "העברה לחשבון אחר", "-5000.00", "ILS"])       # transfer
        rows.append([d.replace(day=1).isoformat(), "משיכת שיק:", "-7700.00", "ILS"])  # rent by check
        rows.append([d.replace(day=15).isoformat(), "נטפליקס", "-54.90", "ILS"])      # a real subscription
    write_csv(path, ["Date", "Description", "Amount", "Currency"], rows)


def mercury_card(path):
    """Mercury-style export: Amount is USD, Original Currency is the merchant's (ILS here)."""
    rows = []
    for d in months(11, day=21):
        rows.append([d.isoformat(), "Hot Mobile", "-49.73", "Mercury Credit", "ILS"])
        rows.append([d.isoformat(), "Zoom", "-21.99", "Mercury Credit", "USD"])
    write_csv(path, ["Date", "Description", "Amount", "Source Account", "Original Currency"], rows)


def scan(folder, *files):
    out = Path(folder) / "recurring.json"
    args = [sys.executable, str(SCRIPTS / "find_recurring.py"), *map(str, files), "--out", str(out), "--today", "2026-10-21"]
    res = subprocess.run(args, capture_output=True, text=True)
    if res.returncode:
        raise AssertionError(res.stderr)
    return json.loads(out.read_text(encoding="utf-8")), res.stdout


class MixedCurrencyScan(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        d = Path(cls.tmp.name)
        cls.ils, cls.usd = d / "bank-checking_ILS_2025-11.csv", d / "card_USD_2025-11.csv"
        israeli_checking(cls.ils)
        mercury_card(cls.usd)
        cls.data, cls.stdout = scan(d, cls.ils, cls.usd)
        cls.by_name = {s["merchant"]: s for s in cls.data["recurring"]}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_each_series_keeps_its_own_currency(self):
        self.assertEqual(self.by_name["נטפליקס"]["currency"], "ILS")
        self.assertEqual(self.by_name["ZOOM"]["currency"], "USD")

    def test_original_currency_column_is_not_the_amount_currency(self):
        # Hot Mobile is billed in shekels, but Mercury already converted the Amount to dollars.
        self.assertEqual(self.by_name["HOT MOBILE"]["currency"], "USD")

    def test_no_single_total_across_currencies(self):
        self.assertEqual(sorted(self.data["currencies"]), ["ILS", "USD"])
        self.assertIsNone(self.data["recurring_monthly_total"])
        by = self.data["by_currency"]
        self.assertAlmostEqual(by["USD"]["recurring_monthly_total"], 49.73 + 21.99, places=2)
        self.assertAlmostEqual(by["ILS"]["recurring_monthly_total"], 7700.00 + 54.90, places=2)
        self.assertNotIn(f"{7700 + 54.90 + 49.73 + 21.99:.2f}", self.stdout)

    def test_hebrew_card_payments_and_transfers_are_skipped(self):
        names = set(self.by_name) | {n["merchant"] for n in self.data["near_misses"]}
        for skipped in ("חיוב לכרטיס ויזה", "כ.א.ל חיוב", "העברה לחשבון אחר"):
            self.assertNotIn(skipped, names)

    def test_checks_are_bills_not_subscriptions(self):
        self.assertEqual(self.by_name["משיכת שיק:"]["bucket"], "bill")
        self.assertEqual(self.by_name["נטפליקס"]["bucket"], "spend")

    def test_ids_are_unique_across_currencies(self):
        ids = [s["id"] for s in self.data["recurring"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_compute_total_refuses_to_mix(self):
        ils_id, usd_id = self.by_name["נטפליקס"]["id"], self.by_name["ZOOM"]["id"]
        with self.assertRaises(fr.MixedCurrencyError):
            fr.compute_total(self.data, [ils_id, usd_id], [])
        t = fr.compute_total(self.data, [ils_id], [])
        self.assertEqual(t["currency"], "ILS")
        self.assertAlmostEqual(t["total"], 54.90 * 12, places=2)

    def test_total_cli_prints_one_total_per_currency(self):
        ils_id, usd_id = self.by_name["נטפליקס"]["id"], self.by_name["ZOOM"]["id"]
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            fr.total(str(Path(self.tmp.name) / "recurring.json"), [ils_id, usd_id], [])
        text = out.getvalue()
        self.assertIn("TOTAL RECOVERABLE (first year) (ILS): 658.80", text)
        self.assertIn("TOTAL RECOVERABLE (first year) (USD): 263.88", text)
        self.assertNotIn(f"{658.80 + 263.88:.2f}", text)

    def test_report_needs_a_currency_and_uses_its_symbol(self):
        d = Path(self.tmp.name)
        ils_id = self.by_name["נטפליקס"]["id"]
        (d / "verdicts.json").write_text(json.dumps({"items": {ils_id: {
            "verdict": "CANCEL", "name": "Netflix", "bucket": "subscription", "why": "test"}}}), encoding="utf-8")
        links = str(SCRIPTS.parent / "references" / "cancel-links.json")
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit):
            rr.render(str(d / "recurring.json"), str(d / "verdicts.json"), str(d / "r.html"), links)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            rr.render(str(d / "recurring.json"), str(d / "verdicts.json"), str(d / "r-ILS.html"), links, "ILS")
        page = (d / "r-ILS.html").read_text(encoding="utf-8")
        self.assertIn("₪658.80", page)
        self.assertNotIn("$658.80", page)
        self.assertNotIn("Zoom", page.replace("zoom", ""))  # the dollar plans stay on the dollar page


class HowTheCurrencyIsFound(unittest.TestCase):
    """Each way a statement can say its currency, and what happens when it says nothing readable."""

    def scan_one(self, name, header, rows):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / name
            write_csv(f, header, rows)
            return scan(tmp, f)

    def test_code_in_the_file_name(self):
        data, _ = self.scan_one("bank_ILS_2026.csv", ["Date", "Description", "Amount"],
                                [[d.isoformat(), "נטפליקס", "-54.90"] for d in months(8)])
        self.assertEqual(data["currencies"], ["ILS"])

    def test_symbol_in_the_amount(self):
        data, _ = self.scan_one("bank.csv", ["Date", "Description", "Amount"],
                                [[d.isoformat(), "Netflix", "-₪54.90"] for d in months(8)])
        self.assertEqual(data["currencies"], ["ILS"])

    def test_hebrew_spelling_of_shekel_with_gershayim(self):
        data, _ = self.scan_one("bank.csv", ["Date", "Description", "Amount", "Currency"],
                                [[d.isoformat(), "נטפליקס", "-54.90", "ש״ח"] for d in months(8)])
        self.assertEqual(data["currencies"], ["ILS"])

    def test_unreadable_currency_is_kept_apart_never_usd(self):
        rows = [[d.isoformat(), "Netflix", "-54.90", "Shkalim"] for d in months(8)]
        rows += [[d.isoformat(), "Zoom", "-21.99", "USD"] for d in months(8)]
        data, out = self.scan_one("bank.csv", ["Date", "Description", "Amount", "Currency"], rows)
        self.assertEqual(sorted(data["currencies"]), ["Shkalim", "USD"])
        self.assertAlmostEqual(data["by_currency"]["USD"]["recurring_monthly_total"], 21.99, places=2)
        self.assertIn("WARNING", out)

    def test_hebrew_file_with_no_currency_warns(self):
        _, out = self.scan_one("bank.csv", ["Date", "Description", "Amount"],
                               [[d.isoformat(), "נטפליקס", "-54.90"] for d in months(8)])
        self.assertIn("_ILS", out)


class IsraeliDescriptors(unittest.TestCase):
    def test_card_bills_skipped_card_fees_kept_pension_is_saving(self):
        rows = []
        for i, d in enumerate(months(10)):
            rows.append([d.isoformat(), "חיוב כאל", f"-{3000 + 250 * i}.00"])          # Cal card bill
            rows.append([d.replace(day=12).isoformat(), "דמי כרטיס ישראכרט", "-14.90"])  # the card's own fee
            rows.append([d.replace(day=5).isoformat(), "מיטב דש גמל", "-1500.00"])        # pension deposit
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "bank_ILS.csv"
            write_csv(f, ["Date", "Description", "Amount"], rows)
            data, _ = scan(tmp, f)
        by = {s["merchant"]: s for s in data["recurring"]}
        self.assertNotIn("חיוב כאל", by)
        self.assertIn("דמי כרטיס ישראכרט", by)
        self.assertEqual(by["מיטב דש גמל"]["bucket"], "saving")
        self.assertAlmostEqual(data["recurring_monthly_total"], 14.90, places=2)

    def test_check_patterns(self):
        for desc in ("משיכת שיק:", "שיקים", "צ׳ק 1234", "CHECK #1042", "CHECK 1042"):
            self.assertTrue(fr.CHECKS.search(desc), desc)
        for desc in ("צ'ק פוינט", "CHECK 0315 NETFLIX", "CHECK CARD PURCHASE", "CHECKCARD 0315 SPOTIFY"):
            self.assertFalse(fr.CHECKS.search(desc), desc)


class ReportPage(unittest.TestCase):
    def test_checks_default_to_bills_and_receipts_keep_their_symbol(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            f = d / "bank_USD.csv"
            write_csv(f, ["Date", "Description", "Amount"],
                      [[m.isoformat(), "CHECK #1042", "-1800.00"] for m in months(8)])
            scan(d, f)
            (d / "v.json").write_text(json.dumps({"items": {}, "found_in_email": [
                {"name": "CapCut", "plan": "Pro", "price": "₪49.90", "cadence": "month"}]}), encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                rr.render(str(d / "recurring.json"), str(d / "v.json"), str(d / "r.html"),
                          str(SCRIPTS.parent / "references" / "cancel-links.json"))
            page = (d / "r.html").read_text(encoding="utf-8")
        self.assertIn("₪49.90 a month on the receipt", page)
        self.assertNotIn("$49.90", page)
        self.assertIn('data-sort="bill"', page)


class SingleCurrencyUnchanged(unittest.TestCase):
    def test_plain_english_csv_is_usd_with_one_total(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "checking.csv"
            write_csv(f, ["Date", "Description", "Amount"],
                      [[d.strftime("%m/%d/%Y"), "NETFLIX.COM", "-15.49"] for d in months(10)])
            data, stdout = scan(tmp, f)
        self.assertEqual(data["currencies"], ["USD"])
        self.assertEqual(data["recurring_monthly_total"], 15.49)
        self.assertNotIn("== USD", stdout)


if __name__ == "__main__":
    unittest.main()
