# Architecture decision records

Decisions that shape the platform and would be expensive to reverse, each
with its context, what was decided and what it costs. A new one gets the next
number and a status; a reversed one is marked superseded, never deleted.

| Number | Decision | Status |
| --- | --- | --- |
| [0001](0001-ai-value-bands.md) | AI may choose a value only inside a code enforced band | accepted |
| [0002](0002-one-ai-gateway-offline-by-default.md) | Every model call goes through one gateway, offline by default | accepted |
| [0003](0003-postgresql-for-everything.md) | PostgreSQL for data, search and vectors, one datastore | accepted |
| [0004](0004-money-held-until-the-buyer-confirms.md) | Money in whole rupees, held until the buyer confirms | accepted |
| [0005](0005-api-on-the-web-origin.md) | In production, the API is served under the web app's origin | accepted |
| [0006](0006-ai-cost-model-choice-by-eval.md) | A cheaper model only where a live eval says so | accepted |
| [0007](0007-direct-settlement-for-the-pilot.md) | In the pilot, the buyer pays the brand directly and the platform invoices commission | accepted |
