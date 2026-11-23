from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest

from nanomuse.server.waiting import waiting_for

# Tuesday night UTC is Wednesday morning for this user.
LOCAL = timezone(timedelta(hours=8))
NOW = datetime(2026, 11, 25, 10, tzinfo=LOCAL)


def line(text: str, ident: str = "a", days: int = 0, **fields: Any) -> dict[str, Any]:
    stamp = (NOW - timedelta(hours=3) + timedelta(days=days)).astimezone(UTC).isoformat()
    return {"id": ident, "type": "user", "text": text, "ts": stamp, **fields}


@pytest.mark.parametrize(
    ("text", "day", "subject"),
    [
        ("我在等供应商明天发来星桥报价。", 1, "星桥报价"),
        ("I'm waiting for the supplier to send the Atlas quote by Friday.", 2, "the Atlas quote"),
        ("我在等星桥的报价，下周一给。", 5, "星桥的报价"),
        ("我在等供应商周五发报价。", 2, "报价"),
        ("我在等实验室周五给我报告。", 2, "报告"),
        ("我在等星桥的发票，周五给。", 2, "星桥的发票"),
        ("I am waiting for the approval by 2026-11-30.", 5, "the approval"),
        ("我在等星桥的回复，后天给。", 2, "星桥的回复"),
        ("I'm waiting for the Atlas quote by next Friday.", 9, "the Atlas quote"),
        ("I'm waiting for the Atlas quote by Friday next week.", 9, "the Atlas quote"),
        ("I'm waiting for the Atlas quote by next week on Friday.", 9, "the Atlas quote"),
    ],
)
def test_waits_resolve_the_date_from_the_persons_original_turn(text: str, day: int, subject: str):
    (wait,), used = waiting_for([line(text)], NOW + timedelta(days=2))
    assert (wait.due, wait.subject) == (NOW.date() + timedelta(days=day), subject)
    assert used == {"a"}


@pytest.mark.parametrize(
    "event",
    [
        line("I'm waiting for the train tomorrow."),
        line("I'm waiting for the report from last Friday."),
        line("我在等供应商上周五发的报价。"),
        line("I'm waiting for feedback tomorrow or Friday."),
        line("I'm waiting for the quote. Tomorrow is a holiday."),
        line("I'm waiting for feedback from Nia. Tomorrow is a holiday."),
        line("我在等报价，如果周五给就好。"),
        line("我在等供应商今天发来报价。", via_device="test"),
        line("我在等供应商今天发来报价。", source="schedule"),
        line("我在等供应商今天发来报价。", to_device="another"),
        line("我在等供应商今天发来报价。", files=[{}]),
        line("我在等供应商今天发来报价。", synced=True),
        line("我在等供应商今天十十点发来报价。"),
        line("我在等供应商今天25:95发来报价。"),
        line("I'm waiting for the quote today at 9am or 2pm."),
    ],
)
def test_wait_requires_a_real_local_expectation(event):
    assert waiting_for([event], NOW) == ([], set())


def test_correction_then_receipt_and_independent_same_named_matters():
    first = line("我在等供应商今天发来星桥报价。")
    moved = line("改到周五。", "b")
    (original,), _ = waiting_for([first], NOW)
    (later,), _ = waiting_for([first, moved], NOW)
    assert later.due == NOW.date() + timedelta(days=2) and later.key != original.key
    assert later.correction == moved["text"]
    assert waiting_for([first, moved, line("收到了", "c")], NOW)[0] == []

    two = [first, line("我在等供应商今天发来河湾报价。", "d")]
    assert len(waiting_for([*two, line("收到了", "c")], NOW)[0]) == 2
    (remaining,), _ = waiting_for([*two, line("星桥的报价收到了。", "c")], NOW)
    assert remaining.subject == "河湾报价"


def test_ignores_ambiguous_confirmations_and_respects_repeated_updates():
    first = line("I'm waiting for the Atlas quote by today.")
    repeat = line(first["text"], "b")
    (original,), _ = waiting_for([first], NOW)
    (same,), _ = waiting_for([first, repeat], NOW)
    assert original.key == same.key
    assert waiting_for([first, line("I haven't received the Atlas quote.", "b")], NOW)[0] == [
        original
    ]
    assert waiting_for([first, line("How is the garden?", "b"), line("Got it.", "c")], NOW)[0] == [
        original
    ]
    assert waiting_for([first, line("I received the Atlas quote.", "b")], NOW)[0] == []
    assert waiting_for([first, line("Got it.", "b", days=3)], NOW + timedelta(days=3))[0] == [
        original
    ]


