# Week 7: Manual sales test

This is the most important week in Phase 0. Everything before it is research,
and research can be wrong in comfortable ways. This week you find out whether
anyone actually pays.

The plan is explicit: do not skip this week. If 10 to 20 lots will not sell by
hand, they will not sell through an app.

## The rule for the week

No platform. No website checkout. No code. You are the platform: WhatsApp,
Instagram, a phone, a spreadsheet, a bank account and a courier. Everything
you learn here becomes a requirement in Phase 1, and everything you do not
need here should be cut from Phase 1.

## Target

| Measure | Target | Minimum to pass |
| --- | --- | --- |
| Brands supplying stock | 2 | 1 |
| Lots listed | 15 | 10 |
| Lots sold | 10 | 5 |
| Money collected | Any real revenue | Nothing on credit |
| Deliveries completed | All sold lots | All sold lots |

A sale is only a sale when the money has arrived and the goods have been
delivered. A promise is not a sale. A pending payment is not a sale.

## Day by day

### Day 1: get the stock

- Call the brands who committed in week 2. Ask for one real lot each.
- Agree in writing, over WhatsApp is fine, for each lot: piece count, size and
  colour breakdown, condition, the floor price the brand will accept, your
  commission, and who holds the stock until it sells.
- Decide the protection level per lot: name shown, name hidden, cities
  excluded. Write it down and follow it exactly. Breaking this once in week 7
  costs you the brand forever.

Prefer consignment, meaning the brand keeps the stock until it sells, so you
do not spend your own cash on inventory. If a brand insists on selling you the
lot outright, only buy if you can afford to be wrong about it.

### Day 2: build the listings

For every lot, produce:

- 6 to 10 photographs: the full lot, a single piece front and back, the label,
  the size breakdown, and any defect, photographed honestly
- A manifest using `lot-listing-template.md`
- One price and one minimum order quantity

Photograph defects deliberately. A buyer who finds an unmentioned defect never
buys again, and in a market this small, reputation is the whole business.

### Day 3 to 4: sell

Work your week 3 list and the waiting list, in this order:

1. The resellers who asked to be told first. Call them, do not message.
2. The reseller WhatsApp and Facebook groups, with photographs and manifest.
3. Instagram, as a post and in stories.
4. Walk a market with the photographs on your phone. In person closes fastest.

Rules while selling:

- Take payment by bank transfer or JazzCash before dispatch for every B2B lot.
  Week 7 is not the time to test credit.
- Record every objection and every price negotiation.
- If a buyer asks for something you do not have, write the request down. That
  list is your Phase 1 feature list, written by paying customers.

### Day 5: deliver

- Book through a real courier, not a friend with a car, so you learn the real
  cost, the real transit time and the real paperwork
- Record the actual freight cost per lot, the COD charge if any, and the
  settlement delay
- Confirm delivery with each buyer and ask one question: did it match the
  manifest, yes or no

### Day 6: pay the brands and reconcile

- Pay each brand what you owe, minus the agreed commission, the same week.
  Paying fast is how you get the second lot.
- Reconcile every rupee in `../trackers/manual-sales-tracker.csv`
- Compare the real numbers against the week 5 unit economics model and correct
  the model. The model was a guess, this is data.

### Day 7: write it up

Write `manual-test-results.md` in this folder covering:

- What sold, what did not, and your honest theory about why
- Real contribution margin per lot after all actual costs
- Every objection, counted
- Every feature a buyer or brand asked for, counted
- What you would never do again

## What to measure, and what each result means

| Signal | Good | Worrying | What to do if worrying |
| --- | --- | --- | --- |
| Time from listing to sale | Under 7 days | Over 21 days | Price is wrong or demand is in a different category |
| Share of lots sold | Over 60 percent | Under 30 percent | Wrong category or wrong buyers, revisit week 4 |
| Buyers paying in advance | Most | Few | Escrow becomes mandatory in the MVP, and cash flow needs rethinking |
| Manifest accuracy complaints | None | Any | Fix the manifest process before Phase 1, this is the trust killer |
| Brands offering a second lot | Most | Few | Ask each one why not. The answer is the real product gap |
| Your own hours per lot | Falling | Flat or rising | Identify the manual step that must be automated first in Phase 1 |

The last row is the quiet purpose of this week. Whichever task takes most of
your time by hand is the first thing to automate, and that should set the
build order in Phase 1 regardless of what the plan says.

## The honest question to answer on day 7

Not "did it work" but these three:

1. Would any of these buyers buy again next month without me calling them?
2. Would any of these brands give me a second lot without me chasing them?
3. Did the money work after all real costs, or did it only work because I did
   everything myself for free?

If the answer to 3 is that it only worked because your own labour was free,
that is not a failure, but it tells you precisely which costs the platform
must remove before this is a business.
