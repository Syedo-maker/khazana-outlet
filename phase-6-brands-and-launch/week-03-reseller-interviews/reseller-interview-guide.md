# Week 3: Reseller and buyer interview guide

Target: 20 to 30 interviews with resellers, shopkeepers and online sellers.
These are faster than brand interviews, 10 to 15 minutes each, and you can do
several in an afternoon by walking a market.

The buyer side is where most marketplaces die. A marketplace with supply and
no demand is a warehouse. Week 3 exists to stop that happening.

Note on language: as in week 2, the text here is English for the repository.
Speak Urdu when you are in the market.

## Who to interview, and the mix to aim for

| Buyer type | Where to find them | Target count |
| --- | --- | --- |
| Small shop owners | Local markets in your city, 2 or 3 markets | 8 to 10 |
| Online resellers | Instagram and Facebook resale pages, WhatsApp groups | 6 to 8 |
| Daraz and marketplace sellers | Daraz seller groups, seller meetups | 4 to 5 |
| Wholesale buyers | Zainab Market, Azam Cloth Market, Shah Alam | 3 to 4 |
| Bulk buyers from other cities | Small town shopkeepers, ask city contacts | 3 to 4 |

The last row matters more than it looks. Small town and secondary city buyers
have the least access to branded stock and the least competition, so they are
your most likely early demand. Do not interview only Karachi and Lahore.

## Outreach

### In person, walking a market

This is the best method for this week. Walk in, buy something small first if
it helps, then:

> Hello, I have one question if you have two minutes. If branded leftover
> stock from a company like [a brand they would know] were available in bulk
> at a wholesale price, with the count and sizes guaranteed, would that be
> something you buy? Where do you buy that kind of stock today?

Then run the questions below. Keep it conversational, do not read from a
sheet in front of them.

### WhatsApp or Instagram DM for online resellers

> Hello, I run a research project on where resellers in Pakistan buy branded
> leftover stock in bulk. Could I ask you four or five questions about how you
> buy? I am not selling anything, and I will share what I find with you.

### In Facebook and WhatsApp reseller groups

Post once, do not spam:

> I am researching how resellers buy branded leftover and surplus stock in
> bulk, what goes wrong, and what you wish existed. If you buy bulk lots and
> can spare 10 minutes on a call, please comment or message me.

The people who reply to this post are your first 50 waiting list entries.
Capture every one in `../trackers/reseller-pipeline.csv`.

## The questions

### Part 1: what they sell today (3 minutes)

1. What do you sell, and where? One shop, several, online, or both?
2. Roughly how much stock do you buy in a month, in rupees?
3. What is your best selling category?

### Part 2: how they buy today (5 minutes)

4. Where do you buy your stock? Name the markets, dealers or groups.
5. When you buy a bulk lot, how much do you pay compared to retail price?
6. How do you pay: cash in advance, on delivery, or credit?
7. How do you know what is actually in the lot before you pay?
8. What is the largest single lot you have bought, in rupees?

Question 6 is critical for the payments module. If resellers in this market
expect credit from their dealer, an advance payment platform will struggle,
and escrow plus a credit facility becomes a Phase 2 priority rather than a
nice extra.

### Part 3: what goes wrong (4 minutes)

9. Tell me about the last time a bulk purchase went badly. What happened?
10. Have you ever paid in advance and received nothing, or received fakes or
    the wrong count?
11. How do you handle a lot you cannot sell?

Question 10 is your trust feature list. Write down the stories, count how
many people have been cheated, and use the number. If 18 of 25 resellers have
lost money on an advance payment, escrow is not a feature, it is the product.

### Part 4: the offer (4 minutes)

12. If original branded stock from a known Pakistani brand were available in
    lots of [typical size] at [typical percent] off retail, with a guaranteed
    count and size breakdown, how many would you buy in a month?
13. What would you need to see before you paid: photos, a video, a manifest,
    a sample, a visit?
14. Would you pay before delivery if the money were held by the platform and
    released only after you confirmed the goods?
15. Which brands would sell fastest in your area?
16. May I add you to the list for the first sale? What is your city and
    WhatsApp number?

Question 16 is the week's deliverable. Every interview ends with it.

## Price discovery, the quiet goal of this week

By the end of week 3 you should be able to fill this table from real answers,
not estimates. It is the input to the week 5 unit economics.

| Category | Retail price | What a brand gets from a dealer | What a reseller pays a dealer | What a reseller sells at |
| --- | --- | --- | --- | --- |
| | | | | |

The gap between column 3 and column 4 is the dealer margin. That gap is the
space your commission has to live in. If it is narrow, the business is hard
and you need to know now.

## After every interview

1. Add a row to `../trackers/reseller-pipeline.csv`
2. If they agreed to the waiting list, add them to
   `../trackers/waiting-list.csv` with city and WhatsApp number
3. Write a notes file only for the interviews that taught you something new,
   using `reseller-interview-notes-template.md`. For routine ones the tracker
   row is enough.

## What a successful week 3 looks like

- 20 or more interviews done
- 30 or more names on the waiting list, heading for the 50 you need
- The price discovery table filled for your two or three likely categories
- A counted list of what goes wrong when resellers buy bulk today
- A clear view of whether resellers will pay in advance with escrow, or
  whether cash on delivery is unavoidable in this market
