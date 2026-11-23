# Performance

What was measured, on what, and what changed because of it. Every number here
comes from a run you can repeat with the commands shown. When the code or the
hardware changes, rerun them and replace the numbers rather than keeping old
ones next to new ones.

## The budget

A reseller in Multan on a mid range Android phone over a patchy 3G connection.
The network takes most of the time on every page, so the server's share has to
be small.

| Measure | Budget |
| --- | --- |
| API p95 for the catalogue, search and a lot page | under 500 ms at the expected load |
| API error rate under load | under 1% |
| Queries per list request | constant, whatever the number of brands on the page |

## Load test: the catalogue and search

`loadtest/catalog-search.js` is a k6 script. Each virtual user browses the
catalogue, searches and opens a lot, with pauses of one to four seconds
between steps the way a person reads a page. `THINK=0` removes the pauses and
turns it into a capacity test.

```powershell
.\scripts\dev.ps1 seed --reset --scale 17   # about 500 lots
.\scripts\dev.ps1 loadtest                  # 50 users, with pauses
.\scripts\dev.ps1 loadtest THINK=0 VUS=20   # capacity, no pauses
```

k6 runs from its own image, so nothing is installed. One reseller signs in
once and every virtual user shares the token, because signing in per user
would hit the limit of five codes an hour per phone number.

### Results, week 50, 2026-11-23

The development stack on the development laptop: one API process under
`uvicorn --reload`, PostgreSQL 16 in Docker, 510 lots of which 226 are live.

| Run | Catalogue p95 | Search p95 | Lot page p95 | Requests a second | Errors |
| --- | --- | --- | --- | --- | --- |
| 30 lots, 50 users with pauses | 54 ms | 51 ms | 58 ms | 17.8 | 0% |
| 500 lots, 50 users with pauses, **before the fix** | **875 ms** | 511 ms | 511 ms | 17.0 | 0% |
| 500 lots, 50 users with pauses, after the fix | 58 ms | 51 ms | 59 ms | 17.3 | 0% |
| 500 lots, 20 users, no pauses, before the fix | 1,530 ms | 1,050 ms | 1,030 ms | 27.9 | 0% |
| 500 lots, 20 users, no pauses, after the fix | 755 ms | 689 ms | 850 ms | 40.3 | 0% |

**What the first run found.** At 30 lots everything was comfortably inside
the budget, which is why nothing had shown it before. At 500 lots the
catalogue's p95 was 875 ms. Counting the statements per request showed why:
the catalogue loaded each lot's brand with its own query, so a page of 20
lots from 20 brands made 20 extra round trips. Search, recommendations and the
mixed lot builder had the same pattern.

**The fix.** `approval_service.preload_brands` loads every brand on the page in
one query and attaches each to its lot. A catalogue page went from 31
statements to 11. `tests/test_query_counts.py` fails if a list request ever
costs more queries with nine brands on the page than with two.

The same pass also merged the two `set_config` calls made on every
authenticated request, which set the tenant for the row level policies, into
one statement.

**What the capacity numbers mean.** With no pauses, 20 users is about what a
single development process can serve before queueing sets in, roughly 40
requests a second. That process reloads on every file change and runs one
worker. The production image runs several workers; its numbers are in the
staging section below once it exists.

## Week 52: slow connections, query plans and payload

### How it was measured

`e2e/perf/throttled.spec.ts` loads the main pages in a phone sized Chromium
with Chrome DevTools' Regular 3G profile (750 kbit/s down, 250 kbit/s up,
300 ms latency) and the CPU slowed four times, about a mid range Android
phone. Every page is a first visit with an empty cache. It runs against the
production build, never the dev server:

```powershell
docker build --target runtime -t khazana-web:runtime apps/web
docker run --rm -p 3000:3000 khazana-web:runtime
cd e2e; npx playwright test -c playwright.perf.config.ts perf/throttled.spec.ts
```

It is not in CI. Timings on a shared runner change run to run by more than
the effects being measured, and a number that moves every run is worse than
none. Repeat runs on this laptop vary by several hundred milliseconds too, so
read the table for its shape.

| Page | Heading on screen | LCP | Transferred | of which script | Requests |
| --- | --- | --- | --- | --- | --- |
| Login | 1.4 s | 1.2 s | 143 KB | 134 KB | 9 |
| Catalogue | 3.2 s (was 4.1 s) | 4.5 s | 202 KB | 143 KB | 37 |
| Lot | 4.1 s | 4.7 s | 223 KB | 149 KB | 33 |
| Orders | 3.2 s | 3.8 s | 160 KB | 140 KB | 20 (was 28) |
| Brand dashboard | 4.1 s | 4.1 s | 157 KB | 142 KB | 17 (was 20) |
| Brand lots | 1.5 s | 4.2 s | 204 KB | 144 KB | 24 |

Seed photographs are small placeholders, so the photo savings below were
measured separately on realistic images.

### What the request waterfall showed, and what changed

1. **Every catalogue card downloaded the full 1024 pixel photo**, as soon as
   it mounted, including cards far below the fold. Cards now ask for a 400
   pixel copy, `?size=thumb`, made on first request and kept beside the
   original. On a textured 1600 pixel photograph the stored copy is 165 KB
   and the thumbnail 11 KB, 94% smaller; a page of 24 cards goes from about
   4 MB of photos to about 260 KB. Photos also wait until they are within
   300 pixels of the screen before downloading.
2. **Next.js prefetched every visible link**: each lot card, and every page
   in the menu. On a metered connection that spends the buyer's data on pages
   they may never open, and competes with the page they are reading. Lot cards
   and menu links no longer prefetch.
3. **Every API call costs two round trips.** The web app and the API are on
   different origins, and the `Authorization` header makes the browser send a
   CORS preflight before each new URL, every photo included. At 300 ms
   latency that is most of a second per call before any data moves. The
   preflight answer is now cached for two hours instead of ten minutes, which
   helps repeat calls. Production removes preflights entirely by serving the
   API under the web app's own origin at `/api`; the web app already accepts
   a path as its API base for that. Measured on the staging stack in week 56.
4. **The JavaScript is about 140 to 160 KB compressed per page**, and takes
   about two seconds to arrive on Regular 3G before the page can hydrate.
   That is the floor for every page and the next thing to reduce: the shared
   React and Next.js chunks are most of it.

### Query plans and N plus 1 queries

Every query behind the main pages was captured and run through `EXPLAIN
ANALYZE` on the 510 lot database. No single statement took over 5 ms and none
did a sequential scan over more than 200 rows; the indexes from migration
0016 cover what the pages filter by.

Counting statements per request found two more lists that grew with their
length, both now fixed and guarded in `tests/test_query_counts.py`:

| Request | Before | After |
| --- | --- | --- |
| A brand's order list, 50 orders | 204 queries, 210 ms | 8 queries, 110 ms |
| The admin listing queue, 50 lots | 207 queries, 172 ms | 8 queries, 52 ms |

Each order loaded its lot, the lot's brand, the buyer and the buyer's profile
one at a time; each listing loaded its manifest, defects, photos and category
again for the risk score, though the query had already loaded three of them.

### Images and bundle

- Uploaded photographs are resized to 1024 pixels and stored as JPEG at
  quality 80; thumbnails are 400 pixels at quality 72, progressive.
- The production web image now uses Next.js standalone output: 458 MB
  against 2.27 GB for the development image, with no development packages
  in it.
- Static assets are served with Next.js's immutable cache headers; photos
  are `private, max-age=300`, because every one sits behind sign in.
