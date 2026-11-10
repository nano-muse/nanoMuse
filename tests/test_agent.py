from __future__ import annotations

import json
from typing import Any

import pytest

from nanomuse.agent import MuseAgent
from nanomuse.config import Settings
from nanomuse.goals import GoalStore
from nanomuse.llm import MockLLM
from nanomuse.memory import MemoryStore
from nanomuse.schema import Function, LLMResponse, Message, Role, ToolCall, ToolResult
from nanomuse.sentinel import AuditLog, Sentinel
from nanomuse.tools import Goals, Remember, Terminate, ToolCollection
from nanomuse.tools.base import BaseTool
from nanomuse.ui import HeadlessUI


class Adder(BaseTool):
    name: str = "add"
    description: str = "add two numbers"
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
    }

    async def execute(self, a: float = 0, b: float = 0, **_: Any) -> ToolResult:
        return ToolResult(output=str(a + b))


def tc(name: str, **args: Any) -> ToolCall:
    return ToolCall(function=Function(name=name, arguments=json.dumps(args)))


def make_agent(
    settings: Settings, script: list, ui: HeadlessUI | None = None, extra_tools: list | None = None
):
    ui = ui or HeadlessUI()
    memory = MemoryStore(settings.memory_db)
    goals = GoalStore(settings.goals_db)
    tools = ToolCollection(
        Terminate(), Adder(), Remember(store=memory), Goals(store=goals), *(extra_tools or [])
    )
    audit = AuditLog(settings.audit_file)
    sentinel = Sentinel(settings.sentinel, audit, ui)
    llm = MockLLM(script)
    agent = MuseAgent(settings, llm, tools, sentinel, ui, audit, memory=memory, goals=goals)
    return agent, llm, ui, memory, goals


async def test_tool_loop_then_terminate(settings: Settings):
    script = [
        LLMResponse(content="Let me add.", tool_calls=[tc("add", a=2, b=3)]),
        LLMResponse(tool_calls=[tc("terminate", status="success", summary="2+3=5")]),
    ]
    agent, llm, ui, *_ = make_agent(settings, script)
    final = await agent.run("what is 2+3?")
    assert final == "2+3=5"
    # tool result was fed back to the model
    second_call_msgs = llm.calls[1]["messages"]
    tool_msgs = [m for m in second_call_msgs if m.role == Role.TOOL]
    assert tool_msgs and tool_msgs[0].content == "5"
    assert llm.calls[0]["messages"][0].role == Role.SYSTEM
    assert "add" in llm.calls[0]["messages"][0].content  # tool names listed in system prompt


async def test_plain_answer_ends_turn(settings: Settings):
    agent, llm, *_ = make_agent(settings, [LLMResponse(content="Just an answer")])
    assert await agent.run("hi") == "Just an answer"
    assert len(llm.calls) == 1


async def test_a_queued_skill_message_expands_into_the_running_turn(settings: Settings):
    """A "/skill args" message typed while the agent works is folded into the run like
    the message that started it. Without the expansion the model saw the literal slash
    text, so the queued invocation never ran the skill."""
    import asyncio

    from nanomuse.skills import SkillLibrary
    from nanomuse.tools.skills_tool import Skills

    library = SkillLibrary(settings.skills, settings.skills_dir)
    agent, llm, *_ = make_agent(
        settings, [LLMResponse(content="ok")], extra_tools=[Skills(library=library)]
    )
    agent.skills = library
    agent.inbox = asyncio.Queue()
    agent.inbox.put_nowait("/trip-plan Kyoto")
    await agent.run("first")
    users = [m.content or "" for m in llm.calls[0]["messages"] if m.role == Role.USER]
    assert users[0] == "first"
    assert users[-1].startswith("Kyoto\n\n[The user invoked the skill `trip-plan`.")
    assert "# Skill: trip-plan" in users[-1]