def test_an_acknowledgement_of_the_assistants_draft_and_another_document_are_not_receipts():
    opened = line("I'm waiting for the Atlas quote by today.")
    answer = line("Here is a draft for the Atlas team.", "b", type="assistant")
    (original,), _ = waiting_for([opened], NOW)
    for update in [line("Got it.", "c"), line("I received the Atlas invoice.", "c")]:
        assert waiting_for([opened, answer, update], NOW)[0] == [original]
    assert waiting_for([opened, answer, line("Received the Atlas quote.", "c")], NOW)[0] == []


@pytest.mark.parametrize(
    ("original", "hour", "minute"),
    [
        ("我在等供应商今天下午三点半发来星桥报价。", 15, 30),
        ("我在等今天下午十二点发来的星桥报价。", 12, 0),
        ("我在等供应商今天17:15发来星桥报价。", 17, 15),
        ("I'm waiting for the Atlas quote by today at 5 p.m.", 17, 0),
        ("I'm waiting for the Atlas quote by today at 5:15 PM.", 17, 15),
        ("I'm waiting for the Atlas quote by today at 17:15.", 17, 15),
    ],
)
def test_waits_until_the_agreed_local_time(original, hour, minute):
    (item,), _ = waiting_for([line(original)], NOW)
    agreed = NOW.replace(hour=hour, minute=minute, second=0)
    assert not item.ready(agreed - timedelta(seconds=1))
    assert item.ready(agreed)
    assert item.card()["time"] == agreed.strftime("%H:%M")


def test_changing_just_the_hour_on_the_same_day_retires_the_old_wait():
    first = line("我在等供应商今天下午三点发来星桥报价。")
    (before,), _ = waiting_for([first], NOW)
    (after,), _ = waiting_for([first, line("改到今天下午五点。", "b")], NOW)
    assert before.key != after.key and after.card()["time"] == "17:00"
    assert not after.ready(NOW.replace(hour=16))


def test_adjacent_reschedule_after_an_assistant_reply():
    first = line("我在等供应商今天发来星桥报价。")
    reply = line("记下了。", "b", type="assistant")
    (later,), _ = waiting_for([first, reply, line("改到周五。", "c")], NOW)
    assert later.due == NOW.date() + timedelta(days=2)
    assert later.quote == first["text"]


@pytest.mark.parametrize(
    ("original", "other", "same"),
    [
        (
            "I'm waiting for the Atlas report by today.",
            "I received the Fjord report.",
            "I received the Atlas report.",
        ),
        ("我在等供应商今天发来星桥报价。", "海湾报价收到了。", "星桥报价收到了。"),
    ],
)
def test_another_item_of_the_same_type_cannot_close_the_wait(original, other, same):
    initial = line(original)
    (waiting,), _ = waiting_for([initial], NOW)
    assert waiting_for([initial, line(other, "b")], NOW)[0] == [waiting]
    assert waiting_for([initial, line(same, "b")], NOW)[0] == []


def test_a_quote_from_a_different_person_remains_outstanding():
    first = line("I'm waiting for Morgan to send the quote by Friday.")
    second = line("I'm waiting for Alex to send the quote by Friday.", "b")
    (remaining,), _ = waiting_for(
        [first, second, line("I received the quote from Alex.", "c")], NOW
    )
    assert remaining.quote == first["text"]


def test_a_wait_agreed_three_weeks_ahead_still_appears_in_its_grace_period():
    due = NOW.date() - timedelta(days=3)
    opening = line(f"I'm waiting for the Atlas quote by {due.isoformat()}.", days=-24)
    (item,), _ = waiting_for([opening], NOW)
    assert item.due == due and item.ready(NOW)
    assert not item.ready(NOW + timedelta(days=1))


def test_answer_to_a_tool_question_does_not_close_an_earlier_followup():
    first = line("I'm waiting for the Atlas report by today.")
    (waiting,), _ = waiting_for([first], NOW)
    nudge = line(
        "Did the report arrive?",
        "b",
        type="assistant",
        source="chat_followup",
        waiting_id=waiting.key,
    )
    assert not waiting_for([first, nudge, line("Yes", "c")], NOW)[0]
    tool = line("Continue working?", "d", type="question")
    assert waiting_for([first, nudge, tool, line("Yes", "e")], NOW)[0] == [waiting]
