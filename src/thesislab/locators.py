"""Local-only source extraction; no fetch, OCR, or model-generated locations."""

from decimal import Decimal
import io
import json
import re
import calendar
from .domain import Locator, Scope, Basis, ContractError, amount


def json_value(body: bytes, pointer: str) -> Decimal | None:
    data = json.loads(body.decode("utf-8"), parse_float=Decimal)
    if data.get("code") != 0:
        raise ContractError("provider_response_not_success")
    cursor = data
    for part in pointer.split("/")[1:]:
        part = part.replace("~1", "/").replace("~0", "~")
        cursor = cursor[int(part)] if isinstance(cursor, list) else cursor[part]
    return amount(cursor)


def pdf_value(body: bytes, locator: Locator) -> Decimal:
    try:
        import pdfplumber
    except ImportError as exc:
        raise ContractError("install_regression_extra_for_pdf_verification") from exc
    normalize = lambda text: re.sub(r"\s+", "", text or "")
    with pdfplumber.open(io.BytesIO(body)) as document:
        if locator.page > len(document.pages):
            raise ContractError("pdf_page_not_found")
        page = document.pages[locator.page - 1]
        text = page.extract_text() or ""
        if normalize(locator.table) not in normalize(text):
            raise ContractError("pdf_table_title_not_found")
        values = []
        for table in page.extract_tables():
            header = next((row for row in table if row and normalize(row[0]) == "项目"), None)
            if not header:
                continue
            columns = [i for i, title in enumerate(header) if normalize(title) == normalize(locator.column)]
            for row in table:
                if row and normalize(row[0]) == normalize(locator.row):
                    for index in columns:
                        value = row[index]
                        if value:
                            values.append(amount(normalize(value).replace(",", "")))
        if len(values) != 1:
            raise ContractError("pdf_cell_missing_or_ambiguous")
        return values[0]


def verify_pdf_scope(body: bytes, locator: Locator, scope: Scope) -> None:
    """Verify the actual table caption and units, not just a prior audit's flags."""
    import pdfplumber
    with pdfplumber.open(io.BytesIO(body)) as document:
        text = re.sub(r"\s+", "", document.pages[locator.page - 1].extract_text() or "")
    if (scope.currency != "CNY" or scope.unit != "yuan"
            or not re.search(r"单位[：:]元", text) or not re.search(r"币种[：:]人民币", text)):
        raise ContractError("pdf_currency_or_unit_not_aligned")
    if scope.consolidation != "consolidated" or locator.table != "合并利润表":
        raise ContractError("pdf_consolidation_not_aligned")
    ranges = re.findall(r"(\d{4})年(\d{1,2})[—－\-–至](\d{1,2})月", text)
    annual = (scope.start.month == 1 and scope.start.day == 1 and scope.end.month == 12 and scope.end.day == 31
              and scope.start.year == scope.end.year
              and re.sub(r'\s+', '', locator.column) == str(scope.end.year)+'年度'
              and str(scope.end.year)+'年度' in text)
    if not annual and not any(scope.start.month == int(start) and scope.end.month == int(end)
               and scope.start.day == 1 and scope.end.day == calendar.monthrange(scope.end.year, scope.end.month)[1]
               and scope.start.year == scope.end.year and scope.end.year in (int(year), int(year) - 1)
               for year, start, end in ranges):
        raise ContractError("pdf_period_caption_not_aligned")
    if not locator.column.startswith(str(scope.end.year) + "年"):
        raise ContractError("pdf_comparative_column_year_mismatch")
    if scope.basis != Basis.YTD or scope.start.month != 1 or scope.value_kind != "actual":
        raise ContractError("pdf_ytd_or_actual_scope_not_aligned")
