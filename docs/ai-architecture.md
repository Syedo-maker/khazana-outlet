# AI architecture

How Khazana Outlet is AI native rather than an app with a chatbot attached.
This document is the reference for Phase 1 week 5 and the whole of Phase 2.

## 1. What "totally AI based" means here

It means AI sits in the critical path of the work the platform exists to do,
not beside it.

| Core job of the platform | How it is done without AI | How it is done here |
| --- | --- | --- |
| Turn a pile of stock into a sellable listing | A person types 30 fields per lot | Photos in, a complete draft listing out, the person corrects it |
| Clean a brand's messy spreadsheet | Someone retypes it | Extracted, reconciled, and every change flagged for review |
| Decide the discount | Guesswork | A suggested band with an expected days to sell, and the reasoning shown |
| Help a buyer find stock | Filters and dropdowns | A sentence or a photograph, in Urdu, Roman Urdu or English |
| Catch a bad listing or a fake | Nobody catches it | Risk scored before it goes live |
| Tell a brand what is dying in the warehouse | A quarterly report nobody reads | A question answered in plain language from that brand's own data |

If you removed the AI layer, the platform would still run, and that is the
point: it would be a worse version of itself in every one of those six rows,
which is how you know AI is load bearing and not decoration.

## 2. What AI is never allowed to decide

This list is a hard boundary, not a guideline. Every item is either money or
irreversible, and the plan already requires a brand approval audit trail.

| Decision | Who decides | AI's role |
| --- | --- | --- |
| Whether a listing goes live | The brand, with a recorded approval | Prepares the draft and scores the risk |
| The final price | The brand | Suggests a band and explains why |
| Releasing money to a brand | The system, on confirmed delivery, by rule | Nothing |
| Approving a brand or reseller verification | An admin | Flags document mismatches |
| Banning an account or cancelling an order | An admin | Flags and ranks for review |
| Stock levels, prices, order status quoted to a user | The database | Reads it through a tool and reports it |

That last row is the one that kills marketplaces. The assistant answers only
from tool calls against real data. It is instructed and tested to say it does
not know rather than to produce a plausible number. A hallucinated stock
level or price in a B2B negotiation costs you the brand.

## 3. The AI gateway, built in Phase 1 week 5

Every model call in the platform goes through one service. No module calls
the Claude SDK directly. This is the single most important structural
decision in the project.

```
apps/ai/
  gateway/
    router.py          # task -> model, effort, cache policy, batch or live
    prompts/           # versioned prompt files, one per task, never inline strings
    schemas/           # structured output schemas per task
    client.py          # the only place the Anthropic SDK is constructed
    cost.py            # token and cost logging per call, per brand, per feature
    limits.py          # per brand and per feature spend caps, kill switches
    cache.py           # prompt cache policy and result cache
  features/
    listing_from_photos/
    manifest_extract/
    pricing/
    search_embeddings/
    assistant/
    risk_scoring/
  evals/               # one eval suite per feature, run in CI
```

What the gateway gives you that scattered SDK calls never do:

- One place to change the model, so a price change or a new model is a one
  line edit instead of a grep across the codebase
- Cost attribution per feature and per brand, which is how you find out that
  one feature is 80 percent of the bill
- A kill switch per feature, so a misbehaving model does not take the site
  down with it
- Versioned prompts, so you can tell which prompt produced a bad output last
  Tuesday
- A single choke point for prompt injection defence

## 4. Model routing

Current Anthropic models and prices, per million tokens:

| Model | Model ID | Context | Input | Output |
| --- | --- | --- | --- | --- |
| Claude Opus 5.5 | `claude-opus-5-5` | 1M | $4.00 | $20.00 |
| Claude Sonnet 5.5 | `claude-sonnet-5-5` | 1M | $2.00 | $10.00 |
| Claude Haiku 4.5 | `claude-haiku-4-5` | 200K | $1.00 | $5.00 |

Cache reads on Opus 5.5 are $0.20 per million tokens, which is 20 times
cheaper than a fresh read of the same tokens. The Batch API runs
non urgent work at 50 percent of these prices.

Proposed routing. Opus 5.5 is the default everywhere, and the cheaper models
appear only as bulk workers behind it. Switching any row to a cheaper model
is your decision to make, after the eval shows quality holds.

