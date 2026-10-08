# Lot listing and manifest template

Copy this for every lot as `lot-<number>-<brand-or-code>.md`. This document
is the thing buyers trust or do not trust, so accuracy matters more than
presentation. It is also the direct model for the lot data structure in M3,
so keep the fields stable.

## Listing header

| Field | Value |
| --- | --- |
| Lot code | LOT-0001 |
| Brand name | |
| Brand shown publicly | yes / hidden |
| Public description if hidden | for example, leading Pakistani lawn brand |
| Category | |
| Season or year | |
| Total pieces | |
| Original retail price per piece (PKR) | |
| Lot price (PKR) | |
| Price per piece (PKR) | |
| Discount vs retail | percent |
| Minimum order | whole lot / part lot, minimum pieces |
| Condition grade | A, B or C, see below |
| Location of stock | city |
| Cities excluded | region lock, if any |
| Available until | date |

## Condition grades, use these exactly

| Grade | Meaning |
| --- | --- |
| A | New, unused, with tags, no defects |
| B | New or unused but no tags, minor shelf wear, no functional defect |
| C | Factory seconds or visible defects, described individually below |

Never list a C lot as B. One misgraded lot costs more in lost trust than the
whole lot is worth.

## Size and colour breakdown

The single most important part of the manifest. Buyers refuse lots because a
size curve is unusable, and they are right to.

| Size | Colour | Pieces |
| --- | --- | --- |
| | | |
| | | |
| **Total** | | |

The total here must equal the total pieces in the header. Check it twice.

## Defects and notes

List every defect honestly, with the number of pieces affected.

| Issue | Pieces affected | Photograph reference |
| --- | --- | --- |
| | | |

## Photographs checklist

- [ ] Full lot as stored, so the buyer sees the real volume
- [ ] One piece, front
- [ ] One piece, back
- [ ] Brand label and care label, or the label obscured if the brand is hidden
- [ ] Size and colour spread laid out
- [ ] Every defect listed above
- [ ] Packaging as it will be shipped

## Logistics

| Field | Value |
| --- | --- |
| Total weight (kg) | |
| Number of cartons | |
| Carton dimensions | |
| Courier | |
| Freight cost quoted (PKR) | |
| Who pays freight | buyer / seller / shared |
| Expected transit days | |

## Commercial terms shown to the buyer

| Field | Value |
| --- | --- |
| Payment | advance bank transfer / JazzCash / Easypaisa |
| Returns | state the policy plainly, including what is not returnable |
| Dispute window | number of days to report a mismatch after delivery |

## Internal only, not shown to the buyer

| Field | Value |
| --- | --- |
| Brand floor price | |
| Our commission (percent and PKR) | |
| Consignment or purchased outright | |
| Agreed payout date to brand | |
| Protection level agreed in writing | yes / no, and where it is recorded |

## Outcome, filled in after the lot closes

| Field | Value |
| --- | --- |
| Sold or unsold | |
| Date listed | |
| Date sold | |
| Days to sell | |
| Final price achieved | |
| Buyer | |
| Buyer city | |
| Actual freight cost | |
| Complaints or disputes | |
| Brand paid on | |
| Our actual margin after all costs | |

Copy this row into `../trackers/manual-sales-tracker.csv` so the whole week
can be analysed in one place.
