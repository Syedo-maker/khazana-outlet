# 0005: In production, the API is served under the web app's origin

- **Status:** accepted
- **Date:** 2026-11-24, from the week 52 and 56 measurements
- **Decided by:** the repository owner
- **Affects:** deployment, the web app's API address, CORS

## Context

In development the web app runs on port 3000 and the API on port 8000, two
origins. Every API call carries an `Authorization` header, which makes the
browser send a CORS preflight request first for every new URL, each photograph
included. The week 52 measurements on a throttled 3G profile showed every API
call costing two round trips, at 300 ms latency most of a second before any
data moved.

## Decision

Production serves both from one host behind Caddy: the web app at `/`, the
API at `/api`. The web app is built with `NEXT_PUBLIC_API_BASE_URL=/api`, the
API runs with `--root-path /api`, and Caddy strips the prefix. Development
keeps two origins, because two dev servers on two ports is simpler there.

## Consequences

- No preflights in production. On staging the catalogue and lot pages make
  half the requests they did.
- One certificate, one host name and one Content Security Policy that allows
  connections only to `'self'`.
- The API must know how many proxies are in front of it to read the client's
  address, so `TRUSTED_PROXY_COUNT=1` is required and production refuses to
  start without it.
- `/metrics` is under the same host, so Caddy refuses it explicitly.