| Task | Model | Effort | Mode | Why |
| --- | --- | --- | --- | --- |
| Photo to listing | `claude-opus-5-5` | medium | live | Vision quality decides listing quality, and listing quality decides whether a brand trusts the platform |
| Manifest extraction from Excel | `claude-opus-5-5`, with `claude-haiku-4-5` as the bulk option | low | batch | Nobody is waiting, so batch at half price |
| Pricing suggestion | `claude-opus-5-5` | medium | live | Reasoning task, and a wrong price is expensive |
| Risk and quality scoring | `claude-haiku-4-5` | n/a | live | High volume classification on every listing, the cheapest place to use a small model |
| Buyer assistant | `claude-opus-5-5` | low | live, streaming | Tool calling and three languages, but a chat turn needs no deep reasoning |
| Brand assistant over own data | `claude-opus-5-5` | medium | live, streaming | Analytical questions over real numbers |
| Demand prediction | `claude-opus-5-5` | high | batch, scheduled | Runs weekly, quality matters more than latency |
| Translation and copy cleanup | `claude-haiku-4-5` | n/a | batch | Bulk, low judgement |

Notes that matter when writing the code:

- Thinking on Opus 5.5 is always on. Do not send `thinking: {type: "disabled"}`
  or `budget_tokens`, both return a 400. Control spend with
  `output_config: {effort: ...}`, whose default on this model is `medium`, so
  set it explicitly per route.
- Forced tool choice is gone on Opus 5.5 and Sonnet 5.5. Use
  `tool_choice: {type: "auto"}` with `strict: true` on the tool, or structured
  outputs when the only reason for the forced call was to get JSON back.
- Haiku 4.5 still uses the older `thinking: {type: "enabled", budget_tokens: N}`
  form, so it is not a drop in swap for an Opus route.
- Stream anything with a large `max_tokens` or a long input, and use the SDK's
  `get_final_message()` helper.

## 5. Cost control, with the arithmetic

Four levers, in the order they should be applied. The first three cost
nothing in quality.

### Lever 1: prompt caching

The category taxonomy, the condition grading rules, the brand policy block
and the output schema are identical on every listing call. Put them first in
the prompt with a cache breakpoint, and put the photographs and the lot
specific text after it. The cached prefix then reads at $0.20 per million
instead of $4.00.

Caching is prefix matched, in the order `tools`, then `system`, then
`messages`. Any byte change in the prefix invalidates everything after it, so
never put a timestamp, a request ID or an unsorted JSON dump in the cached
part. Verify it is working by checking `usage.cache_read_input_tokens` is not
zero across repeated calls, because a broken cache fails silently and you
only find out on the invoice.

### Lever 2: the Batch API

Half price, for anything nobody is waiting on: manifest extraction, demand
prediction, nightly re scoring, translation, back filling listings. Results
come back in any order, so key them by `custom_id`.

### Lever 3: effort

Effort is the first quality trading lever after caching. Routine routes run
at `low`, analytical ones at `medium`, the weekly prediction job at `high`.
Measure before raising a default, per route, not globally.

### Lever 4: model choice

Only after the first three, and only with an eval showing quality holds.

### Worked example: cost per listing

Structure first, then measure. Do not trust these numbers, measure yours with
`messages.count_tokens` in Phase 2 week 7 and put the real figures in
`docs/ai-features.md`.

```
Illustrative, per listing created from photographs:

cached prefix     2,000 tokens at $0.20/M   = $0.0004
photographs       4 images, call it 6,000 tokens at $4/M = $0.0240
lot specific text   500 tokens at $4/M      = $0.0020
output              600 tokens at $20/M     = $0.0120
                                              ---------
                                              $0.0384 per listing
```

Roughly four cents per listing, dominated by the image tokens. At 1,000 new
lots a month that is about $38. At 10,000 lots a month, about $384, and at
that point the photo route is worth re measuring against a cheaper model.

Three things follow from that arithmetic, and they should be built in Phase 1
rather than discovered in Phase 4:

1. **Image tokens dominate.** Resize and compress before the call. Send three
   or four well chosen photographs, not twelve. Never send a 5MB original.
2. **Cache or pay 20 times over.** The prefix is most of the stable input.
3. **Charge the cost back.** Log cost per listing against the brand. When
   subscriptions arrive in a later phase, you will already know what a brand
   costs you to serve.

### Guardrails in the gateway

- Per brand monthly spend cap, enforced before the call, not after
- Per feature kill switch
- An alert when daily spend exceeds a threshold
- Every call logged with feature, brand, model, tokens in, tokens out, cache
  hit, cost and latency
- A cost dashboard in Phase 4 week 40

## 6. The six capabilities, and the technique each one uses

