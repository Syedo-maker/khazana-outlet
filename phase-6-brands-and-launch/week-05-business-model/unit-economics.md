# Week 5: Unit economics

Purpose: find out whether a single order makes money before you build a
platform that processes thousands of them. This is the model that decides the
commission rate, the minimum lot size and whether cash on delivery is
affordable.

All figures below marked `[PLACEHOLDER]` are illustrative structure, not
research. Replace every one with a number from weeks 2 and 3. The model is
useless until you do.

## The three prices that drive everything

| Symbol | Meaning | Source |
| --- | --- | --- |
| R | Original retail price per piece | Brand website or tag |
| B | What the brand accepts per piece | Brand interviews, question 6 |
| P | What the reseller pays per piece | Reseller interviews, question 5 |

The platform lives in the gap between B and P. If that gap is small, there is
no room for a commission and the model must change.

## Revenue per order

```
Lot size          Q    = pieces in the lot
Buyer pays        GMV  = Q * P
Commission rate   c    = agreed percent, from brand interviews
Platform revenue  Rev  = GMV * c
Brand receives    Pay  = GMV - Rev
```

Note the direction carefully. The plan charges the commission to the brand,
so the buyer pays GMV and the brand receives GMV minus commission. If you
ever add a buyer fee, add it as a separate line, never fold it into c.

## Cost per order

| Cost | Symbol | How to estimate it |
| --- | --- | --- |
| Payment processing | `f_pay` | Gateway percent plus fixed fee, get the real rate from JazzCash or Easypaisa in week 5 |
| Cash on delivery fee | `f_cod` | Courier COD service charge, usually a percent of collected amount |
| Courier freight | `f_ship` | Weight based, per kg, per city pair |
| Return and failed delivery loss | `f_ret` | Return rate times the cost of a return trip |
| Photography and listing | `f_list` | Your time or a hired photographer, per lot |
| Support and dispute handling | `f_supp` | Minutes per order times loaded hourly cost |
| Packaging | `f_pack` | Per parcel |

```
Total cost     Cost = f_pay + f_cod + f_ship + f_ret + f_list + f_supp + f_pack
Contribution   CM   = Rev - Cost
Margin         CM%  = CM / GMV
```

## Worked example with placeholder numbers

Structure only. Every number here is invented to show the arithmetic.

```
R   = 2,000 PKR      [PLACEHOLDER]  retail price per piece
B   = 400 PKR        [PLACEHOLDER]  brand accepts, 20 percent of retail
P   = 500 PKR        [PLACEHOLDER]  reseller pays, 25 percent of retail
Q   = 100 pieces     [PLACEHOLDER]  one lot

GMV = 100 * 500      = 50,000 PKR
c   = 15 percent     [PLACEHOLDER]
Rev = 50,000 * 0.15  = 7,500 PKR
Pay = 50,000 - 7,500 = 42,500 PKR to the brand

Costs
f_pay  = 50,000 * 0.025        = 1,250   [PLACEHOLDER gateway 2.5 percent]
f_cod  = 0 if prepaid          = 0
f_ship = 20 kg * 120 PKR/kg    = 2,400   [PLACEHOLDER]
f_ret  = 50,000 * 0.03         = 1,500   [PLACEHOLDER 3 percent loss]
f_list = 500 per lot           = 500     [PLACEHOLDER]
f_supp = 30 min at 600 PKR/hr  = 300     [PLACEHOLDER]
f_pack = 150                   = 150     [PLACEHOLDER]
Cost   = 6,100 PKR

CM  = 7,500 - 6,100 = 1,400 PKR
CM% = 1,400 / 50,000 = 2.8 percent of GMV
```

Read what that example is telling you. At a 15 percent commission the order
clears only 1,400 rupees, and a single return or one extra support call wipes
it out. That is the normal shape of marketplace economics at small lot sizes,
and it drives three conclusions you should test in week 5:

1. Lot size is the strongest lever you control. Freight, listing, packaging
   and support are mostly fixed per order, so doubling Q roughly doubles
   revenue while costs rise far less. Set a minimum lot value, do not sell
   10 piece lots in the B2B phase.
2. Cash on delivery is expensive twice over, once in the COD fee and again in
   the return rate. For B2B orders, prepayment with escrow protection is
   worth insisting on. Save COD for B2C in year 2.
3. The commission has to be tested, not assumed. Run the sensitivity table
   below with your real B and P before you promise any brand a rate.

## Sensitivity table to complete

Fill this with your real figures, one table per starting category.

| Lot value (GMV) | c = 5% | c = 10% | c = 15% | c = 20% |
| --- | --- | --- | --- | --- |
| 25,000 | | | | |
| 50,000 | | | | |
| 100,000 | | | | |
| 250,000 | | | | |
| 500,000 | | | | |

Each cell holds the contribution margin in rupees. Then answer:

- What is the minimum lot value where the order is profitable at the
  commission brands actually accepted?
- That number is your minimum order value. Put it in the MVP requirements.

## Break even for the business

```
Monthly fixed costs  F  = salaries + hosting + AI API + marketing + office
Average CM per order    = from the model above
Orders needed to break even = F / average CM per order
```

Fill `../trackers/unit-economics.csv` with your real numbers and keep that
file updated as prices change. Then write the single most important sentence
of Phase 0 here:

> To cover [F] rupees per month we need [N] orders per month at an average lot
> value of [GMV], which means [M] active brands and [K] active resellers.

If N looks impossible for year 1, the fix is one of four things, in this
order: raise lot sizes, raise the commission, cut fixed costs, or add the
logistics fee from Phase 2 earlier. Do not fix it by hoping for volume.

## Costs to confirm with real quotes in week 5

Do not model these from blogs, get quotes.

- JazzCash and Easypaisa merchant rates, settlement time, setup requirements
- A card gateway, for example Safepay or PayFast, rates and onboarding
- Courier rates from at least three of TCS, Leopards, PostEx, M&P and Trax,
  including the COD service charge and the COD settlement time, which
  differs a lot between providers and affects your cash flow directly
- Warehouse or storage cost per square foot in your city, in case you need to
  hold stock during the manual test
