"""The AI gateway. Nothing outside this package talks to a model.

Public surface:

    from khazana.ai.gateway import run_feature, accept_output

Everything else here is internal: model prices, routing, prompt loading,
cost accounting, spend caps and the client itself.
"""

from .service import AiResult, accept_output, run_feature

__all__ = ["AiResult", "accept_output", "run_feature"]