### Photo to listing

Vision input plus structured outputs. Define the listing schema once in
`schemas/` and pass it as `output_config: {format: {...}}` so the response
validates against it instead of being parsed out of prose. Use
`client.messages.parse()` where the SDK offers it.

Output is always a draft. The brand corrects it. Store both the AI draft and
the corrected version, because the difference between them is your training
data later and your quality metric now.

### Manifest extraction and repair

The hard part is not reading the spreadsheet, it is that the numbers will not
add up. Rule: the extractor proposes, it never silently fixes. Every
reconciliation is a flagged change a human accepts or rejects, and the sum
must match total rule is enforced in the database, not in the prompt.

### Pricing

Rules plus model, and honest about what it cannot do yet. With no sales
history, a suggestion is informed guesswork, so it is presented as a band
with its reasoning rather than as a number with false confidence. It becomes
real in Phase 6, when actual sales give it something to learn from. Anyone
who tells you a model can predict days to sell with no sales data is selling
something.

### Visual and semantic search

This is the one part of the AI layer that is not Claude. Anthropic has no
embeddings endpoint. Use a self hosted open image and text embedding model of
the CLIP or SigLIP class, store the vectors in pgvector alongside the
listings, and keep the model behind the gateway like everything else so it can
be swapped. Budget for the compute, since this is the only AI component with
a fixed hosting cost rather than a per call cost.

### Multilingual assistant

Tool calling, not retrieval of free text. The tools are real functions:
`search_lots`, `get_lot`, `check_availability`, `get_order_status`,
`estimate_delivery`, `create_order_draft`. The system prompt forbids answering
a factual question without a tool call, and the eval tests exactly that, with
cases in Urdu script, Roman Urdu and English.

Note for the Pakistani market: Roman Urdu has no standard spelling, so the
eval set needs the same question written five different ways. This is the part
most teams get wrong, and it is cheap to get right if you collect real phrasings
from day one.

### Risk and quality scoring

Classification on every listing before it reaches the approval queue:
completeness, manifest consistency, photo quality, price plausibility and
counterfeit signals. Output is a score plus reasons, and a score never blocks
anything by itself, it orders the admin queue.

## 7. Evals, and why they come first

Phase 1 week 6 builds the harness, and every feature in Phase 2 has its eval
written before the feature.

| Feature | What the eval measures | Graded by |
| --- | --- | --- |
| Photo to listing | Field by field accuracy against human labelled listings | Exact match on category and attributes, human or model scoring on text |
| Manifest extraction | Line count, totals reconciliation, flagged changes correct | Deterministic comparison |
| Pricing | Suggestion inside the band a human expert accepts | Human rating, then real sales in Phase 6 |
| Assistant | Grounded answer rate, tool call correctness, refusal when data is missing, across three languages | Mixed deterministic and model grading |
| Risk scoring | Precision and recall against a labelled set of good and bad listings | Deterministic |

Two rules. Evals run in CI so a prompt change cannot silently degrade
quality. And every eval run costs money, so the suites are small, fixed, and
versioned rather than regenerated on every commit.

## 8. Prompt injection, because this platform takes text from strangers

Brand descriptions, Excel cell contents, buyer chat messages and photograph
text all reach a model. All of it is untrusted input.

- Untrusted content is passed as data in a clearly delimited block, never
  concatenated into the instruction part of the prompt
- The assistant's tools are read mostly, and the few that write, such as
  creating an order draft, require a confirmed user action afterwards
- No tool can move money, change a price, approve a listing or alter a user
  role
- Model output that will be rendered is escaped, because a model can be made
  to emit a payload
- Spend caps and rate limits per account, so an injection cannot run up a bill

## 9. Training your own models, honestly

The original plan said train your own models in year 2. Here is the real
picture, so the plan does not depend on it:

- Nothing can be trained before Phase 6, because there is no proprietary data
  until real brands list real stock and real buyers buy it
- The first genuinely trainable thing is the pricing and days to sell model,
  and it needs a few thousand completed sales with outcomes, not a few hundred
- The second is a demand model per category and city, which needs seasonality,
  so realistically a year of sales
- Everything before that is better served by a frontier model with a good
  prompt, a strict schema and an eval

What you should do instead, from Phase 2 onward, is collect the data that
would make training possible later: every AI draft, every human correction,
every price suggested against the price achieved, every search and what was
clicked. That corpus is the actual asset, and it costs almost nothing to
accumulate if the schema allows for it from week 2.
