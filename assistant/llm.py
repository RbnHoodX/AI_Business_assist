"""Thin Claude wrapper.

Two helpers:
  - structured(): force a single tool call and return its validated input dict.
    Guarantees machine-readable output across SDK versions and is used for
    routing, text-to-SQL, and the final cited answer.
  - The synthesizer can optionally enable adaptive thinking (config.USE_THINKING),
    in which case we cannot force a tool, so we fall back to auto tool choice and
    pick the tool_use block out of the response.
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

import anthropic

from . import config


@lru_cache(maxsize=1)
def _client() -> anthropic.Anthropic:
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        raise RuntimeError(
            "No Anthropic credentials found. Set ANTHROPIC_API_KEY "
            "(see .env.example) before running the assistant."
        )
    return anthropic.Anthropic()


def structured(
    *,
    system: str,
    user: str,
    tool_name: str,
    tool_description: str,
    input_schema: dict[str, Any],
    allow_thinking: bool = False,
    max_tokens: int = 4096,
) -> dict[str, Any]:
    """Call the model and return the JSON input of a single tool call.

    When allow_thinking and config.USE_THINKING are both true, adaptive thinking
    is enabled with tool_choice=auto (forcing a specific tool is not permitted
    alongside thinking). Otherwise the tool is forced for deterministic output.
    """
    tools = [{
        "name": tool_name,
        "description": tool_description,
        "input_schema": input_schema,
    }]

    kwargs: dict[str, Any] = {
        "model": config.MODEL,
        "max_tokens": max_tokens,
        "system": system,
        "tools": tools,
        "messages": [{"role": "user", "content": user}],
    }

    if allow_thinking and config.USE_THINKING:
        kwargs["thinking"] = {"type": "adaptive"}
        kwargs["tool_choice"] = {"type": "auto"}
    else:
        kwargs["tool_choice"] = {"type": "tool", "name": tool_name}

    resp = _client().messages.create(**kwargs)

    for block in resp.content:
        if block.type == "tool_use" and block.name == tool_name:
            return dict(block.input)

    # Model answered with text instead of calling the tool (only possible under
    # auto tool choice). Retry once with the tool forced and thinking off.
    kwargs.pop("thinking", None)
    kwargs["tool_choice"] = {"type": "tool", "name": tool_name}
    resp = _client().messages.create(**kwargs)
    for block in resp.content:
        if block.type == "tool_use" and block.name == tool_name:
            return dict(block.input)

    raise RuntimeError(f"Model did not produce a '{tool_name}' tool call.")
