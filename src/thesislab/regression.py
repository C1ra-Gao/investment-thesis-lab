"""Explicitly local Phase 3 fixture regression, NOT an online data adapter.

This profile's filenames are fixture layout, not production entity routing.
No financial values or issuer assets are embedded in the source tree.
"""

from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal, localcontext
from html.parser import HTMLParser
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from .domain import (Source, Scope, Evidence, Locator, Basis, Verification,
                     ThesisRevision, Subclaim, ClaimRelation, Assessment, Direction,
                     identifier, ContractError)
from .locators import json_value, pdf_value
from .conflicts import detect
from .finance import yoy, gross_margin, cumulative_to_single, margin_delta
from .store import Store


class MissingMaterial(ContractError):
    pass


class _Index(HTMLParser):
    def __init__(self):
        super().__init__()
        self.active = None
        self.records = []
    def handle_starttag(self, tag, attrs):
        if tag == "li":
            self.active = {"links": [], "text": []}
        if self.active is not None and tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.active["links"].append(href)
    def handle_data(self, value):
        if self.active is not None:
            self.active["text"].append(value)
    def handle_endtag(self, tag):
        if tag == "li" and self.active is not None:
            self.records.append(self.active)
            self.active = None


def _check_index(body: bytes, url: str, disclosed: str) -> str:
    parser = _Index()
    parser.feed(body.decode("utf-8"))
    path = urlparse(url).path
    matches = [r for r in parser.records if any(urlparse(x).path == path for x in r["links"])]
    if len(matches) != 1:
        raise ContractError("disclosure_index_link_not_unique")
    text = " ".join(matches[0]["text"])
    dates = re.findall(r"\b\d{4}-\d{2}-\d{2}\b", text)
    if dates != [disclosed]:
        raise ContractError("disclosure_index_date_mismatch")
    return text.strip()


def _read(path: Path) -> bytes:
    if not path.is_file():
        raise MissingMaterial("required_local_material_missing:" + path.name)
    return path.read_bytes()


def _pdf_path(root: Path, reference: str) -> Path:
    folder = (root / "final-evidence/original-reports").resolve()
    path = (folder / Path(reference).name).resolve()
    if not path.is_relative_to(folder):
        raise ContractError("report_path_outside_evidence_folder")
    return path


