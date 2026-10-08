"""Eval runner.

    python -m khazana.ai.evals.run --offline          # what CI runs, free
    python -m khazana.ai.evals.run --live             # costs real money
    python -m khazana.ai.evals.run --live --record    # also saves fixtures
    python -m khazana.ai.evals.run --suite listing_from_photos

Offline is the default. A test suite that silently spends money is a test
suite people switch off.

Exit codes: 0 if every suite passed, 1 otherwise, so CI can gate on it.
"""

from __future__ import annotations

import argparse
import importlib
import os
import pkgutil
import sys
from decimal import Decimal

from sqlalchemy.orm import Session

from ...db import build_engine
from ...models import Base
from ..gateway import run_feature
from .base import CaseOutcome, EvalSuite

SUITES_PACKAGE = "khazana.ai.evals.suites"


def discover_suites(only: str | None = None) -> list[EvalSuite]:
    """Find every module in ``suites`` exporting a ``SUITE``.

    Discovery rather than a registry list, so adding a suite file is the only
    step needed to have it run in CI.
    """
    package = importlib.import_module(SUITES_PACKAGE)
    found: list[EvalSuite] = []
    for info in pkgutil.iter_modules(package.__path__):
        if only and info.name != only:
            continue
        module = importlib.import_module(f"{SUITES_PACKAGE}.{info.name}")
        suite = getattr(module, "SUITE", None)
        if isinstance(suite, EvalSuite):
            found.append(suite)
    return found


def run_suite(db: Session, suite: EvalSuite, *, record: bool) -> list[CaseOutcome]:
    outcomes: list[CaseOutcome] = []

    for case in suite.cases:
        # Placeholder images. The eval exercises the prompt, the schema and the
        # graders; it is not a vision benchmark. Real photographs belong in a
        # labelled set added in Phase 2 week 7.
        images = [b"eval-placeholder-image"] * case.images

        try:
            result = run_feature(
                db,
                suite.feature,
                prompt_name=suite.prompt_name,
                prompt_values=case.prompt_values,
                images=images,
                record_fixture=record,
            )
        except Exception as exc:
            outcomes.append(
                CaseOutcome(case=case, passed=False, error=f"{type(exc).__name__}: {exc}")
            )
            continue

        output = result.output.model_dump(mode="json")
        reasons: list[str] = []
        passed = True
        for grader in case.graders:
            grade = grader(output)
            if not grade.passed:
                passed = False
                reasons.append(grade.reason)

        outcomes.append(
            CaseOutcome(
                case=case,
                passed=passed,
                reasons=reasons,
                cost_usd=float(result.cost_usd),
            )
        )

    return outcomes


def report(suite: EvalSuite, outcomes: list[CaseOutcome]) -> bool:
    """Print one suite's result and return whether it passed."""
    mandatory = [o for o in outcomes if o.case.must_pass]
    optional = [o for o in outcomes if not o.case.must_pass]

    mandatory_failures = [o for o in mandatory if not o.passed]
    optional_passed = sum(1 for o in optional if o.passed)
    rate = optional_passed / len(optional) if optional else 1.0
    total_cost = sum(Decimal(str(o.cost_usd)) for o in outcomes)

    suite_passed = not mandatory_failures and rate >= suite.pass_threshold

    print(f"\n{suite.feature.value}  prompt={suite.prompt_name}")
    print("-" * 72)
    for outcome in outcomes:
        mark = "pass" if outcome.passed else "FAIL"
        tag = " [must pass]" if outcome.case.must_pass else ""
        print(f"  {mark:4}  {outcome.case.name}{tag}")
        if outcome.error:
            print(f"        error: {outcome.error}")
        for reason in outcome.reasons:
            print(f"        {reason}")

    print(
        f"  mandatory: {len(mandatory) - len(mandatory_failures)}/{len(mandatory)} passed, "
        f"other: {optional_passed}/{len(optional)} "
        f"({rate:.0%}, threshold {suite.pass_threshold:.0%}), "
        f"cost ${total_cost}"
    )
    print(f"  suite: {'PASS' if suite_passed else 'FAIL'}")
    return suite_passed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Khazana AI eval suites")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--offline", action="store_true", help="use recorded fixtures, free")
    mode.add_argument("--live", action="store_true", help="call the real API, costs money")
    parser.add_argument("--record", action="store_true", help="save fixtures, implies live")
    parser.add_argument("--suite", help="run only this suite module name")
    args = parser.parse_args(argv)

    live = args.live or args.record
    os.environ["AI_OFFLINE"] = "false" if live else "true"
    # The settings object is cached, so the environment has to be set before
    # anything imports it. Clearing the cache keeps this runner honest when
    # called in process from a test.
    from ...config import get_settings

    get_settings.cache_clear()

    if live:
        print("Running against the live API. This spends real money.")

    # The runner needs somewhere to write job and cost rows. A throwaway
    # SQLite file keeps eval runs out of the development database.
    engine = build_engine("sqlite:///./.eval-runs.db")
    Base.metadata.create_all(engine)

    suites = discover_suites(args.suite)
    if not suites:
        print("No eval suites found.", file=sys.stderr)
        return 1

    all_passed = True
    with Session(engine) as db:
        for suite in suites:
            outcomes = run_suite(db, suite, record=args.record)
            if not report(suite, outcomes):
                all_passed = False

    print("\n" + ("All suites passed." if all_passed else "One or more suites FAILED."))
    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
