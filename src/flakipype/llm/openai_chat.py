"""The model behind an OpenAI-compatible Chat Completions API, e.g. STACKIT AI Model Serving."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from anthropic.types import Message
from anthropic.types.beta import BetaMessage
from openai import APIError, OpenAI, omit
from openai.types.chat import ChatCompletionFunctionToolParam
from pydantic import BaseModel, ValidationError

from flakipype.llm.chat_format import UnreadableAnswerError, chat_request, message_fields
from flakipype.llm.connection import (
    REQUEST_ERRORS,
    ConnectionFailed,
    ConnectionProblem,
    ConnectionResult,
    ModelError,
    answered_model,
    problem_for_error,
)

# Sent with the connection check, so an endpoint without tool calling fails there.
_PING_TOOL: ChatCompletionFunctionToolParam = {
    "type": "function",
    "function": {
        "name": "ping",
        "description": "Answers a ping.",
        "parameters": {"type": "object", "properties": {}},
    },
}


@dataclass(frozen=True)
class OpenAiChatApi:
    """Messages API requests, answered by Chat Completions; the SDK retries failed requests."""

    sdk: OpenAI

    def message(self, request: Mapping[str, Any]) -> Message:
        return self._answer(request, Message)

    def beta_message(self, request: Mapping[str, Any]) -> BetaMessage:
        return self._answer(request, BetaMessage)

    def check(self, model: str) -> ConnectionResult:
        """Send the smallest request with a tool, to prove URL, key and model work together."""
        try:
            response = self.sdk.chat.completions.create(
                model=model,
                max_completion_tokens=1,
                messages=[{"role": "user", "content": "ping"}],
                tools=[_PING_TOOL],
            )
        except REQUEST_ERRORS as error:
            return ConnectionFailed(problem_for_error(error), error.message)
        return answered_model(response)

    def _answer[Answer: BaseModel](
        self, request: Mapping[str, Any], answer: type[Answer]
    ) -> Answer:
        """One turn, streamed, so the request timeout waits for each part and not the whole."""
        try:
            chat = chat_request(request)
            with self.sdk.chat.completions.create(
                model=chat["model"],
                messages=chat["messages"],
                max_completion_tokens=chat["max_completion_tokens"],
                tools=chat.get("tools", omit),
                stream=True,
                stream_options={"include_usage": True},
            ) as stream:
                fields = message_fields(stream)
            return answer.model_validate(fields)
        except APIError as error:
            raise ModelError(problem_for_error(error), error.message) from error
        except UnreadableAnswerError as error:
            raise ModelError(ConnectionProblem.UNEXPECTED_ANSWER, str(error)) from error
        # The SDK does not validate answers: a sign-in page or another JSON API gets here.
        except (AttributeError, TypeError, ValidationError) as error:
            detail = f"The answer does not read as a Chat Completions stream: {error}"
            raise ModelError(ConnectionProblem.UNEXPECTED_ANSWER, detail) from error
