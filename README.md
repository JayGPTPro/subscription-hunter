# /subscription-hunter . Find the money hiding in your subscriptions

Point it at your bank and credit card statements. It finds every subscription and recurring charge,
flags the forgotten ones, the free trials that turned paid, the price increases and the double charges,
and ends with one number: **what you can get back this year.**

A small script finds the charges and does all the math, so every number is real. Claude does the
judgment: what to cut, what to negotiate, what to ask you. It never logs in, never calls, never cancels
anything. You act.

## Install

```bash
npx skills add JayGPTPro/subscription-hunter -g
```

(`-g` installs it globally, so it's available in every folder.)

## Use

1. Download the last 12 months from your bank and your credit card as CSV files. Put them in one folder.
2. Open Claude Code in that folder and type:

```
/subscription-hunter
```

3. Read the number. The full report opens in your browser.

With no file names, it reads every statement in the folder. If your email is connected, it also checks your receipts; to skip that, put an empty file named `.no-email` in the folder (or say "files only").

## What you get

- **One number:** what you can get back this year, calculated in code.
- **A cut list:** every subscription worth cancelling, with a Cancel button that opens the company's own cancel page.
- **Doing the same job:** six streaming services or three cloud storage plans, side by side, with the one to keep.
- **Bills to negotiate:** what went up, by how much, and a phone script you can copy.
- **Renewing soon:** yearly plans about to charge you, with the date.
- **Questions for you:** anything it is not sure about. It never guesses what a charge is.
- **subscription-report.html:** the whole hunt on one page, light and dark, on a phone or a big screen.
- **subscriptions.md:** a memory file. Run it again next month and it tells you only what changed,
  and keeps a tally of the money you actually got back.

## What's inside

- `SKILL.md`: the instructions Claude follows.
- `scripts/find_recurring.py`: finds the recurring charges and does all the math.
- `scripts/render_report.py` and `assets/report-template.html`: build the report page from Claude's verdicts.
- `references/cancel-links.json`: official cancel and manage pages for common US subscriptions.

---

Built by Jay Margaliot. For more tips, insights & updates on AI:
**jaygptpro.com/whatsapp**
