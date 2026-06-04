"""
ARIA-OS: ADK LLM backed by InsForge AI (OpenRouter proxy).

Replaces the Gemini-direct model with InsForge's AI endpoint
(`POST /api/ai/chat/completion`), which proxies OpenRouter (Claude, GPT, etc.)
with the project's configured key — reliable capacity, no Gemini free-tier quota.

This is a thin ADK BaseLlm that translates the ADK LlmRequest (contents, tools,
system instruction) to InsForge's OpenAI-style payload and the response
(`{text, tool_calls}`) back to an ADK LlmResponse — including function calling,
which the agents rely on.
"""
from __future__ import annotations

import json
import os
from typing import Any, AsyncGenerator

import httpx
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from src.infra.logger import log_error


def _system_prompt(llm_request) -> str | None:
    cfg = getattr(llm_request, "config", None)
    si = getattr(cfg, "system_instruction", None) if cfg else None
    if not si:
        return None
    if isinstance(si, str):
        return si
    chunks = [p.text for p in getattr(si, "parts", []) or [] if getattr(p, "text", None)]
    return "\n".join(chunks) or None


def _tools(llm_request) -> list[dict]:
    cfg = getattr(llm_request, "config", None)
    tools = getattr(cfg, "tools", None) if cfg else None
    out: list[dict] = []
    for tool in tools or []:
        for fn in getattr(tool, "function_declarations", None) or []:
            params = fn.parameters
            # google.genai Schema -> plain dict (OpenAI JSON-schema style)
            if hasattr(params, "model_dump"):
                params = params.model_dump(exclude_none=True, by_alias=False)
            out.append(
                {
                    "type": "function",
                    "function": {
                        "name": fn.name,
                        "description": fn.description or "",
                        "parameters": _normalize_schema(params) or {"type": "object", "properties": {}},
                    },
                }
            )
    return out


def _normalize_schema(s: Any) -> Any:
    """Lowercase google.genai 'type' enums (e.g. 'STRING' -> 'string') for JSON-schema."""
    if isinstance(s, dict):
        out = {}
        for k, v in s.items():
            if k == "type" and isinstance(v, str):
                out[k] = v.lower()
            else:
                out[k] = _normalize_schema(v)
        return out
    if isinstance(s, list):
        return [_normalize_schema(x) for x in s]
    return s


def _messages(llm_request) -> list[dict]:
    messages: list[dict] = []
    counter = 0
    emitted_ids: list[str] = []  # tool_call ids emitted so far, in order
    matched: set[str] = set()    # ids already paired with a tool result

    for content in getattr(llm_request, "contents", None) or []:
        role = content.role or "user"
        texts: list[str] = []
        tool_calls: list[dict] = []
        tool_results: list[dict] = []

        for part in content.parts or []:
            if getattr(part, "text", None):
                texts.append(part.text)
            fc = getattr(part, "function_call", None)
            if fc:
                counter += 1
                cid = fc.id or f"call_{counter}"
                emitted_ids.append(cid)
                tool_calls.append(
                    {
                        "id": cid,
                        "type": "function",
                        "function": {
                            "name": fc.name,
                            "arguments": json.dumps(dict(fc.args or {})),
                        },
                    }
                )
            fr = getattr(part, "function_response", None)
            if fr:
                # H3: pair by id when the response carries a valid one; else use the
                # first still-UNMATCHED emitted call (not a blind FIFO pop). Drop an
                # unpairable result rather than mis-pair it — OpenAI-style endpoints
                # 400 on a tool_call_id that doesn't match a preceding tool_calls id.
                rid = fr.id if (fr.id and fr.id in emitted_ids) else None
                if rid is None:
                    rid = next((i for i in emitted_ids if i not in matched), None)
                if rid is None:
                    continue
                matched.add(rid)
                resp = fr.response
                tool_results.append(
                    {
                        "role": "tool",
                        "tool_call_id": rid,
                        "content": json.dumps(resp) if isinstance(resp, (dict, list)) else str(resp),
                    }
                )

        if role == "user":
            if texts:
                messages.append({"role": "user", "content": "\n".join(texts)})
        else:  # model / assistant
            if texts or tool_calls:
                msg: dict = {"role": "assistant", "content": "\n".join(texts)}
                if tool_calls:
                    msg["tool_calls"] = tool_calls
                messages.append(msg)
        # tool results always follow (their preceding assistant tool_calls)
        messages.extend(tool_results)

    return messages


class InsForgeLLM(BaseLlm):
    """ADK model that calls InsForge AI. ``model`` is an OpenRouter id, e.g.
    'openai/gpt-4o-mini' or 'anthropic/claude-sonnet-4.5'."""

    model: str

    async def generate_content_async(
        self, llm_request, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        url = os.environ["INSFORGE_URL"].rstrip("/") + "/api/ai/chat/completion"
        key = os.environ["INSFORGE_API_KEY"]

        payload: dict = {"model": self.model, "messages": _messages(llm_request)}
        system = _system_prompt(llm_request)
        if system:
            payload["systemPrompt"] = system
        tools = _tools(llm_request)
        if tools:
            payload["tools"] = tools
            payload["toolChoice"] = "auto"

        try:
            async with httpx.AsyncClient(timeout=120.0) as http:
                resp = await http.post(
                    url,
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    json=payload,
                )
        except Exception as exc:
            log_error(f"InsForgeLLM transport error: {exc}")
            raise

        if resp.status_code >= 400:
            log_error(f"InsForgeLLM HTTP {resp.status_code}", body=resp.text[:300])
            raise RuntimeError(f"InsForge AI returned {resp.status_code}: {resp.text[:200]}")

        data = resp.json()
        parts: list[types.Part] = []
        text = data.get("text") or ""
        if text:
            parts.append(types.Part(text=text))
        for tc in data.get("tool_calls") or []:
            fn = tc.get("function", {})
            args = fn.get("arguments")
            if isinstance(args, str):
                try:
                    args = json.loads(args or "{}")
                except json.JSONDecodeError:
                    args = {}
            parts.append(
                types.Part(
                    function_call=types.FunctionCall(
                        id=tc.get("id"), name=fn.get("name"), args=args or {}
                    )
                )
            )
        if not parts:
            parts.append(types.Part(text=""))

        yield LlmResponse(
            content=types.Content(role="model", parts=parts), turn_complete=True
        )
