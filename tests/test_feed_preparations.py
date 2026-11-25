from __future__ import annotations

from typing import Any

import pytest

from nanomuse.server.preparations import Source, prepare


@pytest.mark.parametrize(
    "mistake",
    [
        "unknown",
        "invented",
        "one record",
        "same kind",
        "same quote",
        "stale",
        "resolved",
        "no reason",
        "bad form",
    ],
)
def test_grounding_refuses_invalid_or_outdated_evidence(mistake: str) -> None:
    anchor = Source("goal", "a", "Review the Atlas budget", True)
    support = Source("memory", "b", "Atlas reviews should name the decision owner", False)
    offered = {"S1": anchor, "S2": support}
    current = dict(offered)
    item: dict[str, Any] = {
        "form": "brief",
        "why_now": "Before the budget review",
        "anchor": "S1",
        "sources": [{"id": "S1", "quote": "Atlas"}, {"id": "S2", "quote": "decision owner"}],
    }
    assert prepare(item, offered, current) is not None
    if mistake == "unknown":
        item["sources"][1]["id"] = "S99"
    elif mistake == "invented":
        item["sources"][1]["quote"] = "Book a flight"
    elif mistake == "one record":
        item["sources"] = item["sources"][:1]
    elif mistake == "same kind":
        offered["S2"] = current["S2"] = Source("goal", "b", support.text, False)
    elif mistake == "same quote":
        item["sources"][1]["quote"] = "Atlas"
    elif mistake == "stale":
        current["S2"] = Source("memory", "b", "The decision was already made", False)
    elif mistake == "resolved":
        current.pop("S1")
    elif mistake == "no reason":
        item["why_now"] = ""
    else:
        item["form"] = "send_mail"
    assert prepare(item, offered, current) is None


def test_selected_pair_quotes_come_from_the_host_and_unknown_numbers_are_refused() -> None:
    offered = {
        "S1": Source("goal", "g", "Contact the museum before the group visit", True),
        "S2": Source("memory", "m", "The museum entrance needs to be step-free.", False),
    }
    item = {
        "pair": "P1",
        "form": "draft",
        "title": "Museum inquiry",
        "why_now": "Before your group visit",
        "body": "Which museum entrance has step-free access?",
    }
    result = prepare(item, offered, offered)
    assert result and [s["quote"] for s in result["sources"]] == [s.text for s in offered.values()]
    assert prepare({**item, "body": "We are bringing 30 guests."}, offered, offered) is None
    assert prepare({**item, "pair": "P99"}, offered, offered) is None


def test_direct_draft_must_deliver_actual_words_and_can_abstain() -> None:
    from nanomuse.server.preparations import from_draft

    anchor = Source("conversation", "c", "Draft an inquiry for the museum", True)
    draft = "Which entrance should our group use for step-free access?"
    assert from_draft('{"draft":"' + draft + '"}', "P1", anchor)["body"] == draft
    assert from_draft("[quiet]", "P1", anchor) is None
    assert from_draft("[填空]我计划先写一段开场白，然后发给参会的同事", "P1", anchor) is None
    assert from_draft('{"draft":12}', "P1", anchor) is None
