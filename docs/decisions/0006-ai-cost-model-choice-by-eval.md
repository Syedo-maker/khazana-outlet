# 0006: A cheaper model only where a live eval says so

- **Status:** accepted
- **Date:** 2026-11-24, from the week 53 live eval run
- **Decided by:** the repository owner
- **Affects:** the router, the response cache, the batch path

## Context

The cheapest way to cut an AI bill is a cheaper model, and the cheapest way
to lose a brand's trust is a cheaper model that quietly makes worse
decisions. Claude Haiku 5.5 costs a tenth of Haiku 4.5. In week 53 it was
tried on every route Haiku served.

## Decision

1. **The eval decides the model.** A route moves to a cheaper model only when
   its eval suite passes live, over several runs. Haiku 5.5 passed every
   resell kit case and serves that route. It failed the same markdown case and
   the same risk scoring case on every run at low and medium effort, and ran
   out of tokens thinking at high effort, so those routes stay on Haiku 4.5.
   The router records the evidence beside each route.
2. **Free savings first.** Prompt caching on every route whose prefix is long
   enough, a response cache for identical requests on the five features where
   the same input deserves the same answer, and the Message Batches API at
   half price for the one model job nobody waits for, the daily markdown run.
3. **Evals bypass the response cache**, because an eval measures the model.

## Consequences

- Each route's model is a decision with evidence, revisited when the eval is
  rerun, not a guess made once.
- The two Haiku 4.5 routes do not cache, because their prompts are shorter
  than Haiku 4.5's 4,096 token minimum. That costs little on routes this
  cheap, and is a reason to try Haiku 5.5 again when its eval allows.
- The whole week 53 pass, every rerun included, cost USD 1.03.
