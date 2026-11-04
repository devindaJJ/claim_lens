# ClaimLens

ClaimLens is an intake system for insurance claim documents. You upload a claim packet (PDF). The system extracts the key fields, checks them against the policy rules retrieved from the policy documents, and either auto-approves the claim or sends it to a human reviewer. The reviewer sees the document next to the extracted fields and accepts or corrects each one.

```
 Upload PDF ─► FastAPI ─► Celery worker
                              │
                              ├─ 1. Text: pypdf text layer, Tesseract OCR for scanned pages
                              ├─ 2. Fields: Claude structured output → Pydantic Claim model
                              │            (or the offline regex baseline)
                              ├─ 3. Confidence: model score × grounding check × OCR quality
                              ├─ 4. RAG: pgvector search over policy clauses, per section
                              ├─ 5. Rules: Claude reads the clauses → PolicyTerms,
                              │            deterministic Python decides pass/fail
                              └─ 6. Route: all confident + all rules pass → auto-approved
                                           otherwise → review queue
                                                         │
                         React reviewer UI ◄─────────────┘
                         PDF on the left · fields, checks and decision on the right
```

## Quick start

You need Docker. An Anthropic API key is optional: without one, the stack uses the deterministic baseline extractor.

```bash
cp .env.example .env          # optionally set ANTHROPIC_API_KEY
make up                       # Postgres+pgvector, Redis, API, worker, UI
make seed                     # embed the 4 policies, queue the 25 sample claims
open http://localhost:8080    # reviewer UI   (API docs: http://localhost:8000/docs)
```

Other commands: `make test`, `make eval`, `make eval-claude`, `make logs` and `make reset`. Run `make help` for the full list.

## How it works

### 1. Text extraction ([text_extraction.py](backend/app/services/text_extraction.py))
pypdf reads each page's text layer. A page with fewer than `OCR_MIN_CHARS_PER_PAGE` characters is treated as a scan: it is rendered at 300 DPI with pypdfium2 and run through Tesseract. The mean word confidence from Tesseract is kept for the page and later lowers field confidence.

### 2. Field extraction ([extraction/](backend/app/services/extraction))
Two extractors share one interface:

* **`ClaudeExtractor`** calls `client.beta.messages.parse(output_format=ClaimExtraction)`. Every field comes back as `{value, confidence, evidence}`, and the result is converted to the domain [`Claim`](backend/app/schemas/domain.py) model. The prompt defines each field precisely, for example "incident date, not the date the letter was written". The call uses `claude-opus-5-5` with server-side refusal fallback enabled. Transient API errors are retried by Celery with backoff.
* **`HeuristicExtractor`** is a regex baseline. It needs no network, so tests, CI and the evaluation always run, and it gives a reference point for comparison.

### 3. Confidence ([confidence.py](backend/app/services/confidence.py))
The extractor's self-reported confidence is adjusted by signals it cannot fake:
* **Grounding**: the quoted evidence must appear in the document text. If it does not, confidence is capped at 0.5.
* **OCR quality**: values from scanned pages are scaled by `0.6 + 0.4 × OCR confidence`.

### 4. Retrieval ([rag/](backend/app/services/rag))
Policies are split at clause level (`1.2 Theft of Vehicle`, `2.1 Flood`, …), embedded locally with `BAAI/bge-small-en-v1.5` through fastembed, and stored in pgvector with an HNSW index. For each claim the system asks three questions:

| Question | Searched within |
|---|---|
| Who is insured, and what is the policy period? | Declarations |
| What is the limit and deductible for this claim type? | Coverages |
| Does an exclusion apply to *this incident description*? | Exclusions |

Each search is filtered by policy number and section. Without the section filter, a long incident description pulled in coverage clauses and the relevant exclusion dropped out of the top-k. The unit tests use an `InMemoryRetriever` with the same chunks and embeddings as pgvector, so the evaluation needs no database.

### 5. Rules ([interpretation.py](backend/app/services/interpretation.py), [validation.py](backend/app/services/validation.py))
The LLM reads the policy and the code decides the outcome. Claude turns the retrieved clauses into structured `PolicyTerms`: period, named insureds, limit, deductible and any triggered exclusions with a reason. Plain Python then evaluates the rules:

`required_fields` · `policy_found` · `claimant_insured` · `incident_in_period` · `coverage_applies` · `within_limit` · `no_exclusion`

Each rule result carries the policy clauses it relied on, and the reviewer UI shows them.

### 6. Routing and review
A claim is auto-approved only if every field's confidence is at least `CONFIDENCE_THRESHOLD` (default 0.80) and every rule passes. Otherwise it goes to the review queue with the reasons listed. In the UI the reviewer accepts or corrects each field. A correction re-runs the policy rules immediately. A claim can be approved only after every field has been reviewed.

## Evaluation

[`data/`](data) holds 25 synthetic claims made by [`generate_data.py`](backend/scripts/generate_data.py) in three layouts: labelled forms, free-text letters and degraded scans. Each claim has a ground-truth JSON file with the expected fields and the expected rule failures. The claims are built to cover:

