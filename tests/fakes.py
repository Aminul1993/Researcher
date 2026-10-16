"""Offline stand-ins for the Ollama chat models used by the workflow."""

import threading
from collections.abc import Sequence
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import PrivateAttr

DEFAULT_TEAM = [
    {"name": "Coder", "role_prompt": "Write code.", "skill": "coding"},
    {"name": "Reviewer", "role_prompt": "Review code.", "skill": "review"},
]

# The kinds of call the workflow makes, as recorded by ScriptedChatModel.
TEAM_CALL = "TeamSchema"
ROUTER_CALL = "RouterSchema"
CHAT_CALL = "chat"


def _usage(input_chars: int, output_chars: int) -> dict:
    # Roughly four characters per token, like most tokenizers.
    input_tokens, output_tokens = input_chars // 4, output_chars // 4
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
    }


class ScriptedChatModel(BaseChatModel):
    """Offline stand-in for ChatOllama that answers team and routing calls.

    Attributes:
        team: Agents the team designer proposes. ``None`` makes the designer
            reply in prose instead of calling the tool.
        routes: The supervisor's choices, in order. The last one repeats
            once the list is used up, so ``["Coder"]`` never finishes.
        prose_routing: Reply to routing calls in prose instead of calling
            the routing tool.
        reply: The text of every agent and finalizer reply.
        error: Raised on every call when set.
    """

    team: list[Any] | None = DEFAULT_TEAM
    routes: list[str] = ["FINISH"]
    prose_routing: bool = False
    reply: str = "done"
    model: str = "scripted-model"
    error: Any = None

    _calls: list[tuple[str, int]] = PrivateAttr(default_factory=list)
    _lock: threading.Lock = PrivateAttr(default_factory=threading.Lock)

    @property
    def _llm_type(self) -> str:
        return "scripted"

    @property
    def calls(self) -> list[tuple[str, int]]:
        """Every call so far, as (kind, input characters)."""
        return list(self._calls)

    def count(self, kind: str) -> int:
        return sum(1 for call, _ in self._calls if call == kind)

    def input_chars(self, kind: str) -> int:
        return sum(chars for call, chars in self._calls if call == kind)

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        name = convert_to_openai_tool(tools[0])["function"]["name"]
        return self.bind(tool_name=name)

    def _next_route(self) -> str:
        routed = self.count(ROUTER_CALL) - 1
        return self.routes[min(routed, len(self.routes) - 1)]

    def _generate(
        self,
        messages: Sequence[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        tool_name: str | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        input_chars = sum(len(str(message.content)) for message in messages)
        with self._lock:
            self._calls.append((tool_name or CHAT_CALL, input_chars))
            route = self._next_route() if tool_name == ROUTER_CALL else ""
        if self.error is not None:
            raise self.error

        metadata = {"model_name": self.model}
        if tool_name == TEAM_CALL and self.team is not None:
            args: dict = {"agents": self.team}
        elif tool_name == ROUTER_CALL and not self.prose_routing:
            args = {"next_agent": route, "reasoning": f"{route} is next."}
        else:
            if tool_name == ROUTER_CALL:
                text = f"The next agent should be {route}."
            elif tool_name == TEAM_CALL:
                text = "I would build a team of experts."
            else:
                text = self.reply
            message = AIMessage(
                content=text,
                response_metadata=metadata,
                usage_metadata=_usage(input_chars, len(text)),
            )
            return ChatResult(generations=[ChatGeneration(message=message)])

        call = {"name": tool_name, "args": args, "id": "call-1"}
        message = AIMessage(
            content="",
            tool_calls=[call],
            response_metadata=metadata,
            usage_metadata=_usage(input_chars, len(str(args))),
        )
        return ChatResult(generations=[ChatGeneration(message=message)])
