# Scrutiny Desk

Review college CIE question papers against taught syllabus coverage, Bloom’s taxonomy, and the examination pattern. Faculty record their decisions and export a draft report. See [AI settings](AI_SETTINGS.md) for provider configuration.

## What works now

1. Upload Set A and check the extracted questions, metadata, marks, CO/PO labels, and printed Bloom’s levels. Set B is optional.
2. Upload a CO–PO mapping photo or enter the course outcome statements and mapping manually.
3. Upload a syllabus sheet or add one file at a time under numbered modules. Choose an entire file or enter the start and end file page numbers and boundary phrases. Confirm the coverage, then run the evaluation.

- View each question’s printed and suggested Bloom’s level, the rationale, syllabus coverage, and supporting source quotes. The agent looks for concepts required by application questions, even when the wording differs from the syllabus. Longer sources are reviewed in windows before selecting evidence.
- Check eight 10-mark full questions, a/b splits, 80 offered marks, and every one of the eight legal 50-mark answer selections.
- Apply 30% L1-L2, 60% L3-L4, and 10% L5-L6 across all **80 offered marks**, with no tolerance.
- Keep unknown values unresolved, preserve duplicate questions, and flag course mismatches.
- Save owner-scoped drafts and immutable source revisions in SQLite. Reject conflicting saves and fabricated source quotes.
- Record faculty-reviewed Bloom’s levels and decisions on coverage, the assessment plan, CO/PO alignment, and format in **Question papers** for each set. Use **Syllabus & coverage** to confirm the source, range, and exam rules. Run scrutiny again to update the findings and draft for the saved revision.
- Generate revision-specific, two-page draft reports based on the supplied departmental format, with bounded comments and blank signature/recommendation fields.
- Run a bounded LangGraph review with a question specialist, a separate verification pass, and a limited repair pass. The app validates source quotations and keeps academic judgments separate from arithmetic checks.
- Explore optional Bloom’s replacements when a paper misses its targets. The app previews the effect on marks and checks proposed wording, syllabus evidence, and the answer key before showing a draft.

## Review and access

Faculty make the final academic decisions and sign the report. Local inference and scanned layouts need faculty validation on the papers used by each course. The automated tests cover software behavior. Model accuracy on real papers requires a separate faculty benchmark.

The local app is designed for localhost. Hosted mode uses a presentation access code and a persistent volume for owner-scoped drafts. Configure the code and provider credentials as server environment variables. Keep question papers, syllabus uploads, and workspace data in private storage.

## Run

Python 3.11+ and Node.js are required.

```powershell
cd backend
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
# Optional, for Windows native OCR:
.venv\Scripts\python.exe -m pip install -r requirements-ocr.txt
Copy-Item .env.example .env
cd ..\frontend
npm ci
npm run build
cd ..
backend\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8010
```

Open http://127.0.0.1:8010. For frontend development, `npm run dev` uses Vite's proxy to backend port 8010.

## AI setup

The example environment file disables AI until configured. The professor chooses local or configured cloud processing in the UI; cloud use requires destination-specific sharing permission. No automatic switch to another provider occurs after an error.

- Local Ollama: `SCRUTINY_AI_PROVIDER=local`, `SCRUTINY_LOCAL_MODEL=<installed-model>`. Only an HTTP loopback model endpoint is accepted.
- Gemini: `SCRUTINY_AI_PROVIDER=gemini`, `GEMINI_MODEL=<supported-model-id>`, `GEMINI_API_KEY=<your-key>`. This sends paper/syllabus excerpts and context to Google's Gemini API when the professor requests AI assistance. Never put a key in source code or chat.
- Any supported cloud adapter: set `SCRUTINY_AI_PROVIDER`, `SCRUTINY_AI_KEY`, and `SCRUTINY_AI_MODEL`. Compatible services also need `SCRUTINY_AI_BASE_URL`. Restart the backend and refresh the page. Follow [AI_SETTINGS.md](AI_SETTINGS.md) for capability settings and connection checks.

Use the provider that performs best against independently faculty-reviewed cases. No academic accuracy benchmark has been completed, so no model is described as the most accurate.

API contracts: [Gemini generation](https://ai.google.dev/api/generate-content), [Ollama chat](https://docs.ollama.com/api/chat), [OpenAI Chat Completions](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create), [Anthropic Messages](https://platform.claude.com/docs/en/api/messages). Every model response must pass local schema validation; failures leave the review unresolved. Alternate providers have offline protocol coverage; complete live academic validation with those services remains outstanding.

## Tests

```powershell
backend\.venv\Scripts\python.exe -m unittest discover -s backend\tests -v
cd frontend
npm run build
```

Backend tests exercise hard-rule arithmetic, exact distributions, missing values, source extraction, owner isolation, stale revisions, draft PDF generation, and bounded AI tool selection using test planners. Test planners do not measure a live model's academic accuracy. Windows sandboxing may require a permitted local socket pair for the FastAPI test client.

## Main implementation

- `backend/app/domain.py`: typed versioned data and explicit unknowns.
- `backend/app/validation.py`: deterministic criteria and answer-path checks.
- `backend/app/intake.py`: conservative source extraction and proposals.
- `backend/app/academic_review.py`: active per-question specialist, verifier, and bounded repair workflow.
- `backend/app/ai_config.py` / `model_client.py`: server-side provider configuration, scoped sharing checks, and validated API adapters.
- `backend/app/repository.py`: persistent owner-scoped revisions and source metadata.
- `backend/app/api.py`: active API; old global-latest and heuristic approval routes are retired.
- `backend/app/bloom_replacements.py`: optional syllabus-backed Bloom’s replacement planning.
- `backend/app/draft_report.py`: validated payload to draft report.
- `frontend/src/App.tsx`: personal upload, coverage, review, findings, and export workflow.

Earlier routes and agents remain in the source tree for reference. The current application uses the review pipeline listed above.
