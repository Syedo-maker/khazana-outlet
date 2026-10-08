# Week 4: Category decision

Goal: choose the two or three categories to start with, using the evidence
from weeks 1 to 3 instead of instinct. Output: a scored table, a decision,
and the reasons written down so that in month six you remember why.

## Why this decision matters more than it looks

Every later choice inherits it. Lot sizes, photography needs, condition
grading, courier weight bands, return policy, even whether you need an expiry
field in the database, all follow from the starting category. Changing it in
Phase 1 means rebuilding the catalogue module.

## The criteria and their weights

Score each candidate category from 1 to 5 on each criterion, multiply by the
weight, and total. The weights below reflect what kills marketplaces early,
so change them only with a reason you can defend.

| # | Criterion | Weight | Score 1 means | Score 5 means |
| --- | --- | --- | --- | --- |
| 1 | Brand supply available | 5 | No brand offered stock in this category | Several brands offered stock in week 2 |
| 2 | Reseller demand confirmed | 5 | No reseller asked for it | Most resellers named it unprompted |
| 3 | Margin space | 4 | Dealer margin is thin, no room for commission | Wide gap between brand price and reseller price |
| 4 | Easy to describe and photograph | 3 | Needs fitting, feel, or lab testing | A photo and a size list are enough |
| 5 | Shipping simplicity | 3 | Heavy, fragile, or oversized | Light, robust, flat |
| 6 | Low return risk | 3 | Sizing and fit disputes are normal | Size barely matters |
| 7 | No expiry or compliance risk | 3 | Expiry dates, cosmetics or food rules apply | No shelf life, no special rules |
| 8 | Counterfeit risk manageable | 2 | Fakes are everywhere and hard to spot | Fakes are rare or easy to spot |
| 9 | Repeat purchase likely | 2 | One off purchase | Buyer comes back monthly |
| 10 | Price per lot is affordable to small buyers | 2 | Minimum lot costs more than a small shop can pay | Small shops can buy a lot from pocket cash |

Maximum possible total: 160.

## Candidate categories

Starting candidates from the plan and from the brand list. Add or remove
based on what you actually found.

- Stitched womenswear, including lawn and pret
- Unstitched fabric
- Menswear, shirts and trousers
- Kidswear
- Footwear
- Bags and accessories
- Stationery, including pens
- Cosmetics
- Electronics accessories
- Home textiles, including bedsheets and towels

## Scoring sheet

Fill `../trackers/category-scoring.csv`, then copy the totals here.

| Category | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | Total |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| | | | | | | | | | | | |

## Things known in advance that should shape the scores

These are structural facts, not opinions, so apply them before you score:

- Cosmetics carry expiry dates. Selling near expiry or expired cosmetics is a
  legal and safety problem, not a discount opportunity. If cosmetics score
  well on demand, still treat them as a later phase, as the plan does, and
  only with an expiry field and a hard rule against listing expired stock.
- Footwear has a size and fit return problem, and a size curve problem. A lot
  of 500 pairs that is mostly size 11 is close to worthless. Insist on the
  size breakdown in the manifest before you accept a footwear lot.
- Unstitched fabric is the easiest category to describe and ship, and it is
  what Queen of Raw proved works, but in Pakistan it is also where the
  existing dealer market is strongest and margins are thinnest.
- Stationery is light, cheap to ship, has no size or fit problem, and has no
  expiry. It scores well on operations even when demand is moderate, which
  makes it a good second category for learning logistics cheaply.
- Electronics accessories have a warranty expectation and a higher fake rate.
  Returns will be higher than you expect.

## The decision

Write it here when the scores are in.

| Field | Value |
| --- | --- |
| Primary category | |
| Second category | |
| Third category (optional) | |
| Categories explicitly deferred | |
| Date decided | |

### Why these

Three to five sentences. Reference the evidence, naming the brands who
offered supply and the number of resellers who asked for the category.

### What would make us change this

Name the signal that would make you switch, and the date you will check it.
For example: if fewer than three of the first ten lots in the primary
category sell within 21 days, revisit the decision.

## Definition of done for week 4

- Scoring sheet filled for every candidate, no empty cells
- Two or three categories chosen and written above with reasons
- The findings summary from weeks 1 to 3 written in
  `findings-summary.md`, using the template in this folder
- One page of implications for the MVP, carried into week 8
