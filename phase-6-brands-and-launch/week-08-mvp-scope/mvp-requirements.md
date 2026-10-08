# Week 8: Requirements check and pilot findings

## How to use this document now that the order has changed

This was written to define the MVP before it was built. In the current
[roadmap](../../ROADMAP.md) the platform is built first, so this document has
a different job: it is the checklist you run the finished platform against,
and the place you record what the pilot proved was missing.

Read every requirement below as a question. Does the platform do this, and
does it do it the way real brands and real buyers just showed you they need
it? Three columns of answers matter:

| Verdict | What to do |
| --- | --- |
| Built and correct | Tick it, move on |
| Built but wrong | Record the gap here, fix it before public launch |
| Not built, and now proven necessary | Record it, decide whether it blocks launch |

The last category is the valuable output of this week. It is also the reason
the roadmap keeps commission rates, discount bands, protection rules and lot
minimums as configuration rather than code: most of what the pilot teaches
should be a settings change, not a rebuild.

## Scope rule for the MVP

One sentence to settle every argument in Phase 1:

> The MVP exists to do by software exactly what you did by hand in week 7, for
> ten times the volume, without you being in every conversation.

If a proposed feature was not needed in week 7, it is not in the MVP. Write it
in the deferred list instead. The deferred list is not a rejection, it is a
Phase 2 queue.

## Confirmed MVP scope, from the plan

B2B only. No B2C storefront, no mobile app, no AI beyond smart upload.

| Module | In MVP | Build weeks | Notes |
| --- | --- | --- | --- |
| M1 Auth and roles | yes | 12 to 13 | Phone OTP, email, roles brand, reseller, admin. No customer role yet |
| M2 Brand portal | yes | 14 to 15 | Verification with NTN and company documents, dashboard |
| M3 Product catalog | yes | 16 to 17 | Lot listing with manifest, single and Excel or CSV bulk upload, photos |
| M4 Search and filters | yes | 19 | Brand, price, category, city |
| M5 Cart and orders | yes | 20 to 21 | Bulk order, order tracking. Returns policy enforced manually at first |
| M6 Payments | partly | 22 | COD plus bank transfer plus one gateway. Escrow and automated payouts move to Phase 2 |
| M7 Logistics | partly | 23 | One courier only, shipping charges |
| M8 Admin panel | yes | 24 to 25 | Approvals, orders, commission, payouts |
| M9 AI engine | smart upload only | 18 | Photo to title, description, category |
| M10 Analytics | no | deferred | A weekly email of basic numbers is enough for the MVP |

## The manifest is the core data structure

Week 7 will have shown that buyers trust or reject a lot based on its
manifest. So the lot record is not a product record with a quantity, it is a
structured manifest. Minimum fields, carried straight from
`../week-07-manual-sales-test/lot-listing-template.md`:

- Lot code, brand, brand visibility setting, public description when hidden
- Category, season, condition grade A, B or C
- Total pieces, with a size and colour breakdown that must sum to the total
- Original retail price per piece, lot price, derived price per piece and
  derived discount percent
- Minimum order quantity
- Defect list with pieces affected
- Photograph set with a required minimum count
- Weight, cartons, stock location, excluded cities
- Available until date

Two validation rules that must exist in the MVP, because both failures
destroy buyer trust:

1. The size and colour breakdown must sum exactly to the total pieces, and
   the listing cannot be submitted if it does not.
2. A listing cannot go live without the brand's recorded approval, with a
   timestamp and the approving user. The approval is an audit record, not a
   checkbox.

## Brand protection requirements

These are not optional features, they are the reason brands will list at all.
Record which ones brands actually demanded in week 2 and build those first.

| Requirement | Demanded by n brands | In MVP |
| --- | --- | --- |
| Private listings, visible only to verified resellers | | |
| Hide brand name, show category and quality only | | |
| Exclude named cities from a lot | | |
| Brand approves every listing before it is visible | | yes, mandatory |
| Brand can withdraw a listing at any time | | yes, mandatory |

The last two are mandatory regardless of what the interviews say, because
without them no brand can safely try the platform once.

## User stories for the MVP

Write acceptance criteria for each one before building. These are the minimum
set, add the ones week 7 proved you need.

### Brand

1. As a brand, I can register and submit my NTN and company documents for
   verification, and see my verification status.
2. As a brand, I can create a lot with a full manifest and upload photographs.
3. As a brand, I can upload many lots from an Excel or CSV file.
4. As a brand, I can set the protection level per lot: name visible, name
   hidden, cities excluded.
5. As a brand, I must approve a listing before it becomes visible to buyers.
6. As a brand, I can withdraw a listing that has no active order against it.
7. As a brand, I can see my orders, what I am owed, and when I was paid.

### Reseller

8. As a reseller, I can register with my phone number and be verified as a
   business buyer.
9. As a reseller, I can search and filter lots by category, price, city and
   brand, where the brand is visible.
10. As a reseller, I can see the full manifest, the condition grade, the
    defect list and the photographs before ordering.
11. As a reseller, I can place an order for a whole lot or the minimum
    quantity, and pay by the available methods.
12. As a reseller, I can track my order and confirm or dispute delivery
    within the dispute window.

### Admin

13. As an admin, I can approve or reject brand and reseller verifications
    with a recorded reason.
14. As an admin, I can moderate any listing before it goes live.
15. As an admin, I can see every order, change its status, and record a
    payout to a brand.
16. As an admin, I can set the commission rate per brand, because week 2 will
    almost certainly show that one global rate does not fit every brand.

## Explicitly out of the MVP

Record these so they are not argued about again in week 20.

- B2C storefront and consumer accounts
- Mobile applications
- Escrow automation and automated payouts, handled manually in the MVP
- AI pricing, shopping assistant, recommendations, visual search
- Reviews and ratings
- Multiple couriers
- Analytics dashboards
- Subscriptions and featured listings
- Multi language interface

## Non functional requirements

These are cheap to specify now and expensive to retrofit.

| Requirement | Target |
| --- | --- |
| Works on a mid range Android phone on 3G | Page usable within 5 seconds |
| Mobile first layout | Designed at 360px before desktop |
| Image handling | Server side compression, lazy loading, no 5MB originals served to phones |
| Data safety | Daily database backup, tested restore before launch |
| Secrets | No credentials in the repository, environment variables only |
| Audit trail | Every listing approval, order status change and payout is logged with user and timestamp |
| Access control | Tested so that no brand can see another brand's lots or orders |

The access control row deserves a dedicated test suite. In a marketplace where
competing brands list on the same platform, one leak between two brands ends
the business.

## Open decisions to settle before week 9

| Decision | Options | Decided | Why |
| --- | --- | --- | --- |
| Custom build or a Shopify or WooCommerce shortcut first | | | The plan allows a 4 to 6 week no code test if money or time is tight |
| Backend language | NestJS or FastAPI | | Choose what your developers actually know |
| Hiring plan | Two full stack developers, or one plus yourself | | |
| Consignment or purchased stock | | | Decides whether you need inventory cash |
| Starting city | | | One city in the MVP keeps logistics simple |
| Commission rate per brand or global | | | |

## Definition of done for week 8

- This document completed with every blank filled
- `go-no-go-review.md` completed and signed with a date
- Phase 1 week by week plan confirmed or amended with reasons
- The build order revised so that whatever consumed most of your time by hand
  in week 7 is built first
