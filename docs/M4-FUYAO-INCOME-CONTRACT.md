# M4 / Stage 1 — Fuyao income contract and offline financial channel

2026-10-14, Asia/Shanghai. Scope: local preparation, Mock and existing real
history; no new authenticated financial/model calls, credentials, push or deployment.

## Evidence hierarchy and current-access limitation

1. Phase3 `diagnostic-followup/new-request-records.json` records HTTP200/code0,
   complete body, 3,748 bytes, 6 rows and a response hash matching the project-local
   archived body. Parameters: thscode=600519.SH, period=quarterly, limit=6.
2. Phase3 `Authenticated-Diagnostic-Result.md` and preceding transport diagnosis
   record GET and X-api-key. Earlier incomplete reads are not successful results.
3. Archived official `public-document-snapshots/api-reference-financials.html`
   was acquired 2026-10-13T17:02:11.582028Z; SHA256
   `23e60606a69e6a4df04e11f3a0459bb6cea34b88b85f82643f2dca971522ffb5`.
   Overview snapshot SHA256:
   `0dd4c59d6a9c5b058a0e0a0d9353d9da2ad591c0131c63bdf6a57bfaba379b9b`.
   Both were read and hashes matched the existing manifest this round.
4. Current direct document fetch failed; official GitHub URLs returned404 through
   the web tool. Search-indexed official references corroborate the endpoint/MCP
   names but do not establish that the current server contract has not changed.

