# FailProof domain-drift lab

A FastAPI demo that uses prompt profiles as virtual domain models. Each response is checked by an independent domain judge before release. When the score meets the threshold, the response is withheld, a `domain_drift` hook is completed as rejected, and a `DomainDriftDetected` FailProof error event is emitted.

The included benchmark covers finance, healthcare, legal, and deliberately off-domain responses. It runs entirely with deterministic fixtures in demo mode; live mode calls the same OpenAI model for both the specialist response and the independent judge.

## Run locally on Windows

From this directory, create a Windows virtual environment (the checked-in `venv-failproof` was created on Linux and cannot be used from PowerShell):

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn server:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000. Use **Demo fixtures** to run immediately. To use OpenAI, set `OPENAI_API_KEY` in `.env`, optionally set `OPENAI_MODEL` and `OPENAI_JUDGE_MODEL`, then restart the server. The API docs are at http://127.0.0.1:8000/docs.

## API

`POST /api/evaluations`

```json
{"domain":"finance","variant":"strict","question":"Explain DSCR.","mode":"demo","threshold":0.5}
```

`POST /api/benchmarks` runs the six labelled cases. `GET /api/dashboard` returns recent runs, alerts, and batch summaries persisted in `.runtime/drift.sqlite3`.

## FailProof instrumentation

`engine.configure()` configures the local spool at `.runtime/failproof` (override with `FAILPROOF_SPOOL`). Every evaluation has an `agent_start` and `agent_end`, while the drift gate emits `hook_triggered`/`hook_completed`. A detected drift additionally emits an `error` event.

The SDK writes JSONL files locally. For explicit direct Cloud delivery, set `FAILPROOF_API_KEY` to a scoped key with `events:add` in `.env`, then call `POST /api/failproof/sync`. Accepted batches are moved to `.runtime/failproof/sent/` rather than deleted. You can also run a FailProof collector against the same spool instead.

## Important limits

Demo scoring is transparent keyword matching for safe offline smoke tests, not semantic classification. Live scoring uses a second model and is still an evaluation signal, not a compliance determination. Test the threshold, prompts, and benchmark cases with representative failures before using this in a high-impact workflow.
