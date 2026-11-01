"""Recorded task trajectories and an opt-in configured-model run."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from nanomuse.config import load_settings
from nanomuse.llm import create_llm
from nanomuse.llm.mock import MockLLM
from tests.goal_eval_recovery import deny_network
from tests.goal_eval_tasks import (
    DATA,
    FIXTURES,
    World,
    archive_observation,
    make_report,
    meeting_observations,
    observations,
    replay_llm,
    run_case,
    run_cases,
    ticket_observations,
    usage_summary,
    write_recording,
    write_report,
)

RECORDING = json.loads((FIXTURES / "tasks_v1_recording.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", DATA["cases"], ids=lambda c: c["id"])
async def test_replay(case: dict, tmp_path: Path) -> None:
    recording = RECORDING["cases"][case["id"]]
    llm = replay_llm(recording, tmp_path / "workspace")
    with pytest.MonkeyPatch.context() as patcher:
        deny_network(patcher.setattr)
        result = await run_case(case, llm, tmp_path)
    assert len(llm.calls) == len(recording)
    assert not llm.script
    assert result["verdict"] == result["expected_verdict"]
    assert result["criteria"] == result["expected_criteria"]


def test_ticket_exclusions_and_ambiguity() -> None:
    result = ticket_observations(
        "没有符合条件的车次\n- G101 无票\n- G102 超过时间\n- G103 不是二等座"
    )
    assert result == {"TKT-C1": "", "TKT-C2": True}
    assert "TKT-C1" not in ticket_observations("查询结果暂不可用")


def test_meeting_sections() -> None:
    text = "# 目的\n进入试用\n# 遗留\n材料读取失败，无法列出\n# 问题\n1. 回滚？\n2. 谁？\n3. 何时？"
    assert meeting_observations(text, False) == {
        "MEET-C1": True,
        "MEET-C2": False,
        "MEET-C3": False,
        "MEET-C4": True,
        "MEET-C5": 3,
    }
    assert (
        meeting_observations(text.replace("读取失败，无法列出", "读取失败，回滚"), False)["MEET-C4"]
        is False
    )
    assert meeting_observations("# 目的\n试用", False) == {}


def test_archive_line_attribution_and_ambiguity() -> None:
    state = {"invoice-a": True, "invoice-b": False}
    assert archive_observation("invoice-a 成功\ninvoice-b 失败", state) is True
    assert archive_observation("invoice-a 成功 invoice-b\ninvoice-b 失败", state) is True
    assert archive_observation("invoice-a 成功 失败\ninvoice-b 失败", state) is None
    assert archive_observation("invoice-a 成功 invoice-b 失败", state) is None


@pytest.mark.parametrize("case", ["P2", "P6", "P8", "P10"])
async def test_world_faults(case: str, tmp_path: Path) -> None:
    world = World(case, tmp_path)
    if case == "P2":
        result = await world.call({"action": "write", "path": "report.csv", "content": "x"})
        assert result.ok and not (world.workspace / "report.csv").exists()
    elif case == "P6":
        assert not (await world.call({"action": "read", "path": "decisions.md"})).ok
    elif case == "P8":
        result = await world.call(
            {
                "action": "calendar_create",
                "title": "x",
                "start": "2026-10-30T10:00:00+08:00",
                "end": "2026-10-30T10:30:00+08:00",
            }
        )
        assert not result.ok and len(world.snapshot()["events"]) == 1
    else:

        def copy(name: str) -> dict[str, str]:
            return {
                "action": "copy",
                "source": f"收件箱/{name}.pdf",
                "destination": f"发票/{name}.pdf",
            }

        assert (await world.call(copy("invoice-a"))).ok
        assert not (await world.call(copy("invoice-b"))).ok


def test_usage_counts_partial_reports() -> None:
    assert usage_summary(
        [
            {"usage": {"input_tokens": 2}},
            {"usage": {"prompt_tokens": 4, "completion_tokens": 3}},
            {"usage": {}},
        ]
    ) == {"reported_input_tokens": 6, "reported_output_tokens": 3, "calls_without_usage": 2}


@pytest.mark.live
@pytest.mark.skipif(os.environ.get("NANOMUSE_LIVE") != "1", reason="set NANOMUSE_LIVE=1 to run")
async def test_live_tasks(tmp_path: Path) -> None:
    settings = load_settings()
    settings.llm.max_retries = 0
    output = Path(os.environ.get("NANOMUSE_GOAL_EVAL_OUTPUT", str(tmp_path)))
    output.mkdir(parents=True, exist_ok=True)
    results, recordings, workspaces = await run_cases(
        lambda case: create_llm(settings.llm, settings.data_dir), tmp_path
    )
    write_report(
        output / "report.json", make_report("live", settings.llm.model, results, recordings)
    )
    write_recording(output / "recording.json", recordings, workspaces)
    assert not [result for result in results if "error" in result]


def test_ticket_chinese_boundaries_and_normalized_exclusions() -> None:
    result = ticket_observations(
        "- G101次 有票\n- 车次G102 有票\n- G103 余票0\n- G104 余票 0\n- G105 余票：0"
    )
    assert result["TKT-C1"] == "G101,G102"


@pytest.mark.parametrize("failure", ["未成功", "没有成功", "没成功", "未能成功"])
def test_archive_negated_success(failure: str) -> None:
    assert (
        archive_observation(
            f"invoice-a {failure}\ninvoice-b 成功", {"invoice-a": False, "invoice-b": True}
        )
        is True
    )


def test_expense_header_and_total(tmp_path: Path) -> None:
    world = World("P1", tmp_path)
    before = world.snapshot()
    (world.workspace / "report.csv").write_text(
        "类别,金额（元）\n交通,80\n办公,160\n餐饮,60\n总计,300\n", encoding="utf-8"
    )
    result = observations(world, before, "总额300元")
    assert result["EXP-C1"] and result["EXP-C2"]


def test_recording_resolves_symlink_paths(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(real, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symbolic links unavailable: {exc}")
    responses = [
        {
            "content": f"{link}/file {real.resolve()}/file",
            "tool_calls": [],
            "finish_reason": "stop",
            "usage": {},
            "model": "test",
        }
    ]
    dest = tmp_path / "recording.json"
    write_recording(dest, {"P1": responses}, {"P1": link})
    text = dest.read_text(encoding="utf-8")
    assert str(link) not in text and str(real.resolve()) not in text
    recorded = json.loads(text)["cases"]["P1"]
    llm = replay_llm(recorded, link)
    assert llm.script[0].content == f"{real.resolve()}/file {real.resolve()}/file"


async def test_a_failing_case_does_not_stop_the_rest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def run(case: dict, llm: object, path: Path) -> dict:
        if case["id"] == "P2":
            raise RuntimeError("synthetic failure")
        return {"id": case["id"]}

    monkeypatch.setattr("tests.goal_eval_tasks.run_case", run)
    results, recordings, workspaces = await run_cases(lambda case: MockLLM(), tmp_path)
    assert [r["id"] for r in results] == [c["id"] for c in DATA["cases"]]
    assert [r["id"] for r in results if "error" in r] == ["P2"]
    assert results[1]["error"] == "RuntimeError: synthetic failure"
    assert set(recordings) == set(workspaces) == {c["id"] for c in DATA["cases"]}
