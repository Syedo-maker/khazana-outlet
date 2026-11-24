# 0002: Every model call goes through one gateway, offline by default

- **Status:** accepted
- **Date:** decided in Phase 1, recorded 2026-11-24
- **Decided by:** the repository owner
- **Affects:** every AI feature

## Context

An AI native marketplace makes model calls from many places: listings,
manifests, pricing, risk, the assistants, bargaining, markdowns. Left to
themselves, each feature would construct its own client, choose its own model,
and spend money nobody was counting. Tests and CI would either call the real
API, which costs money and fails without a network, or not test the AI path
at all.

## Decision

1. **One gateway.** `ai/gateway` is the only place the Anthropic client is
   constructed. A feature calls `run_feature` with a feature name, a
   versioned prompt and an output schema. The gateway picks the model and
   effort from the router, checks the spend caps and the kill switch, records
   a job, the tokens, the cost and the output, and validates the reply against
   the schema before anything reads it.
2. **Offline by default.** With `AI_OFFLINE=true`, the default everywhere but
   production, the gateway answers from recorded fixtures keyed by the prompt
   version and the rendered input, and makes no network call. The tests, the
   eval suites in CI and every development machine run this way, free.
3. **Every feature has an eval, written first.** A test fails if a feature
   that calls the gateway has no eval suite.

## Consequences

- Changing the model, the effort or the caching of a feature is one line in
  the router, and the evidence for it sits beside it.
- Spend is visible per feature and per brand, and caps stop it before a call.
- Offline evals prove the pipeline and the graders, not the model. Measuring
  the model is a deliberate, paid act: `run --live`, done in week 53 for every
  suite.
- A prompt change needs its fixtures recorded again, or CI fails. That is the
  point.
