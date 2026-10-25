"""Async Responses API adapter, shared by specialist and independent judge."""
import json
import os
import time
import uuid

import httpx
import failproofai_sdk as fp


class ModelError(Exception):
    """A provider failure whose message contains no credentials or provider body."""


async def respond(instructions, content, *, model=None, schema=None, role="specialist"):
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        raise ModelError("OPENAI_API_KEY is missing. Add it to .env and restart.")
    model = model or os.environ.get("OPENAI_MODEL", "gpt-4.1-mini")
    rid, started = uuid.uuid4().hex, time.monotonic()
    # This lab uses synthetic data. Response text is recorded to support Cloud audits/evaluation.
    fp.event.model_request(model=model, request_id=rid, model_role=role)
    payload = {"model": model, "instructions": instructions, "input": json.dumps(content), "store": False, "max_output_tokens": 1600}
    if schema:
        payload["text"] = {"format": {"type": "json_schema", "name": "drift_evaluation", "strict": True, "schema": schema}}
    try:
        async with httpx.AsyncClient(timeout=65) as client:
            response = await client.post("https://api.openai.com/v1/responses", headers={"Authorization": f"Bearer {key}"}, json=payload)
        if response.status_code != 200:
            raise ModelError(f"OpenAI HTTP {response.status_code}. Check credentials, model access and quota.")
        data = response.json()
        if data.get("status") != "completed":
            raise ModelError("OpenAI response was incomplete; no valid score is available.")
        answer = "".join(part["text"] for item in data.get("output", []) for part in item.get("content", []) if part.get("type") == "output_text")
        if not answer.strip():
            raise ModelError("OpenAI returned no output text, possibly a provider refusal.")
        usage = data.get("usage", {})
        fp.event.model_response(model=model, request_id=rid, model_role=role, content=answer,
                                input_tokens=usage.get("input_tokens", 0), output_tokens=usage.get("output_tokens", 0),
                                duration_ms=round((time.monotonic()-started)*1000), stop_reason="completed")
        return answer
    except BaseException as exc:
        fp.event.model_response(model=model, request_id=rid, model_role=role,
                                duration_ms=round((time.monotonic()-started)*1000), error=type(exc).__name__)
        if isinstance(exc, (httpx.HTTPError, ValueError)):
            raise ModelError("OpenAI request failed or returned invalid JSON; no valid score is available.") from None
        raise
