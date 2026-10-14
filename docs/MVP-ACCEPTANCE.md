# MVP acceptance — 2026-10-14, Asia/Shanghai

Latest scope: complete local Web product, environment-only Provider configuration,
no new public deployment. Existing M1/M2/M4/V1 files/databases preserved.

## Actually executed

- Baseline: 184 tests, OK, 2 private-fixture suites skipped.
- Before env change: 194 tests, OK, 2 private-fixture suites skipped.
- After env change: 199 tests, OK, 2 private-fixture suites skipped (11.236s).
- Browser: real localhost:8767 workspace opens; creates/persists a new task;
  missing model gives explicit error, never a fake plan; returning to research
  library after server restart restores the task.
- Browser environment acceptance: Provider page shows deepseek/deepseek-chat,
  unconfigured model/finance status, environment permission and separate public
  consent. DOM password field count=0; model_key/financial_key fields count=0.
  Separate public consent checkbox saves and renders checked; no key form exists.
- HTTP fixtures: environment secret configured only server-side; GET settings
  never returns it; POST settings=405; injecting a key into consent=400; complete
  background research, source lineage, followup and revision are exercised.
- Real public smoke was attempted (no model or paid financial API). DNS pinning
  rejected the current network's non-global resolution: public_dns_not_global.
  No successful real network retrieval is claimed. Results stay in ignored .local.
- No paid model/Fuyao credentials were read or used in this run. .env was created
  with blank keys, ignored by Git, mode 0600; existing .env would be preserved.
- Docker binary absent on this machine: Compose/Dockerfile provided, runtime build
  not executed or claimed. Python localhost service actually runs.

Screenshot of readonly Provider/consent page is retained privately in
`.local/provider-env-browser.jpg` and is not uploaded to GitHub.

## Reproducible cases and origin labels

| Scenario | Fixture test | Expected behavior |
| --- | --- | --- |
| Revenue 120 vs 100 | RuntimeTests end-to-end | deterministic 20% support, raw JSON provenance |
| Revenue 80 vs 100 | negative evidence | deterministic -20% refutation |
| Ambiguous profit meaning | critical ambiguity | cannot execute until critical answer |
| Same period 120 vs 130 | conflicting vintages | both preserved, unverifiable |
| SEC HTTP403 | missing/failure | explicit failed call, no evidence/no retry |
| Second company same scope | company comparison | comparable numeric rows |
| Explain causality | followup | model inference, needs new research |
| Interrupted in-flight call | restart | no replay, continue unexecuted jobs |
| .env permission=false + key | environment gate | disclosure consent rejected |
| Forged Web settings key | AgentHTTPTests | write rejected, secrets never returned |

These model and SEC HTTP cases are **synthetic fixtures**, not live SEC/model
results. Existing project-local original PDF/historical supplier tests are
**offline real-material regression**, not new authorized supplier requests.

Run `python tools/run_tests.py` in the installed venv. Optional private-original
tests require THESISLAB_PHASE3_ROOT and --require-real, as described in historical
README sections. Browser checks can be repeated by opening /research, inspecting
settings, creating a task, restarting and restoring it. No API Key is entered in
the browser.

## Remaining acceptance limitations

Real model + paid supplier end-to-end run requires operator-filled .env and a
network with public DNS/authorized HTTPS connectivity. The legal credentials,
supplier quotas/billing and current schema compatibility must be tested with the
user's account. No substitution of test fixtures is permitted in production.
Public-source parsing is deliberately narrow. Qualitative causal/forecast claims
remain unverifiable. Docker execution and authenticated live provider acceptance
remain unverified; these are not described as completed deployment.