Sources: [financial statements](https://fuyao.aicubes.cn/docs/api-reference/financials/),
[overview/auth/errors/limits](https://fuyao.aicubes.cn/docs/api-reference/overview/),
[official repository](https://github.com/HiThink-Tech/Financial-API),
[A-share MCP reference](https://github.com/HiThink-Tech/Financial-API/blob/main/docs/mcp/hithink-finance-a-share.md).
The detailed contract below is **HISTORICAL_OFFICIAL_DOCUMENT_SUPPORTED**; only
the exact recorded quarterly/latest-six query is **HISTORICALLY_CALL_VERIFIED**.
Current permissions and service availability are **UNVERIFIED**.

## Accurate recovered wire contract

| Item | Contract | Evidence status |
|---|---|---|
| Base/method/path | GET `https://fuyao.aicubes.cn/api/a-share/financials/income-statements` | Historical documentation + Phase3 execution |
| Authentication | Header `X-api-key`; no credential in URL | Historical official contract and diagnostic record; no credential read now |
| thscode | Required single full code with market suffix SH/SZ/BJ; no comma list | Documented;600519.SH used successfully |
| period | annual or quarterly; documented default annual; client always explicit | quarterly tested;annual not tested |
| Latest mode | Omit start/end; limit default4, integer1–20; descending report end | limit6 tested;other limits not runtime-verified |
| Range mode | start/end both Unix milliseconds, inclusive report-end window; end≥start; span≤10 years | Documented only;not tested |
| Mutual exclusion | limit cannot accompany start/end; only one range bound invalid, code1004 | Documented only |
| MCP equivalent | get_a_share_financials_income_statements | Fuyao MCP reference;NOT iFinD MCP, neither connection tested |

Safe no-key request description:

```text
GET /api/a-share/financials/income-statements?thscode=600519.SH&period=quarterly&limit=6
Authentication header name: X-api-key
Credential value: intentionally absent
```

The implementation has a pure wire-description builder, **no live HTTP finance
client and no credential loader**. Headers Accept-Encoding:identity and socket
timeout20s/2MB guard belong to the prior diagnostic client, not vendor parameters.
Historical response was chunked with no Content-Length/Content-Encoding; a future
client must validate complete stream termination before reading business code.

## Return schema and units

Envelope: code(integer), message(string), request_id(string), data(object/null).
Successful data: timestamp(milliseconds), item(array). data.timestamp is the
maximum returned period_end_ms; it is not acquisition or issuer disclosure time.

Each row metadata: thscode, ticker, period, fiscal_year, fiscal_period(FY/Q1/Q2/Q3/Q4),
report_date_ms, period_end_ms, currency. Financial fields are number or null:

`operating_income`, `operating_costs`, `operating_expenses`, `sales_fee`, `manage_fee`,
`research_and_development_expenses`, `operating_profit`, `interest_expenses`,
`profit_total`, `income_tax_expense`, `net_profit`, `parent_holder_net_profit`, `basic_eps`.

Contract units: original-currency yuan, CNY for A-shares; basic_eps is yuan/share.
Contract consolidation: consolidated. Raw response has no separate unit,
consolidation, actual/forecast or flow-basis field. Null is missing, never zero.
operating_expenses is total operating cost, not the operating_costs input to gross
margin. JSON uses Decimal parsing, not binary floating-point.

Only eight income/cost fields at 2025/2026 Q1/H1 have original-report verification.
Q1 is Jan–Mar YTD, Q2 labels here are Jan–Jun YTD. This is a **case-level**
verified annotation, not a global quarterly→single or quarterly→YTD assumption.
Other returned periods/metrics retain unknown flow start/basis and partial quality.
Single Q2 is calculated H1−Q1 for income and cost separately; never subtract ratios.

## Errors, quota, fees and rights

Documentation: check HTTP and business code independently. Business errors may
arrive with HTTP200;429 can occur without a standard envelope. code2001 is missing/
invalid authentication,2003 denied capability;1001–1004 parameter errors;
3001/3002/3004 symbol/data/type problems;4001 limit;5001–5003 server/upstream errors.
These error responses were not newly tested against the supplier this round.

Historical overview says no cumulative-count restriction and dynamic throttling.
No fixed QPS, account-specific quota or guaranteed free tariff established.
**Billing, balance deduction, current account permissions, public display,
long retention and secondary use: UNVERIFIED.** Permission/charge/rate signals
must halt future live calls; no automatic retry or payment operation is prepared here.

## Financial tool and orchestration boundary

`FinancialRequest`: provider, operation, entity, requested metrics, desired report
ends, period/query mode, consolidation, request ID. `FinancialResult` separates:

- Acquisition: available / unauthorized / not_connected / field_missing /
  data_missing / call_failed / unsupported.
- Origin: real_historical_response / synthetic_mock / disabled.
- Per-datum quality: prior-verified or partial, source pointer, original date,
  normalized unit/basis and optional official evidence link.
- Evidence direction and claim conclusion remain M2 concerns; available does not
  imply support, financial truth, current availability or public rights.

`FuyaoHistoricalProvider` locally projects the existing response to a request.
Original query parameters, source acquisition time and current adaptation time are
separate. A local limit/range filter is not a new real supplier query or completeness
claim. Missing periods and fields remain explicit. No source fallback to an issuer
website occurs if a financial provider is unavailable.

Admission rechecks JSON field, official PDF cell, scope, disclosure-index date and
original artifacts using M1, retains original supplier dates, and appends four
unresolved date conflicts. Net profit/EPS remain partial and are not admitted as
trusted facts. Existing source hashes are integrity checks, not fact authenticity.

Orchestrator now provides:
`plan_financial_requests → acquire_financial → calculate_financial → Workspace.run`.
It requires current confirmed design, compiles one structured request per Evidence
Task (support/refute/discriminate), requests income/cost inputs for derived metrics,
and requests profit bridge fields for attribution. Nonrecurring-profit absence is
explicit; income growth cannot establish attribution. Named M1 Decimal functions
produce bound evidence for M2; unresolved/time/forecast rules remain unchanged.

Official disclosure code `online_research.py` is preserved as a supplementary
verification component. It is not registered as a financial supplier. This stage
does not rewire Web controls or authorize online disclosure execution.

Independent `IFinDMCPBoundary` returns not_connected. It has no invented server
URL/tool list/schema. Actual connection discovery, account/data rights and per-tool
authorization must precede implementing any MCP transport. Fuyao's MCP tool name
must not be mislabeled iFinD.

## Tests and changed files

```bash
.venv/bin/python -B tools/run_financial_tests.py
```

Actual result: **121 passed,0 failed,0 skipped**. This is a focused offline suite,
not the earlier161/169 tests or a full Web/browser acceptance. Ten new tests cover
query modes/limits, null vs zero, typed states, mock origin, malformed/incomplete
and tampered responses, eight real historical fields, four report locators, restore,
EPS unit/partial quality, and financial tool→Decimal→M2 regression. Existing Q2
single-quarter regression also passes. Network connect and subprocess.run are
patched to fail during the suite; scratch files are retained under project `.local`.
First runner launch had a Python multiline-with syntax error, corrected once;
it executed no tests. The subsequent run above passed; no repeated test loop.

New files: `src/thesislab/financial_tools.py`, `src/thesislab/fuyao.py`,
`tests/test_financial_tools.py`, `tools/run_financial_tests.py`, this contract.
Incremental modifications: `src/thesislab/orchestrator.py`, `src/thesislab/workspace.py`.
Prior V2 changes, databases and original Phase3 materials were retained.
No SDK installation, migrations to old financial tables, model calls, financial
HTTP/MCP calls, credentials, commit, push or deployment this round.

## Still requires confirmation

Before live activation: verify latest contract, supplier capability/fees and call
budget, authorize exactly the credential source, implement a complete-response
finance transport and test its permission/limit/charging stops. iFinD additionally
needs a real authorized connection and exposed schemas. Public launch separately
needs data display/retention/reuse permission. Only the prepared offline integration
is complete; live finance and Web integration are not claimed complete.
