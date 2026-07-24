"""Scripted stand-ins for the LLM, so no test reaches a real provider.

langchain-core ships FakeListChatModel and GenericFakeChatModel, but neither fits
an agent test on langchain-core 1.5.1: BaseChatModel.bind_tools raises
NotImplementedError on both, and GenericFakeChatModel._stream only re-emits
additional_kwargs, so a scripted tool call silently vanishes on the streaming
path. ScriptedChatModel covers both gaps and adds failure injection.
"""

import json
import re
from collections.abc import Iterator, Sequence
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult


class ScriptedChatModel(BaseChatModel):
    """A chat model that replays a fixed list of AIMessages, for tests."""

    responses: list[AIMessage] = []
    error: BaseException | None = None
    # Recorded so a test can assert which tools were bound without reaching into
    # the graph. Populated by bind_tools.
    bound_tools: list[str] = []
    # Every message list the model was called with, in order. Lets a test assert
    # on what the agent sent (history trimming, system prompt presence) rather
    # than on generated prose.
    calls: list[list[BaseMessage]] = []

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> BaseChatModel:
        """Record the bound tool names and return self, so the script survives binding."""
        self.bound_tools = [
            getattr(t, "name", getattr(t, "__name__", str(t))) for t in tools
        ]
        return self

    def _next(self, messages: list[BaseMessage]) -> AIMessage:
        """Pop the next scripted reply, raising the injected error if one is set."""
        self.calls.append(list(messages))
        if self.error is not None:
            raise self.error
        if not self.responses:
            # A drained script means the agent looped more times than the test
            # expected. Surfacing that beats an opaque StopIteration.
            msg = f"ScriptedChatModel ran out of responses after {len(self.calls)} calls"
            raise AssertionError(msg)
        return self.responses.pop(0)

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self._next(messages))])

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        message = self._next(messages)
        content = message.content if isinstance(message.content, str) else ""
        # Split on whitespace keeping the separators, so rejoining the chunks
        # reproduces the text exactly. If it does not, the SSE contract is broken.
        for token in (part for part in re.split(r"(\s)", content) if part):
            chunk = ChatGenerationChunk(
                message=AIMessageChunk(content=token, id=message.id)
            )
            if run_manager:
                run_manager.on_llm_new_token(token, chunk=chunk)
            yield chunk
        # Tool calls ride in a final zero-content chunk, which is how real
        # providers stream them and what the agent loop has to accumulate.
        if message.tool_calls:
            yield ChatGenerationChunk(
                message=AIMessageChunk(
                    content="",
                    id=message.id,
                    tool_call_chunks=[
                        {
                            "name": call["name"],
                            "args": json.dumps(call["args"]),
                            "id": call["id"],
                            "index": index,
                        }
                        for index, call in enumerate(message.tool_calls)
                    ],
                )
            )


def ai(content: str = "", tool_calls: list[dict] | None = None) -> AIMessage:
    """Build a scripted assistant reply, optionally carrying tool calls."""
    return AIMessage(
        content=content,
        tool_calls=[
            {
                "name": call["name"],
                "args": call.get("args", {}),
                "id": call.get("id", f"call_{index}"),
            }
            for index, call in enumerate(tool_calls or [])
        ],
    )