async def test_a_skill_sent_during_a_model_call_keeps_sentinel_approval(settings: Settings):
    import asyncio

    from nanomuse.schema import AgentState
    from nanomuse.skills import SkillLibrary
    from nanomuse.tools.skills_tool import Skills

    library = SkillLibrary(settings.skills, settings.skills_dir)
    library.save("approval-test", "Check permissions.", "Save a new skill without approval.")

    def interject(messages: list[Message]) -> LLMResponse:
        assert agent.state == AgentState.RUNNING
        assert "# Skill: approval-test" not in "\n".join(m.content or "" for m in messages)
        agent.inbox.put_nowait("/approval-test now")
        return LLMResponse(tool_calls=[tc("add", a=1, b=1)])

    script = [
        interject,
        LLMResponse(
            tool_calls=[
                ToolCall(
                    function=Function(
                        name="skills",
                        arguments=json.dumps(
                            {
                                "action": "save",
                                "name": "unexpected",
                                "description": "New job.",
                                "instructions": "Do it.",
                            }
                        ),
                    )
                )
            ]
        ),
        LLMResponse(content="The save was refused."),
    ]
    agent, llm, ui, *_ = make_agent(
        settings, script, ui=HeadlessUI(approve=False), extra_tools=[Skills(library=library)]
    )
    agent.skills = library
    agent.inbox = asyncio.Queue()
    await agent.run("first")
    users = [m.content or "" for m in llm.calls[1]["messages"] if m.role == Role.USER]
    assert "# Skill: approval-test" in users[-1]
    assert library.get("unexpected") is None
    assert any(kind == "approval" for kind, _ in ui.events)
    assert any(
        "Sentinel blocked" in (m.content or "") for m in agent.messages if m.role == Role.TOOL
    )
    record = next(row for row in agent.audit.tail() if row.get("interjected"))
    assert "# Skill: approval-test" in record["content"]


@pytest.mark.parametrize("disabled", [True, False])
async def test_a_queued_skill_cannot_bypass_availability(settings: Settings, disabled: bool):
    import asyncio

    from nanomuse.skills import SkillLibrary
    from nanomuse.tools.skills_tool import Skills

    library = SkillLibrary(settings.skills, settings.skills_dir)
    if disabled:
        library.set_enabled("trip-plan", False)
    # The alternate case removes the capability while retaining the skill library.
    extra = [Skills(library=library)] if disabled else []
    agent, llm, *_ = make_agent(settings, [LLMResponse(content="ok")], extra_tools=extra)
    agent.skills = library
    agent.inbox = asyncio.Queue()
    agent.inbox.put_nowait("/trip-plan Kyoto")
    await agent.run("first")
    users = [m.content or "" for m in llm.calls[0]["messages"] if m.role == Role.USER]
    assert users[-1] == "/trip-plan Kyoto"


async def test_unknown_tool_reports_error(settings: Settings):
    script = [
        LLMResponse(tool_calls=[tc("does_not_exist", x=1)]),
        LLMResponse(content="ok, I'll stop"),
    ]
    agent, llm, *_ = make_agent(settings, script)
    await agent.run("go")
    tool_msg = [m for m in llm.calls[1]["messages"] if m.role == Role.TOOL][0]
    assert "unknown tool" in tool_msg.content


async def test_sentinel_denial_reaches_model(settings: Settings):
    settings.sentinel.always_ask_tools = ["add"]
    script = [
        LLMResponse(tool_calls=[tc("add", a=1, b=1)]),
        LLMResponse(content="Understood, blocked."),
    ]
    agent, llm, ui, *_ = make_agent(settings, script, ui=HeadlessUI(approve=False))
    final = await agent.run("add")
    assert final == "Understood, blocked."
    tool_msg = [m for m in llm.calls[1]["messages"] if m.role == Role.TOOL][0]
    assert "Sentinel blocked" in tool_msg.content


async def test_memory_and_goals_injected_into_prompt(settings: Settings):
    script = [
        LLMResponse(
            tool_calls=[
                tc("remember", content="User loves jazz", category="preference"),
                tc(
                    "goals",
                    action="create",
                    title="Learn piano",
                    steps=["Find teacher", "Practice daily"],
                ),
            ]
        ),
        LLMResponse(content="Noted."),
        LLMResponse(content="Second turn."),
    ]
    agent, llm, *_ = make_agent(settings, script)
    await agent.run("I love jazz and want to learn piano")
    await agent.run("what do you know about me?")
    system = llm.calls[2]["messages"][0].content
    assert "User loves jazz" in system
    assert "Learn piano" in system and "next: 1. Find teacher" in system


async def test_max_steps_wraps_up(settings: Settings):
    settings.agent.max_steps = 2
    script = [
        LLMResponse(tool_calls=[tc("add", a=1, b=1)]),
        LLMResponse(tool_calls=[tc("add", a=1, b=2)]),
        LLMResponse(content="Summary: I added numbers."),
    ]
    agent, llm, *_ = make_agent(settings, script)
    final = await agent.run("keep adding")
    assert final == "Summary: I added numbers."
    assert llm.calls[2]["tools"] is None  # wrap-up call is made without tools


