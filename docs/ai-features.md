# AI features

What Phase 2 built, what each feature costs, and what each one is allowed to
decide. The design reasoning lives in [ai-architecture.md](ai-architecture.md);
this is the per feature reference.

## The six capabilities

| Feature | Model | Effort | Mode | Endpoint |
| --- | --- | --- | --- | --- |
| Photo to listing | Opus 5.5 | medium | live | `POST /ai/listings/draft` |
| Manifest extraction | Opus 5.5 | low | live | `POST /ai/manifests/extract` |
| Pricing suggestion | Opus 5.5 | medium | live | `POST /ai/lots/{id}/price-suggestion` |
| Semantic and visual search | self hosted embeddings | n/a | n/a | `GET /ai/search` |
| Buyer assistant | Opus 5.5 | low | live | `POST /ai/assistant/ask` |
| Risk scoring | Haiku 4.5 | n/a | live | `POST /ai/lots/{id}/risk-score` |

Every response carries a `cost` object with the dollars spent, the model used
and whether the reply came from a recorded fixture. A feature whose cost is
visible where it is used is a feature nobody is surprised by later.

---

## Photo to listing

**What it does.** Photographs of a lot in, a complete draft listing out:
title, description, category, colours, material, apparent condition,
suggested sizes, tags, a confidence score and a list of what it could not
determine.

**Three guards between the model and the catalogue.** A good model is not the
same as a safe output.

1. A category slug not in the taxonomy falls back to `other` and is flagged.
   The taxonomy is read from the database and supplied in the prompt, but a
   prompt instruction is not a guarantee.
2. A condition grade is never talked up. The model may grade worse than the
   brand claimed, never better. A lot sold as B that arrives as C loses that
   buyer permanently; the reverse costs nothing.
3. A draft below 0.6 confidence is routed to a person before it can be
   submitted.

**Cost control.** Image tokens dominate this call, so nothing reaches the
model without passing through `ai/images.py`: the long edge is capped at 1024
pixels, the image is recompressed, at most four photographs are sent, and
duplicate views are collapsed. The bytes saved are returned in the response so
the saving is measured rather than assumed.

**What it never touches.** Piece counts, prices and the manifest. Those are
the brand's to state.

---

## Manifest extraction

**What it does.** A brand CSV in, manifest lines out, with every proposed
change listed.

**The governing rule.** The extractor proposes, a human disposes. When the
rows do not sum to the total the file states, the difference is reported and
the lines come back exactly as read. Nothing is adjusted to make the
arithmetic work. A manifest that was quietly corrected is worse than one that
openly does not add up, because the first gets shipped and the second gets
checked.

**Computed, not asked of a model.** The sum, the comparison against the
declared total, and the merging of duplicate size and colour pairs. That last
one also protects the unique constraint in the database, which would otherwise
reject the insert with a far worse message.

**Encoding.** UTF-8 first, then cp1256 for older Windows exports. The fallback
is reported rather than silent: cp1256 maps almost every byte, so a UTF-16 or
Windows-1252 file would decode into plausible nonsense rather than failing.
Using the fallback at all forces review.

**Not supported yet.** Excel binaries. The error says to save as CSV, which is
a deliberate scope choice: most brands can export CSV and a binary parser is a
separate decision with its own attack surface.

---

## Pricing suggestion

**What it does.** Suggests a discount band and an expected days to sell range,
with the reasoning shown.

**Honest about its limits.** With fewer than three comparable sales the
suggestion is marked `based_on_rules_only`, which is set in code as well as
asked of the model, because the interface label depends on it. A confident
price with no evidence behind it is the failure that costs a brand money and
then costs you the brand.

**Computed, not asked of a model.** The comparable set is a query over lots
with a completed order, because a lot marked sold with no order proves nothing
and a model asked to recall comparables would invent them. The clamp to the
brand's discount band is enforced in code, because the band is a commercial
decision the brand already made.

**The model never sees a rupee figure.** It returns a percentage band and the
system computes the money.

---

## Semantic and visual search

**Not Claude.** Anthropic has no embeddings endpoint, so vectors come from a
self hosted model of the SigLIP or CLIP class, reached over HTTP. It is the
only AI component with a fixed hosting cost rather than a per call cost.

**The default provider is a stub, and says so.** Without
`EMBEDDING_SERVICE_URL` the platform uses a deterministic hashing provider. It
matches shared character trigrams, it is not semantic, and for images it finds
the identical file and nothing else. It exists so the whole storage and search
path works now and a real model is a configuration change. Anything that calls
its output semantic similarity is wrong.

**Two filters live inside the SQL, not after it.** Draft, unapproved and soft
deleted lots can never reach a buyer, and private lots stay out of general
search. Filtering afterwards would shrink a page of results and would leak an
unapproved listing the day a caller forgot.

