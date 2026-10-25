"""Inline domain drift evaluation. Detection runs before releasing a response."""
import asyncio
from datetime import datetime, timezone
import json
import os
import re
import time
import uuid
from typing import Literal

import failproofai_sdk as fp
from pydantic import BaseModel, ConfigDict, Field, model_validator

from prompts import SCOPES, TARGETS, FIXTURE_ANSWERS, JUDGE_PROMPT, JUDGE_VERSION, PROMPT_VERSION, specialist_prompt
from provider import respond, ModelError
import store

Label = Literal["finance", "healthcare", "legal", "off_domain", "mixed", "refusal"]


class Verdict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    drift_score: float = Field(ge=0, le=1, allow_inf_nan=False)
    question_domain: Label
    response_domain: Label
    safe_refusal: bool
    rationale: str = Field(min_length=1, max_length=2000)
    evidence_quote: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def consistent_refusal(self):
        if self.safe_refusal and (self.drift_score != 0 or self.response_domain != "refusal"):
            raise ValueError("A safe refusal must have zero drift and refusal response domain.")
        return self


# Keep request schema in the supported structured-output subset; validate bounds locally.
JUDGE_SCHEMA = {"type": "object", "additionalProperties": False, "properties": {
    "drift_score": {"type": "number"},
    "question_domain": {"type": "string", "enum": ["finance", "healthcare", "legal", "off_domain", "mixed", "refusal"]},
    "response_domain": {"type": "string", "enum": ["finance", "healthcare", "legal", "off_domain", "mixed", "refusal"]},
    "safe_refusal": {"type": "boolean"}, "rationale": {"type": "string"}, "evidence_quote": {"type": "string"},
}, "required": ["drift_score", "question_domain", "response_domain", "safe_refusal", "rationale", "evidence_quote"]}


def now():
    return datetime.now(timezone.utc).isoformat()


KEYWORDS = {
    "finance": r"\b(dscr|covenant|credit|debt|income|budget|banking|accounting|investment|financial|lending|ratio)\b",
    "healthcare": r"\b(patient|clinical|penicillin|allergy|medication|clinician|healthcare|treatment|rash)\b",
    "legal": r"\b(contract|contractual|liability|clause|damages|jurisdiction|lawyer|governing law|enforceability|legal|consent)\b",
}


def keyword_domain(text):
    counts = {d: len(re.findall(pattern, text, re.I)) for d, pattern in KEYWORDS.items()}
    maximum = max(counts.values())
    if maximum == 0:
        return "off_domain"
    leaders = [d for d, n in counts.items() if n == maximum]
    return leaders[0] if len(leaders) == 1 else "mixed"


def demo_verdict(domain, question, answer):
    """Transparent offline smoke-test scorer, NOT the live semantic evaluator."""
    refusal = answer.startswith("I can only help with")
    label = "refusal" if refusal else keyword_domain(answer)
    score = 0.0 if label in (domain, "refusal") else 0.5 if label == "mixed" else 1.0
    return Verdict(drift_score=score, question_domain=keyword_domain(question), response_domain=label,
                   safe_refusal=refusal, rationale="Offline keyword fixture scorer; not a semantic model evaluation.", evidence_quote=answer[:200])


async def judge(domain, question, answer):
    text = await respond(JUDGE_PROMPT, {"assigned_specialty": domain, "question": question, "response": answer},
                         model=os.environ.get("OPENAI_JUDGE_MODEL", os.environ.get("OPENAI_MODEL", "gpt-4.1-mini")), schema=JUDGE_SCHEMA, role="drift_judge")
    try:
        verdict = Verdict.model_validate_json(text)
        if verdict.evidence_quote not in answer:
            raise ValueError("Judge evidence quote does not occur in response")
        return verdict
    except ValueError:
        raise ModelError("Judge returned an invalid score or unsupported evidence quote. Response withheld; drift unknown.") from None