def verify_phase3(root: Path, store: Store) -> dict:
    root = root.resolve()
    raw_path = root / "diagnostic-followup/income-response-new-1.json"
    raw_body = _read(raw_path)
    payload = json.loads(raw_body, parse_float=Decimal)
    if payload.get("code") != 0 or not isinstance(payload.get("data", {}).get("item"), list):
        raise ContractError("complete_success_envelope_required")
    ledger = json.loads(_read(root / "diagnostic-followup/new-request-records.json"))
    receipt = next((r for r in ledger if r.get("request_id") == payload.get("request_id")), None)
    if not receipt or not receipt.get("body_complete") or receipt.get("business_code") != 0:
        raise ContractError("no_complete_response_receipt")
    if hashlib.sha256(raw_body).hexdigest() != receipt.get("response_sha256"):
        raise ContractError("provider_snapshot_hash_mismatch")
    trace = json.loads(_read(root / "final-evidence/verified-numeric-trace.json"))
    checks = trace["checks"]
    if len(checks) != 8 or len({c["provider_json_pointer"] for c in checks}) != 8:
        raise ContractError("regression_requires_eight_distinct_fields")
    manifest = json.loads(_read(root / "final-evidence/original-document-manifest.json"))
    by_url = {x["url"]: x for x in manifest}
    index_body = _read(root / "final-evidence/issuer-report-index.html")
    index_path = root / "final-evidence/issuer-report-index.html"
    index_url = "https://www.moutaichina.com/mtgf/tzzgx/cwbg/index.html"
    prepared = []
    pdfs = {}
    # Validate all eight cells before importing any financial evidence.
    for check in checks:
        doc_url = check["original_url"]
        path = _pdf_path(root, check["original_document"])
        body = _read(path)
        if doc_url not in by_url or hashlib.sha256(body).hexdigest() != by_url[doc_url]["sha256"]:
            raise ContractError("official_document_hash_mismatch")
        date_locator = _check_index(index_body, doc_url, check["public_listing_disclosure_date"])
        pointer = check["provider_json_pointer"]
        row_index = int(pointer.split("/")[3])
        row = payload["data"]["item"][row_index]
        field = pointer.rsplit("/", 1)[1]
        suffix = "第一季度" if row["fiscal_period"] == "Q1" else "半年度"
        if row["fiscal_period"] not in ("Q1", "Q2") or field not in ("operating_income", "operating_costs"):
            raise ContractError("unexpected_regression_field_or_period")
        column = str(row["fiscal_year"]) + "年" + suffix
        locator = Locator("preflight", page=check["page_1_based"], table=check["table"],
                          row=check["row"], column=column)
        official = pdf_value(body, locator)
        provider = json_value(raw_body, pointer)
        if (provider != official or provider != Decimal(check["raw_value"])
                or official != Decimal(check["original_value"].replace(",", ""))):
            raise ContractError("financial_value_crosscheck_failed")
        if row["currency"] != check["currency"]:
            raise ContractError("currency_mismatch")
        end = datetime.fromtimestamp(row["period_end_ms"] / 1000, ZoneInfo("Asia/Shanghai")).date()
        if end != date.fromisoformat(check["report_period_end"]):
            raise ContractError("provider_period_end_mismatch")
        if date.fromisoformat(check["report_period_start"]) != date(row["fiscal_year"], 1, 1):
            raise ContractError("not_calendar_ytd_origin")
        pdfs[doc_url] = (path, body, check, date_locator)
        prepared.append((check, row, field, locator, provider))
    if len(pdfs) != 4:
        raise ContractError("regression_requires_four_original_reports")

    api_source = Source(identifier("source", payload["request_id"]), "Cached financial response",
                        "https://fuyao.aicubes.cn/api/a-share/financials/income-statements", "provider_cache")
    store.put_source(api_source)
    raw_id = store.put_artifact(api_source.id, raw_body, "application/json",
                                receipt["finished_at_utc"], str(raw_path))
    index_source = Source(identifier("source", index_url), "Issuer disclosure index", index_url, "issuer_index")
    store.put_source(index_source)
    index_acquired = datetime.fromtimestamp(index_path.stat().st_mtime, timezone.utc).isoformat()
    index_id = store.put_artifact(index_source.id, index_body, "text/html", index_acquired, str(index_path))
    pdf_ids = {}
    for url, (path, body, check, date_locator) in pdfs.items():
        source = Source(identifier("source", {"url": url, "date": check["public_listing_disclosure_date"]}),
                        path.stem, url, "issuer_report", disclosed_on=date.fromisoformat(check["public_listing_disclosure_date"]),
                        disclosure_locator=encode_date_locator(index_id, url, date_locator))
        store.put_source(source)
        pdf_ids[url] = store.put_artifact(source.id, body, "application/pdf", by_url[url]["local_saved_at_utc"], str(path))

    fields = {}
    pairs = []
    conflicts = []
    for check, row, field, locator, value in prepared:
        scope = Scope(row["thscode"], field, date.fromisoformat(check["report_period_start"]),
                      date.fromisoformat(check["report_period_end"]), check["currency"], check["unit"],
                      "consolidated", Basis.YTD)
        provider_date = datetime.fromtimestamp(row["report_date_ms"] / 1000, ZoneInfo("Asia/Shanghai")).date()
        provider = Evidence(identifier("evidence", {"artifact": raw_id, "pointer": check["provider_json_pointer"]}),
                            scope, value, Verification.VERIFIED, "provider",
                            Locator(raw_id, json_pointer=check["provider_json_pointer"]),
                            provider_report_date=provider_date,
                            reported_period_label=row["period"] + ":" + row["fiscal_period"], raw_lexeme=str(value),
                            limitation="Normalized YTD scope crosschecked with issuer report; provider date semantics unverified.")
        official_locator = replace(locator, artifact_id=pdf_ids[check["original_url"]])
        official = Evidence(identifier("evidence", {"locator": official_locator}), scope, value,
                            Verification.VERIFIED, "issuer", official_locator,
                            issuer_disclosure_date=date.fromisoformat(check["public_listing_disclosure_date"]),
                            raw_lexeme=check["original_value"], limitation="Issuer report is unaudited; index date has day precision.")
        store.put_evidence(provider)
        store.put_evidence(official)
        crosscheck_id = store.put_crosscheck(provider.id, official.id)
        fields[(scope.start.year, row["fiscal_period"], field)] = official
        pair_conflicts = detect(provider, official)
        for conflict in pair_conflicts:
            store.put_conflict(conflict)
            # Automated projection of the verified index, NOT a new human approval.
            state = store.conflict_state(conflict.id)
            if not state["reviews"]:
                store.review(conflict.id, reviewer="automated_verified_index_projection",
                             reason="Use the issuer-index disclosure date; preserve provider semantics as unresolved.",
                             selected_evidence_id=official.id, field="original_disclosure_date", keep_unresolved=True)
            conflicts.append(conflict.id)
        pairs.append({"provider_evidence": provider.id, "official_evidence": official.id,
                      "metric": field, "period": str(scope.start.year) + row["fiscal_period"],
                      "value_match": True, "crosscheck_id": crosscheck_id,
                      "conflicts": [c.id for c in pair_conflicts]})

    calculations = []
    single = {}
    years = sorted({year for year, _, _ in fields})
    if len(years) != 2 or years[1] != years[0] + 1:
        raise ContractError("regression_requires_adjacent_years")
    for year in years:
        for metric in ("operating_income", "operating_costs"):
            calc = cumulative_to_single(fields[year, "Q2", metric], fields[year, "Q1", metric])
            store.put_calculation(calc)
            calculations.append(calc)
            single[year, metric] = calc.result
    summaries = []
    results_for_assessment = []
    for name in ("Q1", "H1", "Q2-single"):
        group = {}
        for year in years:
            revenue = single[year, "operating_income"] if name == "Q2-single" else fields[year, "Q1" if name == "Q1" else "Q2", "operating_income"]
            costs = single[year, "operating_costs"] if name == "Q2-single" else fields[year, "Q1" if name == "Q1" else "Q2", "operating_costs"]
            gm = gross_margin(revenue, costs)
            store.put_calculation(gm)
            calculations.append(gm)
            group[year] = (revenue, costs, gm.result)
        previous, current = years
        growth = yoy(group[current][0], group[previous][0])
        delta = margin_delta(group[current][2], group[previous][2])
        for calc in (growth, delta):
            store.put_calculation(calc)
            calculations.append(calc)
        summary = {"period": name, "revenue_2026": str(group[current][0].value), "cost_2026": str(group[current][1].value),
                   "revenue_2025": str(group[previous][0].value), "cost_2025": str(group[previous][1].value),
                   "revenue_yoy_percent": str(growth.result.value), "gm_2026_percent": str(group[current][2].value),
                   "gm_2025_percent": str(group[previous][2].value), "gm_change_pp": str(delta.result.value)}
        # Historical keys in the local audit profile; no values are hardcoded in this runner.
        baseline = next(x for x in trace["calculations"] if x["period"] == name)
        for key in summary.keys() - {"period"}:
            with localcontext() as ctx:
                ctx.prec = 40
                if abs(Decimal(summary[key]) - Decimal(baseline[key])) > Decimal("0.000000000001"):
                    raise ContractError("calculation_regression_mismatch:" + key)
        summaries.append(summary)
        if name != "Q2-single":
            results_for_assessment.extend([(name + ":income", growth.result), (name + ":margin", delta.result)])

    revision_id = identifier("revision", {"provider_sha": hashlib.sha256(raw_body).hexdigest(), "fixture_contract": "m1-v1"})
    root_id = "root"
    subclaims = [Subclaim(root_id, "本研究两个已披露报告期的营业收入同比增长且毛利率改善。")]
    for claim_id, result in results_for_assessment:
        statement = "该报告期营业收入同比大于零。" if claim_id.endswith("income") else "该报告期计算毛利率同比改善。"
        subclaims.append(Subclaim(claim_id, statement))
    revision = ThesisRevision(revision_id, "internal-regression", subclaims[0].statement,
                              tuple(subclaims), tuple(ClaimRelation(c.id, root_id, "and") for c in subclaims[1:]))
    store.put_revision(revision)
    for claim_id, result in results_for_assessment:
        assessment = Assessment(claim_id, result.id, Direction.SUPPORTS if result.value > 0 else Direction.OPPOSES,
                                Verification.VERIFIED, "Deterministic positive-change predicate within the audited scope; no causal inference.")
        store.put_assessment(revision.id, assessment)
    evidence_ids = [i for pair in pairs for i in (pair["provider_evidence"], pair["official_evidence"])]
    evidence_ids.extend(c.result.id for c in calculations)
    store.checkpoint("internal-regression", revision.id, state="awaiting_review", evidence_ids=evidence_ids, conflict_ids=conflicts)
    restored = store.restore("internal-regression")
    return {"input_kind": "REAL_PHASE3_CACHE_NOT_LIVE", "source_fields_matched": len(pairs), "official_reports": len(pdfs),
            "financial_requests": 0, "keychain_reads": 0, "calculations": summaries, "pairs": pairs,
            "conflict_count": len(conflicts), "unresolved_conflicts": sum(c["state"] == "unresolved" for c in restored["conflicts"]),
            "assessments": restored["assessments"], "task_id": "internal-regression", "revision_id": revision.id,
            "trace": store.trace(results_for_assessment[-1][1].id), "project_scope": "M1_offline_only",
            "data_gate": "CONDITIONAL_no_historic_PIT_or_public_data_rights_assurance"}


def encode_date_locator(index_id: str, report_url: str, excerpt: str) -> str:
    return json.dumps({"artifact_id": index_id, "report_url": report_url, "index_excerpt": excerpt}, ensure_ascii=False)
