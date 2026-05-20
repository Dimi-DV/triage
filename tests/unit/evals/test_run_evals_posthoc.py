"""Unit tests for the post-hoc evaluator gating in evals.run_evals.

The MAST classifier is a post-hoc evaluator: it fires only when at least
one *gating* evaluator (the scoring custom judges, currently
`diagnosis_matches_ground_truth-*` and `asks_before_destructive_action-*`)
returns a numeric score of 0. These tests pin that contract without
touching AgentCore.
"""

from __future__ import annotations

from typing import Any

import pytest
from evals.run_evals import (
    _any_gating_failure,
    _is_gating,
    _run_posthoc_evaluators,
)


@pytest.mark.unit
def test_is_gating_excludes_builtins() -> None:
    assert _is_gating("Builtin.Correctness") is False
    assert _is_gating("Builtin.TrajectoryInOrderMatch") is False


@pytest.mark.unit
def test_is_gating_includes_scoring_custom_judges() -> None:
    assert _is_gating("diagnosis_matches_ground_truth-K6N4S4FyUs") is True
    assert _is_gating("asks_before_destructive_action-gg2q6dArgF") is True


@pytest.mark.unit
def test_is_gating_excludes_mast_classifier() -> None:
    """MAST is a categorical post-hoc classifier; never gates."""
    assert _is_gating("mast_classification-N5x5TC8avR") is False


@pytest.mark.unit
def test_any_gating_failure_true_when_diagnosis_judge_zero() -> None:
    verdicts = [
        {"evaluator_id": "Builtin.Correctness", "score": 0.0},
        {"evaluator_id": "diagnosis_matches_ground_truth-K6N4S4FyUs", "score": 0.0},
        {"evaluator_id": "asks_before_destructive_action-gg2q6dArgF", "score": 1.0},
    ]
    assert _any_gating_failure(verdicts) is True


@pytest.mark.unit
def test_any_gating_failure_false_when_both_judges_pass() -> None:
    verdicts = [
        {"evaluator_id": "Builtin.Correctness", "score": 1.0},
        {"evaluator_id": "Builtin.TrajectoryInOrderMatch", "score": 0.0},  # built-in 0 doesn't gate
        {"evaluator_id": "diagnosis_matches_ground_truth-K6N4S4FyUs", "score": 2.0},
        {"evaluator_id": "asks_before_destructive_action-gg2q6dArgF", "score": 1.0},
    ]
    assert _any_gating_failure(verdicts) is False


@pytest.mark.unit
def test_any_gating_failure_ignores_errored_judge() -> None:
    """A gating judge that errored doesn't count as a failure — we can't
    classify against MAST if we don't know whether the run actually
    failed against the assertions."""
    verdicts = [
        {
            "evaluator_id": "diagnosis_matches_ground_truth-K6N4S4FyUs",
            "error": "ServiceError",
            "error_message": "transient",
        },
        {"evaluator_id": "asks_before_destructive_action-gg2q6dArgF", "score": 1.0},
    ]
    assert _any_gating_failure(verdicts) is False


@pytest.mark.unit
def test_any_gating_failure_ignores_partial_score() -> None:
    """Score 1.0 on the 3-point diagnosis judge is Partial, not NoMatch.
    The post-hoc gate fires only on score==0."""
    verdicts = [
        {"evaluator_id": "diagnosis_matches_ground_truth-K6N4S4FyUs", "score": 1.0},
        {"evaluator_id": "asks_before_destructive_action-gg2q6dArgF", "score": 1.0},
    ]
    assert _any_gating_failure(verdicts) is False


@pytest.mark.unit
def test_run_posthoc_skips_on_passing_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """No post-hoc evaluator should fire when all gating judges pass."""
    called: list[str] = []

    def fake_call(*args: Any, **kwargs: Any) -> dict[str, Any]:
        called.append(args[1])  # evaluator_id positional
        return {"evaluator_id": args[1], "level": args[2], "score": None}

    monkeypatch.setattr("evals.run_evals._call_evaluate", fake_call)

    verdicts_passing = [
        {"evaluator_id": "diagnosis_matches_ground_truth-K6N4S4FyUs", "score": 2.0},
        {"evaluator_id": "asks_before_destructive_action-gg2q6dArgF", "score": 1.0},
    ]
    new = _run_posthoc_evaluators(
        client=None,
        verdicts=verdicts_passing,
        spans=[],
        scenario={"name": "test", "reference_answer": "x"},
        session_id="sess",
        trace_id="trace",
    )
    assert new == []
    assert called == []


@pytest.mark.unit
def test_run_posthoc_fires_on_failing_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the diagnosis judge scores 0, MAST should fire and the
    verdict gets a posthoc=True marker."""
    called: list[str] = []

    def fake_call(
        client: Any,
        evaluator_id: str,
        level: str,
        spans: Any,
        scenario: Any,
        session_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        called.append(evaluator_id)
        return {
            "evaluator_id": evaluator_id,
            "level": level,
            "score": None,
            "label": "FM-3.3",
            "rationale": "Agent didn't verify",
        }

    monkeypatch.setattr("evals.run_evals._call_evaluate", fake_call)

    verdicts_failing = [
        {"evaluator_id": "diagnosis_matches_ground_truth-K6N4S4FyUs", "score": 0.0},
        {"evaluator_id": "asks_before_destructive_action-gg2q6dArgF", "score": 1.0},
    ]
    new = _run_posthoc_evaluators(
        client=None,
        verdicts=verdicts_failing,
        spans=[],
        scenario={"name": "test", "reference_answer": "x"},
        session_id="sess",
        trace_id="trace",
    )
    assert len(new) == 1
    assert new[0]["evaluator_id"].startswith("mast_classification")
    assert new[0]["label"] == "FM-3.3"
    assert new[0]["posthoc"] is True
    assert called == [new[0]["evaluator_id"]]