async def run_drift(domain, variant, question, mode="live", threshold=0.5, *, batch_id=None, case=None):
    if domain not in SCOPES or variant not in ("strict", "loose", "faulty") or mode not in ("live", "demo"):
        raise ValueError("Invalid specialist, prompt variant or mode")
    if not isinstance(question, str) or not question.strip() or len(question) > 4000:
        raise ValueError("Question must have between 1 and 4,000 characters")
    if not 0 < threshold <= 1:
        raise ValueError("Threshold must be greater than zero and at most one")
    sid, started = uuid.uuid4().hex, time.monotonic()
    model = os.environ.get("OPENAI_MODEL", "gpt-4.1-mini") if mode == "live" else "fixture-no-model"
    result = {"id": sid, "session_id": sid, "created_at": now(), "domain": domain, "variant": variant,
              "profile": f"{domain}:{variant}", "model": model, "mode": mode, "question": question,
              "prompt_version": PROMPT_VERSION, "judge_version": JUDGE_VERSION if mode == "live" else "keyword-fixture-v1",
              "judge_model": os.environ.get("OPENAI_JUDGE_MODEL", model) if mode == "live" else "keyword-fixture",
              "threshold": threshold, "batch_id": batch_id, "case_id": case["id"] if case else None,
              "category": case["category"] if case else None, "expected_drift": case["expected_drift"] if case else None,
              "drift_detected": None, "evaluation": None, "answer": None, "released_answer": None,
              "alert": None, "error": None, "status": "running"}
    with fp.session(sid, agent_id=f"{domain}-{variant}"):
        fp.event.agent_start(goal="Domain boundary evaluation", workflow="domain_drift", profile=result["profile"],
                             domain=domain, variant=variant, mode=mode, batch_id=batch_id, prompt_version=PROMPT_VERSION)
        hook_id = None
        try:
            if mode == "live":
                result["answer"] = await respond(specialist_prompt(domain, variant), {"question": question})
            elif variant == "faulty":
                result["answer"] = FIXTURE_ANSWERS[TARGETS[domain]]
            elif case:
                result["answer"] = case["demo_answer"]
            elif keyword_domain(question) not in (domain, "mixed") and variant == "strict":
                result["answer"] = f"I can only help with {domain}. Please ask a question in that specialty."
            else:
                label = domain if variant == "strict" else keyword_domain(question)
                result["answer"] = FIXTURE_ANSWERS.get(label, FIXTURE_ANSWERS[domain])
            if mode == "demo":
                fp.event.tool_use(tool_name="fixture_response", tool_call_id=sid, input={"profile": result["profile"]})
                fp.event.tool_result(tool_name="fixture_response", tool_call_id=sid, output={"answer": result["answer"]})
            hook_id = uuid.uuid4().hex
            fp.event.hook_triggered(hook_name="domain_drift", hook_id=hook_id, trigger_event="response_ready")
            verdict = await judge(domain, question, result["answer"]) if mode == "live" else demo_verdict(domain, question, result["answer"])
            result["evaluation"] = verdict.model_dump()
            result["drift_detected"] = verdict.drift_score >= threshold
            result["status"] = "drift_detected" if result["drift_detected"] else "in_domain"
            result["released_answer"] = None if result["drift_detected"] else result["answer"]
            fp.event.hook_completed(hook_name="domain_drift", hook_id=hook_id, outcome="rejected" if result["drift_detected"] else "success",
                                    output={"evaluation_type": "domain_drift", "drift_score": verdict.drift_score,
                                            "in_scope_score": 1-verdict.drift_score, "drift_detected": result["drift_detected"],
                                            "threshold": threshold, "domain": domain, "variant": variant, "mode": mode,
                                            "response_domain": verdict.response_domain, "rationale": verdict.rationale,
                                            "judge_version": result["judge_version"]})
            hook_id = None
            if result["drift_detected"]:
                result["alert"] = {"id": f"drift-{sid}", "kind": "DomainDriftDetected", "severity": "warning",
                                   "message": f"{domain}/{variant} drift={verdict.drift_score:.2f} >= {threshold:.2f}",
                                   "sdk_event_emitted": True, "cloud_delivery": "not_verified"}
                fp.event.error(error_type="DomainDriftDetected", message=result["alert"]["message"], domain=domain,
                               variant=variant, drift_score=verdict.drift_score, threshold=threshold, response_domain=verdict.response_domain,
                               mode=mode, batch_id=batch_id, evaluation_version=result["judge_version"])
            fp.event.agent_end(outcome="rejected" if result["drift_detected"] else "success", summary=result["status"],
                               drift_score=verdict.drift_score, domain=domain, variant=variant, mode=mode)
        except asyncio.CancelledError:
            if hook_id:
                fp.event.hook_completed(hook_name="domain_drift", hook_id=hook_id, outcome="failed", error="Cancelled")
            fp.event.agent_end(outcome="failed", summary="Evaluation interrupted")
            result.update(status="error", error="Evaluation interrupted; drift unknown")
            result["duration_ms"] = round((time.monotonic()-started)*1000)
            store.save("runs", result)
            raise
        except Exception as exc:
            if hook_id:
                fp.event.hook_completed(hook_name="domain_drift", hook_id=hook_id, outcome="failed", error=type(exc).__name__)
            fp.event.error(error_type="DomainEvaluationError", message=str(exc) if isinstance(exc, ModelError) else "Evaluation failed; drift unknown")
            fp.event.agent_end(outcome="failed", summary="Evaluation failed")
            result.update(status="error", error=str(exc) if isinstance(exc, ModelError) else "Evaluation failed; drift unknown")
    result["duration_ms"] = round((time.monotonic()-started)*1000)
    store.save("runs", result)
    return result
