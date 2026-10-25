"""Benchmark orchestration and dashboard summaries for domain drift."""
import asyncio
from datetime import datetime, timezone
import uuid

from drift import run_drift
from prompts import BENCHMARKS
import store


def utc_now():
    return datetime.now(timezone.utc).isoformat()


async def run_benchmark(mode="demo", threshold=0.5):
    """Run labelled cases sequentially to keep API usage predictable."""
    batch = {"id": uuid.uuid4().hex, "created_at": utc_now(), "mode": mode,
             "threshold": threshold, "status": "running", "total": len(BENCHMARKS),
             "runs": [], "summary": None, "error": None}
    store.save("batches", batch)
    try:
        for case in BENCHMARKS:
            run = await run_drift(case["domain"], case["variant"], case["question"], mode,
                                  threshold, batch_id=batch["id"], case=case)
            batch["runs"].append(run["id"])
        results = [store.get("runs", run_id) for run_id in batch["runs"]]
        results = [item for item in results if item]
        correct = sum(item["drift_detected"] == item["expected_drift"] for item in results)
        batch.update(status="completed", summary={"cases": len(results), "correct": correct,
            "accuracy": correct / len(results) if results else 0,
            "alerts": sum(bool(item["drift_detected"]) for item in results),
            "missed_expected_alerts": sum(item["expected_drift"] and not item["drift_detected"] for item in results),
            "false_alerts": sum(not item["expected_drift"] and item["drift_detected"] for item in results)})
    except asyncio.CancelledError:
        batch.update(status="interrupted", error="Benchmark cancelled")
        raise
    except Exception as exc:
        batch.update(status="error", error=str(exc))
    finally:
        store.save("batches", batch)
    return batch


def dashboard(limit=100):
    runs = store.list_records("runs", limit)
    alerts = [item for item in runs if item.get("alert")]
    return {"runs": runs, "alerts": alerts,
            "metrics": {"total_runs": len(runs), "alerts": len(alerts),
                        "in_domain": sum(item.get("status") == "in_domain" for item in runs),
                        "errors": sum(item.get("status") == "error" for item in runs)},
            "batches": store.list_records("batches", 20)}
