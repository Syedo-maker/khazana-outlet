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
