# ThesisLab Agentic Research Workspace V1 — local delivery

Delivery date: 2026-10-14 (Asia/Shanghai). Code is uncommitted on top of
`9ae48edcdef203423a5f0f508c6067f68e2102b2`. Existing M2.5/M3 changes preserved.
No push, public deployment, real model/finance request, credential read or deletion.

## Start / stop

```bash
.venv/bin/python -B tools/serve_v1.py --port 8766 --seed-local-corpus
```

URL: http://127.0.0.1:8766. Default mode is offline. Ctrl+C closes the foreground
server. The delivery instance PID is 14482; `kill -INT 14482` closes that instance
only, while it still owns this port. All listeners bind 127.0.0.1.
Port 8765 is the earlier M3 service, not V1. V1 uses a separate local SQLite file.
No new dependencies installed. Existing .venv and bundled Playwright/Chrome were used.

## Human acceptance route

1. Library: choose financial demo, explicitly labeled human-authored plan.
2. Review editable subclaims, support/refute actions, defined periods and change
   condition. Confirm with review checkbox and explanation; no technical fields needed.
3. Start Agent research: five actual sequential local steps, persisted before and
   after execution. Pause at a step boundary, refresh and resume without replaying
   completed steps. An interrupted running step halts for manual review.
4. Report: independently evaluated revenue and margin, supporting and opposing
   evidence, missing facts, conditions and conflict limitations. Follow evidence
   buttons back to recursive Decimal formulas and original report pages.
5. Keep supplier-date cause unresolved or select issuer-date field with an audit
   reason. Original source records remain immutable.
6. Save, refresh and reopen; compare pre/post research versions in Comparison view.

For actual AI proposals choose cached candidate #4. The original multi-node output
is preserved; suggestions and critical clarifications require human review. Run
without financial coverage returns unverifiable, rather than inventing evidence.
Cached attribution #6 remains invalid and editable; no silent repair.
Arbitrary new statements are saved honestly as manual drafts in offline mode.

## Actual roles and tools

| Logical agent | Implementation and current boundary |
|---|---|
| Thesis Decomposition | Existing DeepSeek CandidateProvider / exact original cache import; strict M2 validation; semantic review independent. No new model calls in V1 acceptance. Financial demo uses explicitly manual design. |
| Evidence Retrieval | Orchestrator matches approved financial predicates to unique local admitted Scope, traverses M1 source trace; Q2 plans invoke existing Decimal calculations. No online data retrieval. |
| Counter-Evidence | Explicit refute-task traversal with same-scope sources, independently checked by M2. Tests both sides rather than assigning direction from task purpose. No open-web search for alternative causes. |
| Conflict Resolution | Audits recorded M1 conflicts in bound evidence closure, marks needs_review, leaves both values intact; existing field-level human review endpoint. No autonomous arbitration. |
| Conclusion Assessment | Existing M2 evaluate/AND/OR/necessary relationships, missing/future facts stay unverifiable. No invented probability. |
| Research Report | Deterministic structured report from saved M2 run, original claim captions, source IDs, counter-tasks, conditions and limitations. No LLM financial prose promoted to fact. |

Tool chain: confirmed design → local catalog/scope/trace → refute tasks → recorded
conflict audit → M2 evaluate → persisted report. Each step records input confirmation,
design hash, timestamps, attempt count, result and failure; execution records zero
external model/financial calls. No automatic retry. Rerun is a new user-requested
execution; completed old runs/reports remain in append-only workspace events.

## Acceptance evidence

Final Python/HTTP: **161 tests passed, 0 failed; 2 external-fixture classes skipped**.
Original 162-test result belongs to an earlier run and is not substituted.
Project-local genuine material tests still verify 8 issuer fields, provider fields,
original PDF locators, Q2 calculations, dates and reopen. Added V1 tests cover
pause/reopen/resume, plan invalidation, controlled failure, interrupted execution,
HTTP orchestration and version comparison, genuine report, honest cache miss.

```bash
.venv/bin/python -B tools/run_tests.py --retain-local-temp --require-local-corpus
```

Final browser: **14 checkpoints passed, 0 failed**. First attempt: 12 passed and
1 mobile overflow assertion failed. Root cause was the five-tab nonwrapping flex
layout; one CSS fix wraps tabs. Second attempt passed including mobile overflow.
Earlier M3 history test now explicitly awaits rendered history and passes.
No repeated further testing. Private logs retain both attempts.

Browser proved: new thesis + honest mode; hidden advanced fields; pre-confirmation
block; actual cached four-node AI proposal; AI-plan execution with evidence gap;
real financial support/refute/conflict/report; source formula/report page; human
date review; save/reload; history; fixed version diff; desktop/mobile; no JS errors.
Financial demo direction is computed by M2, not hardcoded in product code. Browser
assertions compare to the prior verified expected direction. No financial values,
raw supplier response or PDFs are included in source/test files.

Private artifacts: `.local/v1-python-final.log`, `.local/v1-browser-results.json`,
`.local/v1-browser-first-attempt.log`, `.local/v1-browser.log`, desktop/mobile PNGs.
They are ignored and must not be published. Browser tests restrict requests to
127.0.0.1; genuine local regression also patches outbound sockets to fail.

## Implemented / partial / absent

Implemented: three views, human confirmation, actual sequential role execution,
source/drilldown, counter-evidence, unresolved conflict review, report, recovery,
same-thesis immutable-version comparison, pause/resume backend and UI, honest
cache-miss handling, advanced-only technical parameters.

Partial: decomposition is real prior AI output for cached originals; financial demo
plan is manual. Retrieval/counter search cover the admitted local corpus only.
Conflict detection reuses recorded M1 findings; it does not scan fresh sources.
Report is structured deterministic text. Trace and safety checks are not a legal,
financial audit, full penetration test or calibration guarantee.

Absent/not enabled: fresh Live calls this round, arbitrary-thesis auto-decomposition
in offline mode, online finance adapters, new counter-source discovery, automation,
trading, historical PIT, multi-user service, publicly redistributable financial demo.

## Incremental files

New: `orchestrator.py`, `tools/serve_v1.py`, `tools/v1_e2e.mjs`,
`tests/test_orchestrator.py`, `docs/V1-AUDIT.md`, this delivery report.
Modified existing uncommitted M3: `workspace.py` (honest miss/source and edit
invalidation), `web_server.py` (role routes/consent), `web/app.js` (workspace UX,
progress/report/comparison), `web/style.css` (advanced/mobile), `test_workspace.py`,
`test_local_corpus.py`, `audit_staged.py` (explicit browser-script allowlist).
README updated from stale M1/M2-only description. Original research reports untouched.
No migration required: version-3 event payloads gain optional fields; existing
events retain original contents. Before-images retained in private baseline folder.

Working-tree safety check: **58 source/document/config files checked, 0 findings**
using the existing path allowlist, secret-pattern check and admitted original
financial-value exclusion. No matched values printed. This audits actual unstaged
source as well as tracked files, not an empty staging area. `.local` material is
ignored. Private result: `.local/v1-safety-audit.json`. It is a limited content
check, not a claim of comprehensive security or data-rights clearance.

## Remaining authorization

Live model calls require separate activation/budget approval and per-click backend
consent. Data public display/retention/secondary-use rights remain unconfirmed;
financial case is strictly local internal validation. New model/finance services,
Git push or public deployment require user approval. Project license remains
unselected; no source copied from reference projects.

Stop here for human product acceptance; no automatic next milestone.