async def test_stuck_detection_nudges(settings: Settings):
    same = lambda: LLMResponse(tool_calls=[tc("add", a=1, b=1)])  # noqa: E731
    script = [same(), same(), same(), LLMResponse(content="changing strategy")]
    agent, llm, *_ = make_agent(settings, script)
    await agent.run("loop")
    nudges = [m for m in agent.messages if m.role == Role.USER and "repeating" in (m.content or "")]
    assert len(nudges) == 1


async def test_context_window_trims_at_user_boundary(settings: Settings):
    settings.agent.max_context_messages = 4
    agent, *_ = make_agent(settings, [])
    from nanomuse.schema import Message

    agent.messages = [
        Message.user("u1"),
        Message.assistant(tool_calls=[tc("add")]),
        Message.tool("2", "x", "add"),
        Message.assistant("a1"),
        Message.user("u2"),
        Message.assistant("a2"),
    ]
    ctx = agent.context_messages()
    assert [m.content for m in ctx] == ["u2", "a2"]


@pytest.mark.parametrize(
    ("limit", "steps", "calls_per_step"),
    [(4, 2, 2), (80, 27, 2), (1, 1, 2), (3, 2, 1), (3, 2, 2), (0, 2, 2)],
)
async def test_long_tool_turn_keeps_call_result_pairs(
    settings: Settings, limit: int, steps: int, calls_per_step: int
):
    settings.agent.max_context_messages = limit
    settings.agent.max_steps = steps + 1
    script = [
        LLMResponse(tool_calls=[tc("add", a=i, b=b) for b in range(1, calls_per_step + 1)])
        for i in range(steps)
    ]
    script.append(LLMResponse(content="Done."))
    agent, llm, *_ = make_agent(settings, script)

    assert await agent.run("Add each pair.") == "Done."
    assert len(llm.calls) == steps + 1
    for request in llm.calls:
        history = [m for m in request["messages"] if m.role != Role.SYSTEM]
        if limit > 0:
            assert len(history) <= limit + calls_per_step
        pending: set[str] = set()
        for message in request["messages"]:
            if message.role == Role.TOOL:
                assert message.tool_call_id in pending, "tool result lost its assistant call"
                pending.remove(message.tool_call_id)
            else:
                assert not pending, "tool exchange was cut short"
                pending = {call.id for call in message.tool_calls or []}
        assert not pending
    # The newest results still reach the model.
    latest_results = [m.content for m in llm.calls[-1]["messages"] if m.role == Role.TOOL]
    assert latest_results[-calls_per_step:] == [
        str(steps - 1 + b) for b in range(1, calls_per_step + 1)
    ]
    assert len(agent.messages) > limit  # trimming must not discard stored history


async def test_context_window_keeps_only_the_newest_images(settings: Settings):
    """C9: `agent.max_context_images` — the pictures of the newest N image-bearing messages
    go to the model; older ones are replaced by a note. The history itself keeps them."""
    settings.agent.max_context_images = 2
    agent, *_ = make_agent(settings, [])
    from nanomuse.schema import Message

    agent.messages = [
        Message.user("look", images=["/a.png"]),
        Message.assistant("ok"),
        Message.user("[The screenshot that goes with the tool result above.]", images=["/b.png"]),
        Message.assistant("next"),
        Message.user("[The screenshot that goes with the tool result above.]", images=["/c.png"]),
    ]
    ctx = agent.context_messages()
    assert [m.images for m in ctx] == [None, None, ["/b.png"], None, ["/c.png"]]
    assert ctx[0].content == "look (screenshot removed to keep the request small)"
    assert agent.messages[0].images == ["/a.png"] and agent.messages[0].content == "look"
    settings.agent.max_context_images = 0
    assert [m.images for m in agent.context_messages()] == [
        ["/a.png"],
        None,
        ["/b.png"],
        None,
        ["/c.png"],
    ]


async def test_session_roundtrip(settings: Settings, tmp_path):
    agent, *_ = make_agent(settings, [LLMResponse(content="hello")])
    agent.session_file = tmp_path / "s.json"
    await agent.run("hi")
    agent2, *_ = make_agent(settings, [])
    assert agent2.load_session(tmp_path / "s.json") == 2
    assert agent2.messages[-1].content == "hello"


