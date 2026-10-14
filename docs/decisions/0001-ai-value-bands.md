# 0001: AI may choose a value only inside a code enforced band

- **Status:** accepted
- **Date:** 2026-10-14
- **Decided by:** the repository owner
- **Affects:** week 42 bargaining bot, week 43 smart markdown agent, and the
  existing pricing feature
- **Supersedes:** nothing. It narrows the rule in `CLAUDE.md` section 4 and
  `docs/ai-architecture.md` section 2.

## Context

The plan expanded on 2026-10-14 and added two features in which AI changes a
price:

- **Week 42, the bargaining bot.** Negotiates with a buyer in Urdu.
- **Week 43, the smart markdown agent.** Lowers the price of unsold lots on a
  schedule, with nobody watching.

Both sit against a standing rule that has been in this repository since week
1: *AI never decides money, approvals, bans or quoted stock levels. It drafts,
suggests, scores and flags.*

That rule is not decoration. It is the reason a brand can be shown this
platform and believe the protection it is promised. A brand that discovers a
model discounted its stock without asking does not file a bug report, it
leaves. So the two features cannot simply be built and the rule quietly
forgotten, and they cannot be dropped either, because both are genuinely
useful: a shop owner in this market expects to negotiate, and stock that has
not moved in four months needs a price change whether or not anyone remembers
to make one.

The question is therefore not whether AI may touch a price. It is what kind of
authority is acceptable.

## Decision

AI may choose a value only inside a band the brand set, and only where the
code enforces that band. Four conditions, all four required:

1. **The floor and the step size are brand policy rows.** Not constants in
   code, not a number in a prompt, and not anything the model is asked to
   respect. This follows the rule already in `CLAUDE.md` section 4 that
   commission rates, discount bands and lot minimums are database
   configuration.

2. **The service clamps every proposal to the band before it is shown or
   applied.** The model never sets a price. It picks within what the clamp has
   already decided is permissible, and a proposal outside the band is not an
   error to report but a value that cannot exist by the time anything acts on
   it.

3. **Every move is written to the append only audit trail.** The same trail
   the approval gate uses, under the same database trigger that blocks UPDATE
   and DELETE. A brand asking why its lot is at this price gets an answer with
   a timestamp.

4. **The agent is off by default.** The brand turns it on per lot and can turn
   it off at any time. Nothing is opted in on a brand's behalf.

Anything outside those four conditions remains forbidden.

## Why this is consistent rather than a loosening

The pricing feature shipped in weeks 10 and 11 already does this. It suggests
a discount band, and `catalog_service._validate_commercials` refuses any lot
price outside the brand's own `min_discount_percent` and
`max_discount_percent`. The model's suggestion has never been able to leave
that band, because the service checks it rather than trusting it.

So the distinction this decision draws is not new, it is one the codebase has
been enforcing without having stated it:

- **Deciding what something is worth** is forbidden. Setting the band, setting
  the floor, approving a listing, choosing who gets credit.
- **Choosing within a band someone else set** is permitted, when code holds
  the boundary.

A clamp in the service is a different kind of guarantee from an instruction in
a prompt. A prompt is a request; a clamp is arithmetic. The eval suite for
pricing has six mandatory cases checking the model stays inside the band, and
those exist precisely because a model that is merely asked will sometimes not.
The clamp is what makes that failure harmless rather than expensive.

## Schema this implies

Recorded now so weeks 42 and 43 are not a design exercise. Not built yet.

On `brand_policies`, extending the rows that already hold
`min_discount_percent` and `max_discount_percent`:

| Column | Purpose |
| --- | --- |
| `allow_bargaining` | Off by default. The brand level switch for the week 42 bot |
| `bargain_floor_percent` | The deepest discount the bot may ever offer. Distinct from `max_discount_percent`, because a brand may accept a deeper price in a negotiation than it advertises |
| `allow_auto_markdown` | Off by default. The brand level switch for the week 43 agent |
| `markdown_step_percent` | How far one scheduled reduction may move the price |
| `markdown_interval_days` | How often the agent may act |
| `markdown_floor_percent` | The deepest discount the agent may reach, after any number of steps |

On `lots`, because condition 4 requires per lot control:

| Column | Purpose |
| --- | --- |
| `bargaining_enabled` | Null means inherit the brand default. A lot the brand does not want negotiated can say so |
| `auto_markdown_enabled` | The same, for markdown |

Three notes on the shape, each of which is a decision in itself:

- The per lot columns are nullable on purpose, so that null means inherit and
  false means refused. The region lock made the opposite choice, where an
  empty per lot list means inherit, and that choice is documented in
  `approval_service.set_region_lock` as a deliberate one. Here an explicit
  refusal has to be distinguishable from silence, because the consequence is a
  price change rather than a visibility rule.
- `bargain_floor_percent` is separate from `max_discount_percent` because the
  two answer different questions. One is what the brand will advertise and the
  other is what it will accept when asked directly, and conflating them would
  either stop the bot being useful or publish the brand's real floor.
- The markdown agent needs both a step and a floor. A floor alone permits one
  jump straight to it, which is not a markdown schedule, it is a sale.

## Consequences

- Weeks 42 and 43 can be built as planned, with the guardrails designed before
  the feature rather than after.
- `CLAUDE.md` section 4 carries the exception and its four conditions, so a
  future session reads the narrowed rule rather than the old absolute one and
  does not have to rediscover this argument.
- Week 50, the test coverage pass, already lists the bargaining floor and the
  markdown floor as money adjacent paths to cover. Week 51, the security pass,
  already lists prompt injection defences on the bargaining bot, which matters
  because a buyer negotiating in free text is untrusted input aimed straight at
  a price.
- The pay after sale credit item stays outside this exception. A trust score
  deciding who gets credit is not choosing inside a band, it is deciding
  whether to lend. A human approves every credit limit and AI only suggests,
  and the State Bank of Pakistan question is settled by a lawyer before any
  code is written.

## Alternatives considered

**Drop both features.** Safest and the plan is poorer for it. Negotiation is
how this market buys, and a markdown schedule nobody has to remember is one of
the few things software does better than a person.

**Require a human to approve every move.** Defensible for bargaining, where a
counter offer could queue for review, and self defeating for markdown, whose
entire value is that it happens without anyone remembering. It also fails on
its own terms: a brand asked to approve forty markdowns a week stops reading
them, and an approval nobody reads is worse than a clamp, because it looks
like oversight.

**Instruct the model in the prompt and trust it.** Rejected. The pricing eval
exists because a model that is merely asked will sometimes not comply, and the
failure here is a real price shown to a real buyer.
