# 0007: In the pilot, the buyer pays the brand directly and the platform invoices commission

- **Status:** accepted
- **Date:** 2026-11-28
- **Decided by:** the repository owner
- **Affects:** orders, payments, logistics, disputes, commission, brand policy
- **Amends:** [0004](0004-money-held-until-the-buyer-confirms.md), which still
  holds for brands settled through the platform

## Context

Phase 6 has no budget. Holding buyers' money needs a registered company,
merchant accounts with JazzCash, Easypaisa or a card acquirer, and a bank
account the platform controls. Booking couriers through the platform needs a
courier contract and API access. None of that exists, and none of it is free.

Brands in Pakistan already ship cash on delivery with their own couriers every
day. A pilot that asks them to keep doing exactly that, and only to record the
order on the platform, costs nothing and asks nothing new of them.

## Decision

1. **A settlement mode per brand.** `brand_policies.settlement_mode` is
   `platform` (the 0004 model) or `direct`. It is copied onto each order when
   it is placed, like the commission rate, so changing a brand's mode never
   changes how an existing order settles.
2. **Direct is the pilot default.** New brands take `DEFAULT_SETTLEMENT_MODE`,
   `direct` in the pilot. Existing rows stay `platform`.
3. **A direct order holds no money.** It is cash on delivery only and creates
   no payment record. The brand books its own courier, and the brand or an
   admin types the courier's name and tracking number in. The brand records
   the outcome: delivered and paid, or refused at the door, which cancels the
   order and returns the stock.
4. **Commission is invoiced, not deducted.** On confirmation the commission due
   is fixed on the order, less any refund the brand made after a dispute. On the
   first of each month every brand with confirmed direct orders gets one
   invoice for the month before. An admin records the brand's payment with its
   bank reference. Nothing in this path moves money.
5. **Disputes still go to a person.** An admin decides, and records the refund
   the brand makes to the buyer directly. A refund of all the goods reverses the
   sale and no commission is owed.
6. **The integrations stay.** The payment providers and the courier interface
   are unchanged. A brand moved to `platform` uses them exactly as before, once
   real providers are connected.

## Consequences

- The pilot runs with no merchant account, no courier contract and no company
  bank account. The production guard no longer requires a real IBAN while the
  default mode is `direct`.
- The buyer carries the brand's delivery risk, as with any cash on delivery
  order today. The dispute window and the admin's decision are the protection;
  the platform cannot refund anyone itself.
- Commission is collected after the fact, so a brand can fall behind. The
  admin page shows what is due and overdue; nothing is enforced automatically.
- Tracking is only as good as what the brand types. There is no courier
  callback for a direct order, so delivery is the brand's word, which the buyer
  can dispute.
