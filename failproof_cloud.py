"""Opt-in delivery of local FailProof SDK JSONL batches to FailProof Cloud."""
import os
from pathlib import Path

import httpx


class CloudUploadError(Exception):
    pass


def upload_pending_events():
    """Upload local NDJSON files and retain accepted batches under sent/."""
    key = os.environ.get("FAILPROOF_API_KEY")
    if not key:
        raise CloudUploadError("FAILPROOF_API_KEY is not configured")
    spool = Path(os.environ.get("FAILPROOF_SPOOL", ".runtime/failproof")) / "events"
    files = sorted(spool.glob("*.jsonl"))
    sent = spool.parent / "sent"
    sent.mkdir(parents=True, exist_ok=True)
    uploaded = skipped = 0
    with httpx.Client(timeout=30) as client:
        for path in files:
            body = path.read_bytes()
            if not body.strip():
                path.replace(sent / path.name)
                continue
            response = client.post("https://app.befailproof.ai/v1/events", content=body,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/x-ndjson"})
            if response.status_code == 401:
                raise CloudUploadError("FailProof rejected FAILPROOF_API_KEY")
            if response.status_code == 403:
                raise CloudUploadError("FAILPROOF_API_KEY needs the events:add permission")
            if response.status_code >= 500:
                raise CloudUploadError("FailProof Cloud could not accept events; files were retained for retry")
            if response.status_code != 200:
                raise CloudUploadError(f"FailProof returned HTTP {response.status_code}; files were retained")
            payload = response.json()
            uploaded += payload.get("accepted", 0)
            skipped += payload.get("skipped", 0)
            path.replace(sent / path.name)
    return {"files": len(files), "accepted": uploaded, "skipped": skipped}
