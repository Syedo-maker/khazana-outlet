"""Task to model routing.

This is the table from docs/ai-architecture.md section 4, expressed as code.
Changing which model serves a feature is a change here and nowhere else.

Routing rules worth knowing before editing:

- Opus 5.5 is the default. Cheaper models appear only where the work is high
  volume and low judgement, and each one is a decision the owner made after
  an eval, not an automatic cost saving.
- Effort is the first cost lever after caching. Routine routes run at low.
- Anything nobody is waiting for runs in batch mode at half price.
"""

from __future__ import annotations

from dataclasses import dataclass

from ...models.enums import AiFeature, AiMode
from .models import HAIKU_4_5, OPUS_5_5, spec_for


@dataclass(frozen=True, slots=True)
class Route:
    feature: AiFeature
    model_id: str
    effort: str | None
    mode: AiMode
    # Whether the stable prefix of this prompt should be cached. Worth it
    # whenever the prefix is large and identical across calls, which is the
    # case for anything carrying the category taxonomy or the grading rules.
    cache_prefix: bool
    # Guard rail, not a model limit: the largest response this task should
    # ever need. A runaway generation is a cost incident.
    max_tokens: int
    requires_vision: bool = False

    def __post_init__(self) -> None:
        spec = spec_for(self.model_id)
        if self.requires_vision and not spec.supports_vision:
            raise ValueError(f"{self.model_id} cannot serve vision task {self.feature}")


ROUTES: dict[AiFeature, Route] = {
    # The highest value feature in the platform. Listing quality decides
    # whether a brand trusts it, so this route does not economise.
    AiFeature.LISTING_FROM_PHOTOS: Route(
        feature=AiFeature.LISTING_FROM_PHOTOS,
        model_id=OPUS_5_5,
        effort="medium",
        mode=AiMode.LIVE,
        cache_prefix=True,
        max_tokens=2_000,
        requires_vision=True,
    ),
    # Nobody waits for a spreadsheet to be cleaned, so it goes in a batch.
    AiFeature.MANIFEST_EXTRACT: Route(
        feature=AiFeature.MANIFEST_EXTRACT,
        model_id=OPUS_5_5,
        effort="low",
        mode=AiMode.BATCH,
        cache_prefix=True,
        max_tokens=8_000,
    ),
    AiFeature.PRICING: Route(
        feature=AiFeature.PRICING,
        model_id=OPUS_5_5,
        effort="medium",
        mode=AiMode.LIVE,
        cache_prefix=True,
        max_tokens=1_200,
    ),
    # High volume classification on every listing: the cheapest place in the
    # system to use a small model, and the eval covers it.
    AiFeature.RISK_SCORING: Route(
        feature=AiFeature.RISK_SCORING,
        model_id=HAIKU_4_5,
        effort=None,
        mode=AiMode.LIVE,
        cache_prefix=True,
        max_tokens=800,
    ),
    AiFeature.ASSISTANT_BUYER: Route(
        feature=AiFeature.ASSISTANT_BUYER,
        model_id=OPUS_5_5,
        effort="low",
        mode=AiMode.LIVE,
        cache_prefix=True,
        max_tokens=1_500,
    ),
    AiFeature.ASSISTANT_BRAND: Route(
        feature=AiFeature.ASSISTANT_BRAND,
        model_id=OPUS_5_5,
        effort="medium",
        mode=AiMode.LIVE,
        cache_prefix=True,
        max_tokens=2_000,
    ),
    AiFeature.DEMAND_FORECAST: Route(
        feature=AiFeature.DEMAND_FORECAST,
        model_id=OPUS_5_5,
        effort="high",
        mode=AiMode.BATCH,
        cache_prefix=False,
        max_tokens=8_000,
    ),
    AiFeature.TRANSLATION: Route(
        feature=AiFeature.TRANSLATION,
        model_id=HAIKU_4_5,
        effort=None,
        mode=AiMode.BATCH,
        cache_prefix=False,
        max_tokens=2_000,
    ),
    # Embeddings are produced by a self hosted open model, not by the Claude
    # API, which has no embeddings endpoint. The route exists so the feature
    # still flows through the gateway for cost and kill switch purposes.
    AiFeature.EMBEDDING: Route(
        feature=AiFeature.EMBEDDING,
        model_id=HAIKU_4_5,  # placeholder, see embedding feature module
        effort=None,
        mode=AiMode.BATCH,
        cache_prefix=False,
        max_tokens=1,
    ),
}


def route_for(feature: AiFeature) -> Route:
    try:
        return ROUTES[feature]
    except KeyError as exc:
        raise ValueError(
            f"No route configured for {feature}. Add one to ROUTES so the "
            "feature has a model, an effort level and a cost owner."
        ) from exc