**The brand name is excluded from the indexed text.** An unbranded listing
that became findable by brand name through search would have its protection
quietly defeated.

**Requires PostgreSQL.** On SQLite the vector column stores and retrieves but
cannot be searched, so the endpoint explains that rather than returning an
empty list that looks like a genuine miss.

---

## Buyer assistant

**What it does.** Answers a shopkeeper in English, Urdu or Roman Urdu using
only facts read from the database in that turn.

**Shape of a turn.** Plan, execute, answer. One structured call picks the
tools, code runs them, a second structured call writes the reply from the
results and nothing else. Two calls rather than a native tool use loop, so
both steps use the gateway unchanged, each is independently evaluable, and the
cost of a turn is bounded. The trade is no reacting to a tool result within
the same turn, which a follow up question covers. Native tool use is the Phase
4 upgrade.

**The guarantee lives in the tools.** Six of them, all real queries:
`search_lots`, `get_lot`, `check_availability`, `get_order_status`,
`estimate_delivery`, `create_order_draft`.

- Every tool applies visibility itself, so a draft, private or deleted lot can
  never be handed to the model.
- An unbranded lot returns the generic label, never the real brand name. The
  assistant cannot leak what it was never given.
- The buyer identity is injected from the session and never taken from the
  model output, so a guessed order code reveals nothing.
- `create_order_draft` writes nothing and reserves nothing. An assistant that
  could place a binding order is one that can be talked into placing one.

**What actually ran overrides what the model claims ran.** Otherwise a model
could assert a lookup it never made and the grounding check would believe it.

---

## Risk scoring

**What it does.** Scores a draft listing for how much human attention it
needs, and orders the admin review queue. It never approves or rejects
anything.

**Division of labour.** Measured facts are computed and are not negotiable:
the manifest sum, the implied discount, the photograph count, the defect
count, and whether the claimed grade matches the defects. The model is asked
only for judgement: counterfeit signals, description quality, whether the
wording and the grade hang together.

**Two one directional rules.** The final score is the higher of the computed
and judged scores, so a well written description cannot talk a structurally
broken listing down the queue. And `manifest_consistent` always comes from the
computation, because a model asserting that a manifest balances when it does
not is the one error that would let a bad lot through on its say so.

---

## Evals

Twelve suites, 95 cases, 46 of them mandatory. A mandatory case is a rule
rather than a quality target, and a failure in one fails the whole run
regardless of the pass rate. The table is generated from the suites, so the
counts are exact for this commit.

| Suite | Feature | Cases | Mandatory |
| --- | --- | --- | --- |
| `assistant_brand` | assistant_brand | 6 | 4 |
| `assistant_buyer` | assistant_buyer | 6 | 4 |
| `assistant_plan` | assistant_buyer | 8 | 2 |
| `bargaining` | bargaining | 5 | 3 |
| `brand_plan` | assistant_brand | 7 | 1 |
| `listing_from_photos` | listing_from_photos | 4 | 2 |
| `logo_detection` | logo_detection | 14 | 10 |
| `manifest_extract` | manifest_extract | 15 | 5 |
| `markdown` | markdown | 4 | 2 |
| `pricing` | pricing | 15 | 6 |
| `resell_kit` | resell_kit | 6 | 4 |
| `risk_scoring` | risk_scoring | 5 | 3 |

A test, `tests/test_eval_coverage.py`, fails if a feature calls a model with no
suite, and `tests/test_prompt_contract.py` checks every case renders with no
placeholder left and every schema sent is one the API accepts. The Phase 4
features and which of them deliberately use no model are described in
`docs/ai-architecture.md` section 6b.

```bash
.\scripts\dev.ps1 evals                     # offline, free, what CI runs
python -m khazana.ai.evals.run --live       # measures the model, spends money
python -m khazana.ai.evals.run --live --record   # re record the fixtures
```

**What an offline run proves, and what it does not.** It exercises the
gateway, the schema validation and the graders. It does not measure the model,
because the reply is recorded rather than generated. That is what is wanted in
CI, where a prompt change must not silently break the pipeline and must not
cost money. Measuring the model is the deliberate `--live` act.

**The graders were verified by breaking something.** A fixture was deliberately
edited to answer confidently with no lookup behind it, and the suite failed
with the reason `stated a fact with no lookup behind it: '300 rupees'` and a
non zero exit. A suite that has never failed is a suite nobody should trust.

---

## Cost, measured where it is spent

Every call records tokens, cache reads, cost, latency, model and prompt
version in `ai_outputs`, and adds to `ai_spend`. Caps are checked before a call
is made, never after.

