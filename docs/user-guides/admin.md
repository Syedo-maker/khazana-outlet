# Guide for the Khazana team

For administrators running the marketplace. Admin accounts are never created
by signing up. The first one is made on the server
(`python -m khazana.manage create-admin`, which prints a sign in link), and
`python -m khazana.manage login-link` makes a fresh link for an admin later. Every action here is recorded in
the **Audit log** with who did it and when.

## Inviting people

SMS codes are off during the beta, so everyone signs in with a link you make.

1. **Invites**: enter the person's mobile number and name, and whether they
   join as a reseller or a brand. Brand staff can join an existing brand.
2. **Create link.** The link is shown once. **Send on WhatsApp** opens your own
   WhatsApp with the message ready; send it only to that number.
3. The person opens it, accepts the beta terms and is signed in. A link works
   once and expires after 72 hours (`INVITE_TTL_HOURS`). Revoke one that was
   sent to the wrong person. Someone who already has an account gets a sign in
   link instead, which never changes their role.
4. Verify each new reseller's business under **Verification** before they can
   order.

## Commission from brands paid directly

Brands in the beta are paid cash on delivery by their own couriers, so you
collect commission from them instead of paying them out.

- On the 1st of each month at 06:00 the scheduler issues one invoice per
  brand for its orders confirmed the month before. **Commission** lists them;
  **Issue invoices** issues a month by hand, and issuing twice bills nothing
  twice.
- When a brand's transfer reaches the bank, enter its reference and **Mark
  paid**.
- In a dispute on a direct order, record the refund the brand agreed to give
  the buyer directly. Commission is then charged only on what the buyer kept.
- If a brand cannot enter a tracking number itself, you can enter it from the
  order page.

## Daily work

**Overview** shows what is waiting: verifications, listings to approve,
payments to confirm, disputes, payouts due, and risk cases.

- **Verification.** Check brand registration documents and reseller
  profiles, and verify or reject them with a reason.
- **Listings.** Every submitted lot, highest risk score first, with the
  findings behind the score: a manifest that does not add up, a price that
  looks wrong, a grade the defects contradict. The score informs; you decide.
- **Payments.** Confirm bank transfers against the bank statement before the
  order moves on. Card and wallet payments confirm themselves through the
  provider.
- **Disputes.** Read the buyer's report and the order history, then decide:
  refund in full, refund in part, or find for the seller. Funds stay held
  until you decide.
- **Payouts.** Gather the payouts that are due into a run, send them from the
  bank, and mark the run paid with the bank reference.
- **Risk review.** Accounts, listings and orders the daily risk job flagged,
  with the signals behind each. Dismiss or act on each case.

## Settings

**Settings** holds what is configuration rather than code: each brand's
commercial terms, and the couriers and shipping rates. Changing a brand's
terms takes effect for new actions immediately; it does not rewrite orders
already placed. The reference data the platform prices and forecasts with,
such as resale benchmarks and the season calendar, is loaded by the seed and
changed in the database for now.

## Watching the AI layer

**Growth and AI cost** shows AI spend by feature and by brand against the
caps, and how often people accepted or corrected what the AI drafted. The AI
never decides money, approvals, bans or quoted stock levels: it drafts,
suggests, scores and flags, and a person decides. The only exception is the
bargaining and markdown agents, which choose a value inside a band the brand
set, enforced in code (ADR 0001).

Each AI feature can be switched off on its own with its
`AI_DISABLE_<FEATURE>` setting if it misbehaves, without stopping anything
else. When the day's AI budget (`AI_DAILY_SPEND_LIMIT_USD`, one dollar in the
pilot) is spent, every feature works by hand until the next day and you get
one email saying so.

## Scheduled work

The scheduler runs these on its own; each can also be run now from the admin
API if needed:

| Job | When, Pakistan time |
| --- | --- |
| Markdown agent, sent as a batch | 02:00 daily |
| Markdown results applied | every 30 minutes |
| Expired pools closed | hourly |
| Dispute windows closed, funds released | hourly |
| Risk review | 03:00 daily |
| Demand forecasts | 04:00 Mondays |
| AI response cache cleaned | 04:30 daily |

How to deploy, back up, restore and monitor the platform is in
[../deployment.md](../deployment.md).
