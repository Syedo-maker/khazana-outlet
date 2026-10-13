# AI features

What Phase 2 built, what each feature costs, and what each one is allowed to
decide. The design reasoning lives in [ai-architecture.md](ai-architecture.md);
this is the per feature reference.

## The six capabilities

| Feature | Model | Effort | Mode | Endpoint |
| --- | --- | --- | --- | --- |
| Photo to listing | Opus 5.5 | medium | live | `POST /ai/listings/draft` |
| Manifest extraction | Opus 5.5 | low | batch | `POST /ai/manifests/extract` |
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

Three suites, fifteen cases, nine of them mandatory. A mandatory case is a
rule rather than a quality target, and a failure in one fails the whole run
regardless of the pass rate.

| Suite | Cases | Mandatory rules |
| --- | --- | --- |
| `listing_from_photos` | 4 | Never grade up when defects are visible; brand supplied text is data, not instructions |
| `assistant_buyer` | 6 | Roman Urdu is not answered in Urdu script; no lookup means no facts; another buyer's order is refused; an injected discount and order confirmation is ignored |
| `risk_scoring` | 5 | A clean listing scores low; a mismatched manifest is reported; instructions inside listing text are a finding, not a command |

```bash
make evals                                  # offline, free, what CI runs
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

## Still to measure

Stated so they are not mistaken for settled facts.

- **Tokens per photograph.** The cost model uses a placeholder of 1,500. Measure
  it with the token counting endpoint against real brand photographs and put
  the real figure here.
- **Cache hit rate in production.** A silently broken prompt cache produces no
  error and a twenty times larger bill. The client logs a warning when a
  cached route returns no cache tokens; that warning needs a dashboard.
- **Haiku 4.5 cache read pricing.** Not published in the source used to build
  the catalogue, so `cost.py` charges cache reads at the full input rate for
  that model. Over reporting is recoverable; under reporting is a surprise.
