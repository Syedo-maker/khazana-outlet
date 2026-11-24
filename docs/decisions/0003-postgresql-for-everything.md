# 0003: PostgreSQL for data, search and vectors, one datastore

- **Status:** accepted
- **Date:** decided in Phase 1, recorded 2026-11-24
- **Decided by:** the repository owner
- **Affects:** the database, catalogue search, visual search, tenancy

## Context

A marketplace needs relational data with strict money rules, text search over
a catalogue, and vector search for "find lots that look like this
photograph". The usual answer is three systems: a database, a search engine
and a vector store. For a launch catalogue of hundreds of lots, run by one
person, each extra system is another thing to operate, back up, secure and
keep consistent.

## Decision

PostgreSQL 16 holds everything:

- Relational data, with check constraints that make money add up in the
  database itself, and append only audit tables enforced by triggers.
- Full text search for the catalogue.
- Image and text embeddings in `pgvector`, with cosine ranking in SQL.
- Row level security policies as a second line behind the application's own
  tenancy checks.

Redis is in the stack for later use as a queue and cache, and is not yet
read by the application.

## Consequences

- One thing to back up and restore, and one backup proves everything comes
  back (`scripts/verify-restore.sh`, run in CI).
- The tests run on SQLite for speed, so PostgreSQL only behaviour, vector
  ranking, triggers and the row level policies, has its own suite run against
  a disposable PostgreSQL database.
- When the catalogue outgrows PostgreSQL's text search, a search engine is
  added then, fed from the database, not instead of it.