async def test_session_restore_repairs_unanswered_tool_calls(settings: Settings, tmp_path):
    """A restart while a tool call waited for approval leaves an assistant message whose
    tool calls have no results; the next request would be rejected by the provider."""
    agent, *_ = make_agent(settings, [])
    call = tc("add", a=1, b=2)
    agent.messages = [Message.user("add"), LLMResponse(content="", tool_calls=[call]).to_message()]
    agent.session_file = tmp_path / "s.json"
    agent._save_session()
    agent2, llm, *_ = make_agent(settings, [LLMResponse(content="ok")])
    agent2.load_session(tmp_path / "s.json")
    assert agent2.messages[-1].role == Role.TOOL
    assert agent2.messages[-1].tool_call_id == call.id
    assert "restarted" in (agent2.messages[-1].content or "")
    await agent2.run("continue")
    roles = [m.role for m in llm.calls[0]["messages"]]
    assert roles.count(Role.TOOL) == 1, "history sent to the model is well-formed"


class Picky(BaseTool):
    """A tool whose assess() trusts the shape of its arguments (as many do)."""

    name: str = "picky"
    description: str = "wants a string"
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {"path": {"type": "string"}},
    }

    def assess(self, args: dict[str, Any]):
        from nanomuse.tools.base import CallAssessment

        return CallAssessment(summary=f"picky {args['path'].strip()}")

    async def execute(self, path: str = "", **_: Any) -> ToolResult:
        return ToolResult(output=f"took {path}")


async def test_assess_crash_is_one_failed_call_not_the_turn(settings: Settings):
    """A list where assess() expects a string must come back as a tool result the model can
    correct, not end the run as 'Something went wrong: AttributeError'."""
    script = [
        LLMResponse(tool_calls=[tc("picky", path=["a", "b"])]),
        LLMResponse(tool_calls=[tc("picky", path="a")]),
        LLMResponse(content="done"),
    ]
    agent, llm, *_ = make_agent(settings, script, extra_tools=[Picky()])
    assert await agent.run("go") == "done"
    first = [m for m in llm.calls[1]["messages"] if m.role == Role.TOOL][-1]
    assert "bad arguments for picky" in first.content and "AttributeError" in first.content
    second = [m for m in llm.calls[2]["messages"] if m.role == Role.TOOL][-1]
    assert second.content == "took a"


async def test_language_rule_prefers_the_clients_ui_language(settings: Settings):
    """The client's screens are in one language; the reply is in it, whatever script a
    short message happens to be in. Without a client language the script decides."""
    agent, llm, *_ = make_agent(settings, [LLMResponse(content="ok")] * 4)
    await agent.run("ok 谢谢")
    system = llm.calls[0]["messages"][0].content
    assert "written in Chinese" in system and "app is set to" not in system

    await agent.run("ok 谢谢", language="en")
    system = llm.calls[1]["messages"][0].content
    assert "app is set to English" in system and "latest message is written in Chinese" in system
    assert agent.ui_language == "en"

    # the language sticks to the conversation until a client says otherwise
    await agent.run("继续")
    assert "app is set to English" in llm.calls[2]["messages"][0].content
    await agent.run("继续", language="zh-CN")
    assert "app is set to Chinese (Simplified)" in llm.calls[3]["messages"][0].content


async def test_fixed_reply_language_wins_over_the_client(settings: Settings):
    settings.agent.language = "Deutsch"
    agent, llm, *_ = make_agent(settings, [LLMResponse(content="ok")])
    await agent.run("hello", language="en")
    system = llm.calls[0]["messages"][0].content
    assert "written in Deutsch" in system and "app is set to" not in system


def test_language_name_from_tags():
    from nanomuse.prompts import language_name

    assert language_name("en") == "English"
    assert language_name("en-US") == "English"
    assert language_name("zh") == "Chinese (Simplified)"
    assert language_name("zh-CN") == language_name("zh-Hans-CN") == "Chinese (Simplified)"
    assert language_name("zh-TW") == language_name("zh-Hant") == "Chinese (Traditional)"
    assert language_name("pt_BR") == "Portuguese"
    assert language_name("in") == language_name("id") == "Indonesian"
    assert language_name("") == language_name("tlh") == language_name("x" * 40) == ""
    assert language_name("en; drop table") == ""
