# 0004: Money in whole rupees, held until the buyer confirms

- **Status:** accepted
- **Date:** decided in Phase 3, recorded 2026-11-24
- **Decided by:** the repository owner
- **Affects:** orders, payments, payouts, disputes

## Context

Resellers buying surplus stock from brands they have never dealt with need to
know they will get what they paid for. Brands need to know they will be paid.
In this market, cash on delivery is common and trust in online payment is
low.

## Decision

1. **Whole rupees as integers.** No floating point anywhere money is stored.
   The order's total, the commission and the brand's payout are related by
   check constraints in the database, so an order that does not add up cannot
   be saved.
2. **Held, then released.** A buyer's payment is held by the platform. It is
   released to the brand only when the buyer confirms the goods arrived, or
   when the dispute window the brand's policy sets has passed with no dispute.
3. **A person decides disputes.** An admin refunds in full, refunds in part or
   finds for the seller. Nothing automatic moves held money back.
4. **Payouts in runs.** Released money becomes a payout scheduled under the
   brand's payout terms, sent by an admin in a run and marked paid with the
   bank reference.

## Consequences

- A buyer's risk is limited to the dispute window; a brand's to the time
  until confirmation.
- The platform holds money in transit, which has regulatory weight. The
  payment providers' merchant agreements and legal advice settle how, before
  launch.
- The end to end money path is tested over HTTP from checkout to payout, and
  in a browser, on every push.
