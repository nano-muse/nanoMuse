"""Control tools: finish the task / ask the human."""

from __future__ import annotations

from typing import Any

from nanomuse.schema import RiskLevel, ToolResult
from nanomuse.tools.base import BaseTool
from nanomuse.ui import UI

UNANSWERED_QUESTION_ERROR = (
    "The user did not answer. Do not ask again this turn. Complete safe independent work, "
    "then state what remains blocked. Silence does not supply missing facts or authorization."
)


class Terminate(BaseTool):
    name: str = "terminate"
    description: str = (
        "Finish the current task. Call this when the request is fully handled (status=success) "
        "or when you cannot make progress (status=failure). Put your final answer / summary for "
        "the user in `summary`."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["success", "failure"]},
            "summary": {"type": "string", "description": "Final message for the user."},
        },
        "required": ["status", "summary"],
    }
    risk: RiskLevel = RiskLevel.SAFE

    async def execute(self, status: str = "success", summary: str = "", **_: Any) -> ToolResult:
        return ToolResult(output=summary or f"Task finished with status: {status}", stop=True)


class AskUser(BaseTool):
    name: str = "ask_user"
    description: str = (
        "Ask a necessary blocking question and wait for the answer. First use information "
        "already supplied and authorized tools, and complete independent preparation. Ask only "
        "for a material decision or information only the user can provide. Bundle independent "
        "essential questions into one call. For optional preferences, deliver a reversible "
        "draft with stated assumptions instead. Do not ask whether to start or continue work "
        "already requested. Never guess credentials, recipients, payment details or exact "
        "dates needed for a booking or reminder."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {"question": {"type": "string"}},
        "required": ["question"],
    }
    risk: RiskLevel = RiskLevel.SAFE
    ui: Any = None  # UI protocol instance

    async def execute(self, question: str = "", **_: Any) -> ToolResult:
        if not isinstance(question, str) or not question.strip():
            return ToolResult.fail("A non-empty question is required")
        if self.ui is None:
            return ToolResult.fail("no UI available to ask the user")
        ui: UI = self.ui
        answer = await ui.ask_user(question)
        if answer is None or not str(answer).strip():
            return ToolResult.fail(UNANSWERED_QUESTION_ERROR)
        return ToolResult(output=f"User answered: {answer}")


__all__ = ["AskUser", "Terminate", "UNANSWERED_QUESTION_ERROR"]
