"""Run the fixed GUI cases and write an inspectable JSON report."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from nanomuse.config import Settings, load_settings
from nanomuse.evaluation.gui import load_cases, run_case, summarize
from nanomuse.llm.factory import create_llm


async def run(args: argparse.Namespace) -> int:
    settings = load_settings(args.config) if args.live else Settings()
    # Offline fixtures must not inherit real credentials, files or devices.
    cases = load_cases(args.cases)
    if args.case:
        cases = [case for case in cases if case.id == args.case]
        if not cases:
            raise ValueError(f"unknown case {args.case}")
    args.output.mkdir(parents=True, exist_ok=True)
    work = args.output / datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    work.mkdir()
    results = []
    for case in cases:
        llm = create_llm(settings.llm, data_dir=settings.data_dir) if args.live else None
        try:
            results.append(await run_case(case, settings, work / case.id, llm))
        finally:
            if llm is not None:
                await llm.close()
        print(f"{case.id}: {'PASS' if results[-1]['passed'] else 'FAIL'}")
    report = summarize(results, mode="live" if args.live else "reference")
    report["model"] = settings.llm.model if args.live else "MockLLM"
    report["case_file"] = str(args.cases.resolve())
    report["case_sha256"] = hashlib.sha256(args.cases.read_bytes()).hexdigest()
    path = work / "report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{report['passed']}/{report['cases']} passed; report: {path}")
    return 0 if report["passed"] == report["cases"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cases",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "tests/fixtures/gui_regression/cases.v1.json",
    )
    parser.add_argument("--output", type=Path, default=Path(".gui-regression"))
    parser.add_argument("--case", help="run one case id")
    parser.add_argument(
        "--live", action="store_true", help="use the configured model; makes paid model calls"
    )
    parser.add_argument("--config", type=Path)
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
