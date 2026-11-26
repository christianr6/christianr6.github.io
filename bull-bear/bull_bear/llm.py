"""Claude as the debater and the judge.

All five calls in a debate share one system prompt: the rules plus the filing.
That prefix is cached, so the filing is paid for in full once and read from
cache by the four calls that follow.
"""

from __future__ import annotations

import os
from typing import TypeVar

import anthropic
from pydantic import BaseModel

from .debate import RULES, documents_block
from .sections import Section

DEFAULT_MODEL = "claude-opus-5-5"
T = TypeVar("T", bound=BaseModel)


class LlmError(RuntimeError):
    """A failure worth showing to the person running the debate."""


class Usage(BaseModel):
    calls: int = 0
    input_tokens: int = 0           # read at full price
    cache_write_tokens: int = 0     # the filing, first call
    cache_read_tokens: int = 0      # the filing, later calls
    output_tokens: int = 0


class ClaudeLlm:
    def __init__(
        self,
        sections: list[Section],
        model: str | None = None,
        effort: str | None = None,
        client: anthropic.Anthropic | None = None,
    ):
        self.model = model or os.environ.get("BULL_BEAR_MODEL", DEFAULT_MODEL)
        self.effort = effort or os.environ.get("BULL_BEAR_EFFORT", "high")
        self.client = client or anthropic.Anthropic()
        self.usage = Usage()
        # Identical for every call, so the cache breakpoint after the filing is reused.
        self.system = [
            {"type": "text", "text": RULES},
            {"type": "text", "text": documents_block(sections), "cache_control": {"type": "ephemeral"}},
        ]

    def ask(self, prompt: str, schema: type[T]) -> T:
        try:
            response = self.client.beta.messages.parse(
                model=self.model,
                max_tokens=16000,
                system=self.system,
                messages=[{"role": "user", "content": prompt}],
                output_config={"effort": self.effort},
                output_format=schema,
                # If a safety classifier declines the request, let the API
                # retry it on Anthropic's recommended fallback model.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except anthropic.AuthenticationError as problem:
            raise LlmError("Claude rejected the API key. Check ANTHROPIC_API_KEY.") from problem
        except anthropic.RateLimitError as problem:
            raise LlmError("Claude's rate limit was hit. Wait a minute and run it again.") from problem
        except anthropic.APIStatusError as problem:
            raise LlmError(f"Claude returned an error ({problem.status_code}): {problem.message}") from problem
        except anthropic.APIConnectionError as problem:
            raise LlmError("Could not reach the Claude API. Check the network connection.") from problem

        usage = response.usage
        self.usage.calls += 1
        self.usage.input_tokens += usage.input_tokens or 0
        self.usage.cache_write_tokens += usage.cache_creation_input_tokens or 0
        self.usage.cache_read_tokens += usage.cache_read_input_tokens or 0
        self.usage.output_tokens += usage.output_tokens or 0

        if response.stop_reason == "refusal":
            raise LlmError("Claude declined this request, and so did the fallback model.")
        if response.stop_reason == "max_tokens":
            raise LlmError("Claude ran out of room before finishing its answer.")
        if response.parsed_output is None:
            raise LlmError("Claude's answer did not match the expected format.")
        return response.parsed_output