* each rule failure (over the limit, outside the policy period, claimant not insured, unknown policy, excluded cause, missing amount);
* distractor dates such as the signature date or letter date;
* differing label wording and amount formats;
* cases that need judgement, such as a burst pipe that "flooded the kitchen", which is not a *Flood*.

`python -m evaluation.run_eval` runs the full pipeline on every claim and reports precision and recall for each field. A correct prediction counts as a TP. A wrong prediction counts as both an FP and an FN. A missing prediction counts as an FN. The report also covers rule outcomes and routing safety.

<!-- EVAL:START -->
Evaluated on 25 synthetic claims (form: 11, letter: 8, scanned: 6). P = precision, R = recall.

| Field | heuristic P | heuristic R |
|---|---:|---:|
| `policy_number` | 100.0% | 100.0% |
| `claimant_name` | 100.0% | 100.0% |
| `incident_date` | 100.0% | 100.0% |
| `amount` | 100.0% | 100.0% |
| `claim_type` | 100.0% | 100.0% |

| Metric | heuristic |
|---|---:|
| Field accuracy – form | 100.0% |
| Field accuracy – letter | 100.0% |
| Field accuracy – scanned | 100.0% |
| Rule outcomes exactly right (per claim) | 84.0% |
| Claims needing review that were sent to review | 92.9% |
| Unsafe auto-approvals | 1 |
| Unnecessary reviews | 3 |
| Accuracy of fields with confidence ≥ 0.8 | 100.0% |
| Share of fields above the threshold | 80.8% |

Run details: heuristic – 2026-11-04T13:45:42+00:00, 4.0s.
<!-- EVAL:END -->

**How to read these numbers**

* The regex baseline was written while looking at this dataset, so its perfect field scores mean "no regressions on these 25 documents". They do not show how well it generalises. New layouts would break it, and handling those is the reason the Claude extractor exists.
* The informative result is the rule outcomes. All four baseline errors are exclusion calls that need semantic judgement:

  | Claim | Description | Baseline | Correct |
  |---|---|---|---|
  | CLM-2025-0008 | "pipe … burst and flooded the kitchen" | Flood exclusion | Covered (escape of water) |
  | CLM-2025-0010 | "the nearby river overflowed" | No exclusion → **auto-approved** | Flood exclusion |
  | CLM-2025-0016 | rhinoplasty "for aesthetic reasons" | No exclusion | Cosmetic exclusion |
  | CLM-2025-0020 | "paragliding accident" | No exclusion | Hazardous activities exclusion |

  CLM-2025-0010 is the one unsafe auto-approval. Retrieval *did* return the Flood clause, but keyword matching cannot connect "river overflowed" to "flood". With `EXTRACTOR=claude`, these judgements are made by the `ClaudeInterpreter`. Run `make eval-claude` to measure it on this set; the results table then gains a Claude column next to the baseline.

## Project layout

```
backend/
  app/
    api/            FastAPI routers (claims, review actions, metadata)
    schemas/        domain models (Claim, PolicyTerms, RuleResult…) and API models
    services/
      extraction/   Claude and heuristic extractors
      rag/          chunking, ingestion, pgvector and in-memory retrievers
      text_extraction.py · confidence.py · interpretation.py · validation.py
      pipeline.py   pure pipeline: text → fields → rules → routing
      claims.py     persistence and review workflow
    worker.py       Celery task
    models.py       SQLAlchemy models
  migrations/       Alembic (pgvector extension + HNSW index)
  evaluation/       harness and results
  scripts/          synthetic data generator
  tests/            unit, pipeline and API tests
frontend/           React + TypeScript (Vite) reviewer UI
data/               generated policies, claims and ground truth
```

## Local development without Docker

```bash
python -m venv .venv && .venv/bin/pip install -e "backend[dev]"
docker compose up -d db redis
cd backend
alembic upgrade head
python -m app.cli ingest-policies ../data/policies
uvicorn app.main:app --reload              # API on :8000
celery -A app.worker.celery_app worker      # in another shell
cd ../frontend && npm install && npm run dev   # UI on :5173
```

OCR needs Tesseract installed locally (`brew install tesseract`). Without it, scanned claims fail with a clear error. Everything else still works.

## Configuration

All settings are environment variables. See [.env.example](.env.example) and [config.py](backend/app/config.py). The main ones:

| Variable | Default | Purpose |
|---|---|---|
| `EXTRACTOR` | `auto` | `claude`, `heuristic`, or `auto` (Claude when a key is set) |
| `ANTHROPIC_MODEL` | `claude-opus-5-5` | Model for extraction and policy interpretation |
| `ANTHROPIC_EFFORT` | `medium` | Reasoning effort |
| `CONFIDENCE_THRESHOLD` | `0.80` | Below this, a field sends the claim to review |
| `ATTACH_PDF_TO_LLM` | `false` | Also send the PDF itself to Claude (helps on poor scans) |
| `RETRIEVAL_TOP_K` | `3` | Chunks retrieved per policy question |

## Limitations

* The data is synthetic. Real claim packets are longer, have several documents and are messier. Treat the numbers above as a regression baseline, not as accuracy you can expect in production.
* Slash dates are read day-first (DD/MM/YYYY).
* There is no authentication. Reviewer identity and an audit log would come next.