| Guard | Where |
| --- | --- |
| Per feature kill switch | `AI_DISABLE_<FEATURE>` environment variable |
| Platform daily cap | `AI_DAILY_SPEND_LIMIT_USD` |
| Per brand monthly cap | `brand_policies.ai_monthly_budget_usd` |

At the cap means stop, not one more call. Using a strict greater than would
let every budget overshoot by one request, which on a bulk upload is hundreds
of requests.

A blocked job keeps its row with the reason, so throttling is visible rather
than looking like the feature quietly did nothing.

## Week 53: the cost and quality pass

Every eval suite was run live on 2026-11-24, then again where a change needed
measuring. Total spend for the whole pass, every rerun included: **USD 1.03**,
against a cap of USD 10, enforced by setting the gateway's own daily cap to
USD 9.50 for the run.

### Results

All 12 suites, 95 cases, passed every mandatory case on the first live run.
Two optional cases failed, both on routes that had been moved to Haiku 5.5,
and that decided the model for those routes:

| Route | Model tried | Runs | Result |
| --- | --- | --- | --- |
| Markdown agent | Haiku 5.5, low and medium effort | 3 each | Cut 3% from a lot that was selling, every run |
| Markdown agent | Haiku 5.5, high effort | 3 | Ran out of tokens thinking; a mandatory case failed |
| Markdown agent | Haiku 4.5 | 3 | Every case passed, every run |
| Risk scoring | Haiku 5.5, low and medium effort | 3 each | Scored a contradicted grade claim 35, below the 40 floor, every run |
| Risk scoring | Haiku 4.5 | 3 | Every case passed, every run |
| Resell kit | Haiku 5.5, low effort | 1 | Every case passed |

So the markdown agent and risk scoring stay on Haiku 4.5, and the resell kit
moves to Haiku 5.5 at a tenth of the price. The router says why beside each
route, so the next person to change it sees the evidence first.

### Prompt caching, measured

| Route | Fresh input tokens | Read from cache | Notes |
| --- | --- | --- | --- |
| Buyer assistant | 2,599 | 26,812 | Opus 5.5 |
| Brand assistant | 2,376 | 18,807 | Opus 5.5 |
| Manifest extraction | 1,401 | 23,730 | Opus 5.5 |
| Pricing | 3,925 | 24,794 | Opus 5.5 |
| Resell kit | 1,323 | 7,430 | Haiku 5.5 |
| Logo detection, before | 39,413 | 0 | caching was off on this route |
| Logo detection, after | 15,655 | 22,061 | 36% cheaper, every case still passes |
| Risk scoring, markdown | all | 0 | Haiku 4.5: prompts are under its 4,096 token minimum |

Haiku 4.5 needs a cached prefix of 4,096 tokens; Opus 5.5, Sonnet 5.5 and
Haiku 5.5 need 512. The two Haiku 4.5 routes are cheap enough that this costs
little, but it is why a move to Haiku 5.5 will be worth re-testing when the
eval allows it.

### What else changed

- **Refusal fallback.** Opus 5.5 requests carry the server side fallback to
  Opus 4.8, so a safety classifier declining an ordinary request is answered
  inside the same call instead of failing. The reply is priced at the model
  that served it.
- **Response cache.** Listing drafts, logo detection, manifest extraction,
  pricing and risk scoring answer an identical request from the stored reply
  for 24 hours, at no cost. The key includes the brand and the image bytes.
  Evals bypass it, because an eval measures the model.
- **Batch.** The daily markdown agent goes through the Message Batches API at
  half price, submitted once a day and collected every half hour. It is the
  only model job nobody waits for: forecasting and the daily risk job never
  call the model, and model risk scoring runs when an admin asks for it.
- **A snapshot name broke pricing.** Haiku 4.5 reports itself as
  `claude-haiku-4-5-20251001`. The new served model tracking priced replies
  by that name, which is not in the catalogue, so every Haiku 4.5 reply failed
  after it had been paid for. Found by the live run, fixed, and tested.
- **The SDK is pinned to 2.x**, which the images and CI had already installed
  while the laptop ran 1.x.


## Still to measure

Stated so they are not mistaken for settled facts.

- **Tokens per photograph.** The cost model uses a placeholder of 1,500. Measure
  it with the token counting endpoint against real brand photographs and put
  the real figure here.
- **Cache hit rate in production.** Measured in the week 53 live run below:
  every Opus 5.5 and Haiku 5.5 route caches, Haiku 4.5 routes do not. In
  production the client logs a warning when a cached route returns no cache
  tokens; that warning needs a dashboard, which is part of the monitoring in
  `docs/deployment.md`.
- **Haiku 4.5 cache read pricing.** Not published in the source used to build
  the catalogue, so `cost.py` charges cache reads at the full input rate for
  that model. Over reporting is recoverable; under reporting is a surprise.
