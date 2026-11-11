#!/usr/bin/env python3
"""Calibrate the decider's difficulty routing against a labelled corpus.

Reads the synthetic benchmark corpus beside this script (or one given
with ``--corpus``), asks the production decider (``build_decider`` and
``difficulty_question``, nothing reimplemented here) to score every
message against the endpoint and model named on the command line, and
reports how the active routing rule would have done: for a threshold,
a message acts (escalates) when the probability mass on the levels
centred at or above the threshold reaches the threshold. Levels 4 and
5 of the corpus count as hard.

The summary gives the trigger rate, the trigger precision (of the
acted messages, how many are labelled hard), the false triggers among
levels 1 and 2, and the recall over the hard messages, plus the acted
count per level. A scan over thresholds from 0.5 to 0.8 names the
smallest one that meets the bar the docs set: precision at least 0.9
and no false trigger at levels 1 and 2. The full per-item
probabilities land in the JSON output, so the scan can be re-derived
without calling a model again.

Nothing here is a test: the calls are real, against the endpoint
given, and cost what the endpoint charges. The corpus is synthetic
and hand-labelled; a calibration on it says how the rule does on the
benchmark, not on real usage, and the configuration page says so.

    python3 scripts/decider_calibration.py \
        --base-url http://127.0.0.1:8911/v1 --api-key placeholder \
        --model inclusionAI/Ling-mini-2.0 --out calibration.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nanomuse.config import Settings  # noqa: E402
from nanomuse.llm.decider import (  # noqa: E402
    DecideRequest,
    ScoreAnswer,
    build_decider,
    difficulty_question,
)

CORPUS = Path(__file__).resolve().parent / "decider_calibration_corpus.json"
HARD_LEVEL = 4  # levels 4 and 5 count as hard
BAR_PRECISION = 0.9


def load_corpus(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data["items"]
    for item in items:
        if not isinstance(item["level"], int) or not 1 <= item["level"] <= 5:
            raise SystemExit(f"corpus item {item.get('id')!r} has no level in 1..5")
        if not str(item["text"]).strip():
            raise SystemExit(f"corpus item {item.get('id')!r} has no text")
    return items


def summarise(rows: list[dict[str, Any]], threshold: float) -> dict[str, Any]:
    """The routing numbers for one threshold, from stored probabilities."""
    acted_rows: list[dict[str, Any]] = []
    for row in rows:
        probabilities = row.get("probabilities")
        if probabilities is None:
            row["acted"] = False
            continue
        answer = ScoreAnswer(score=row["score"], probabilities=probabilities)
        row["p_escalate"] = round(answer.probability_at_or_above(threshold), 4)
        row["acted"] = row["p_escalate"] >= threshold
        if row["acted"]:
            acted_rows.append(row)
    hard = [row for row in rows if row["level"] >= HARD_LEVEL]
    acted_hard = [row for row in acted_rows if row["level"] >= HARD_LEVEL]
    false_easy = [row for row in acted_rows if row["level"] <= 2]
    return {
        "threshold": threshold,
        "items": len(rows),
        "failures": sum(1 for row in rows if row.get("failure")),
        "acted": len(acted_rows),
        "trigger_rate": round(len(acted_rows) / len(rows), 4) if rows else 0.0,
        "precision": round(len(acted_hard) / len(acted_rows), 4) if acted_rows else None,
        "false_triggers_l1_l2": len(false_easy),
        "recall_hard": round(len(acted_hard) / len(hard), 4) if hard else None,
        "acted_by_level": {
            str(level): sum(1 for row in acted_rows if row["level"] == level)
            for level in range(1, 6)
        },
    }


def scan_thresholds(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """The smallest threshold in 0.5..0.8 that meets the bar, if one does."""
    scanned = []
    chosen = None
    for step in range(50, 81, 5):
        threshold = step / 100
        summary = summarise([dict(row) for row in rows], threshold)
        meets = (
            summary["precision"] is not None
            and summary["precision"] >= BAR_PRECISION
            and summary["false_triggers_l1_l2"] == 0
        )
        scanned.append({"threshold": threshold, "meets_bar": meets, **summary})
        if meets and chosen is None:
            chosen = threshold
    return {
        "bar": {"precision_at_least": BAR_PRECISION, "false_triggers_l1_l2": 0},
        "chosen": chosen,
        "scanned": scanned,
    }


async def run(args: argparse.Namespace) -> dict[str, Any]:
    items = load_corpus(args.corpus)
    data_dir = Path(tempfile.mkdtemp(prefix="decider-calibration-"))
    settings = Settings(data_dir=data_dir)
    settings.llm.provider = "openai"
    settings.llm.base_url = args.base_url
    settings.llm = settings.llm.model_copy(update={"api_key": vars(args)["api_key"]})
    settings.llm.model = args.model
    settings.llm.stream = False
    settings.decider.enabled = True
    settings.decider.timeout_seconds = args.timeout
    decider = build_decider(settings)
    rows: list[dict[str, Any]] = []
    for item in items:
        outcome = await decider.decide(
            "calibration",
            DecideRequest(state=item["text"], questions=[difficulty_question()]),
        )
        row: dict[str, Any] = {"id": item["id"], "level": item["level"]}
        answers = outcome.answers or []
        first = answers[0] if answers else None
        if isinstance(first, ScoreAnswer):
            row["score"] = round(first.score, 4)
            row["p_top"] = round(first.p_top, 4)
            row["probabilities"] = [round(p, 4) for p in first.probabilities]
        else:
            row["failure"] = outcome.failure.value if outcome.failure else "unknown"
        row["latency_ms"] = outcome.latency_ms
        rows.append(row)
        print(f"{row['id']} level={row['level']} {row.get('failure') or row.get('score')}")
    summary = summarise(rows, args.threshold)
    return {
        "model": args.model,
        "base_url": args.base_url,
        "timeout_seconds": args.timeout,
        "summary": summary,
        "scan": scan_thresholds(rows),
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--base-url", required=True, help="the endpoint, e.g. http://127.0.0.1:8911/v1"
    )
    parser.add_argument(
        "--api-key", default="", help="the key for the endpoint (a placeholder for a local relay)"
    )
    parser.add_argument("--model", required=True, help="the model that judges the difficulty")
    parser.add_argument(
        "--threshold", type=float, default=0.6, help="the threshold the summary uses (default 0.6)"
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="per-call decider timeout in seconds (default 10)",
    )
    parser.add_argument(
        "--corpus",
        type=Path,
        default=CORPUS,
        help="the corpus JSON (default: the one beside this script)",
    )
    parser.add_argument("--out", type=Path, default=None, help="write the full JSON report here")
    args = parser.parse_args()
    report = asyncio.run(run(args))
    if args.out is not None:
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    summary = report["summary"]
    print()
    print(f"model {report['model']} at {report['base_url']}, timeout {report['timeout_seconds']}s")
    print(
        f"threshold {summary['threshold']}: acted {summary['acted']}/{summary['items']} "
        f"(trigger rate {summary['trigger_rate']}), precision {summary['precision']}, "
        f"false triggers at levels 1-2: {summary['false_triggers_l1_l2']}, "
        f"recall on hard items {summary['recall_hard']}, failures {summary['failures']}"
    )
    print(f"acted by level: {summary['acted_by_level']}")
    chosen = report["scan"]["chosen"]
    if chosen is None:
        print(
            "scan 0.5..0.8: no threshold meets the bar (precision >= 0.9, no level 1-2 false trigger)"
        )
    else:
        print(f"scan 0.5..0.8: smallest threshold meeting the bar is {chosen}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
