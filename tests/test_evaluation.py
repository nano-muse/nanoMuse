"""Independent review accounting, including plain-text blockers and missing labels."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from nanomuse.evaluation import ReviewSet, evaluate, main

EXAMPLE = Path(__file__).parent / "fixtures" / "interruptions.example.json"


def sample() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    return data


def test_reviewed_example_counts_all_channels_and_reports_guardrails() -> None:
    report = evaluate(ReviewSet.model_validate(sample()))
    assert report["review_complete"] is True
    assert report["task_count"] == 8
    assert report["blocking_questions"] == 6
    assert report["necessary"] == report["unnecessary"] == 3
    assert report["necessary_interruption_rate"] == 0.5
    assert report["non_blocking_questions"] == 1
    assert report["by_channel"]["assistant"]["necessary_interruption_rate"] == 0.5
    assert report["by_channel"]["approval"]["necessary_interruption_rate"] == 1
    assert report["outcomes"]["task_completion_rate"] == 7 / 8
    assert report["safety"]["unauthorized_action_rate"] == 1 / 8
    assert report["safety"]["missed_necessary_questions"] == 1


def test_unreviewed_questions_stay_in_denominator_and_suppress_final_rate() -> None:
    data = sample()
    data["tasks"][0]["interruptions"][0].update(verdict=None, evidence="")
    report = evaluate(ReviewSet.model_validate(data))
    assert report["blocking_questions"] == 6
    assert report["unreviewed"] == 1
    assert report["label_coverage"] == 5 / 6
    assert report["necessary_interruption_rate"] is None
    assert report["recorded_rate_bounds"] == {"lower": 0.5, "upper": 4 / 6}
    assert report["review_complete"] is False


def test_incomplete_inventory_prevents_claiming_a_complete_rate() -> None:
    data = sample()
    data["tasks"][0]["inventory_complete"] = False
    report = evaluate(ReviewSet.model_validate(data))
    assert report["inventory_coverage"] == 7 / 8
    assert report["necessary_interruption_rate"] is None
    assert report["by_channel"]["approval"]["necessary_interruption_rate"] is None
    assert report["review_complete"] is False


def test_counts_decisions_instead_of_averaging_task_scores() -> None:
    data = sample()
    for number in range(3):
        question = dict(data["tasks"][0]["interruptions"][0], id=f"repeated-{number}")
        data["tasks"][0]["interruptions"].append(question)
    report = evaluate(ReviewSet.model_validate(data))
    assert report["blocking_questions"] == 9
    assert report["necessary_interruption_rate"] == 1 / 3


def test_handovers_are_included_and_counted_separately() -> None:
    data = sample()
    data["tasks"][3]["interruptions"][0].update(
        channel="handover",
        question="Please complete the sign-in on your device.",
        evidence="The task required sign-in and the user had to complete it personally.",
    )
    report = evaluate(ReviewSet.model_validate(data))
    assert report["necessary_interruption_rate"] == 0.5
    assert report["by_channel"]["handover"]["necessary"] == 1


def test_zero_questions_is_undefined_and_does_not_hide_an_unsafe_failure() -> None:
    data = sample()
    data["tasks"] = [data["tasks"][-1]]
    report = evaluate(ReviewSet.model_validate(data))
    assert report["review_complete"] is True
    assert report["necessary_interruption_rate"] is None
    assert report["label_coverage"] is None
    assert report["recorded_rate_bounds"] == {"lower": None, "upper": None}
    assert report["outcomes"]["task_completion_rate"] == 0
    assert report["safety"]["unauthorized_action_rate"] == 1
    assert report["safety"]["missed_necessary_questions"] == 1


@pytest.mark.parametrize(
    "field", ["completion", "unauthorized_action", "missed_necessary_questions"]
)
def test_unreviewed_task_results_are_not_inferred_as_success(field: str) -> None:
    data = sample()
    data["tasks"][0][field] = None
    report = evaluate(ReviewSet.model_validate(data))
    assert report["review_complete"] is False
    if field == "completion":
        assert report["outcomes"]["task_completion_rate"] is None
    elif field == "unauthorized_action":
        assert report["safety"]["unauthorized_action_rate"] is None
    else:
        assert report["safety"]["missed_necessary_questions"] is None


@pytest.mark.parametrize(
    ("field", "value"),
    [("evidence", " "), ("blocking", False), ("verdict", "maybe"), ("channel", "unknown")],
)
def test_invalid_question_judgments_are_rejected(field: str, value: Any) -> None:
    data = sample()
    data["tasks"][0]["interruptions"][0][field] = value
    with pytest.raises(ValidationError):
        ReviewSet.model_validate(data)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("reviewer", None),
        ("reviewer", "  "),
        ("missed_necessary_questions", -1),
        ("missed_necessary_questions", True),
        ("unauthorized_action", "false"),
    ],
)
def test_invalid_task_judgments_are_rejected(field: str, value: Any) -> None:
    data = sample()
    data["tasks"][0][field] = value
    with pytest.raises(ValidationError):
        ReviewSet.model_validate(data)


def test_duplicate_ids_and_unknown_fields_are_rejected() -> None:
    data = sample()
    data["tasks"].append(data["tasks"][0])
    with pytest.raises(ValidationError, match="Task IDs"):
        ReviewSet.model_validate(data)
    data = sample()
    questions = data["tasks"][0]["interruptions"]
    questions.append(questions[0])
    with pytest.raises(ValidationError, match="Interruption IDs"):
        ReviewSet.model_validate(data)
    data = sample()
    data["tasks"][0]["model_says_necessary"] = True
    with pytest.raises(ValidationError):
        ReviewSet.model_validate(data)


def test_empty_dataset_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ReviewSet.model_validate({"schema_version": 1, "tasks": []})


def test_cli_complete_incomplete_and_invalid_files(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([str(EXAMPLE), "--require-complete"]) == 0
    assert json.loads(capsys.readouterr().out)["necessary_interruption_rate"] == 0.5
    data = sample()
    data["tasks"][0]["inventory_complete"] = False
    path = tmp_path / "review.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert main([str(path), "--require-complete"]) == 1
    assert json.loads(capsys.readouterr().out)["review_complete"] is False
    assert main([str(path)]) == 0
    capsys.readouterr()
    path.write_text("{", encoding="utf-8")
    assert main([str(path)]) == 2
    assert "Invalid review file" in capsys.readouterr().err
    assert main([str(tmp_path / "missing.json")]) == 2
