#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urljoin, urlparse

from playwright.sync_api import BrowserContext, Page, sync_playwright

import stage_build_pool as old
import verify_2059 as core

OUT = Path("stage_output")
OUT.mkdir(exist_ok=True)
WORK = Path("stage_pool_work_v2")
WORK.mkdir(exist_ok=True)

CORPORATE_ENDINGS = (
    "集团股份有限公司|集团有限公司|股份有限公司|有限责任公司|有限公司|股份公司|"
    "重庆市分公司|重庆分公司|分公司|重庆市分行|重庆分行|分行|支行|卷烟厂"
)
CORPORATE_RE = re.compile(rf"^[\u4e00-\u9fffA-Za-z0-9（）()·&＋+\-]{{4,120}}(?:{CORPORATE_ENDINGS})$")
ROLE_PREFIX_RE = re.compile(
    r"^(?:企业名称|单位名称|公司名称|申报单位|建设单位|建设运营单位|牵头单位|依托单位|"
    r"使用单位|服务商名称|供应方|联合单位|配合单位|保险机构及联合单位|揭榜单位)[：:]?"
)
INDEX_RE = re.compile(r"^(?:\d+(?:\.\d+)?|[一二三四五六七八九十百]+)[、.．)）\-]?\s*")
ROLE_SUFFIX_RE = re.compile(r"[（(](?:牵头|联合体牵头|联合申报|申报|建设|运营|依托)[）)]$")
HEADER_HINTS = [
    "企业名称", "企业（机构）名称", "企业(机构)名称", "服务商名称", "申报单位", "建设运营单位",
    "建设单位", "牵头单位", "依托单位", "使用单位", "单位名称", "公司名称", "供应方", "揭榜单位",
    "保险机构及联合单位", "联合单位",
]
BAD_SEGMENTS = {
    "企业名称", "单位名称", "公司名称", "申报单位", "建设单位", "牵头单位", "服务商名称", "供应方",
}


def normalize_segment(value: str) -> str:
    value = core.clean_text(value).strip("*#|，。；;、:：[]【】")
    value = INDEX_RE.sub("", value)
    value = ROLE_PREFIX_RE.sub("", value).strip()
    value = ROLE_SUFFIX_RE.sub("", value).strip()
    return value


def extract_corporations(value: str) -> list[str]:
    # Labels in a single cell are converted into separators before splitting.
    value = re.sub(
        r"(?:配合单位|联合单位|建设运营单位|建设单位|申报单位|牵头单位|依托单位|使用单位|供应方|揭榜单位)[：:]",
        "；",
        core.clean_text(value),
    )
    output: list[str] = []
    seen: set[str] = set()
    for segment in re.split(r"[、，,；;\n]+", value):
        segment = normalize_segment(segment)
        if not segment or segment in BAD_SEGMENTS:
            continue
        # Remove explanatory text before a legal name only when a clear colon remains.
        if "：" in segment:
            segment = normalize_segment(segment.rsplit("：", 1)[-1])
        if CORPORATE_RE.fullmatch(segment):
            key = core.norm_name(segment)
            if key not in seen:
                seen.add(key)
                output.append(segment)
    return output


def unique(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        for company in extract_corporations(value):
            key = core.norm_name(company)
            if key not in seen:
                seen.add(key)
                result.append(company)
    return result


def table_company_cells(tables: list[list[list[str]]]) -> tuple[list[str], int]:
    selected: list[str] = []
    selected_tables = 0
    for table in tables:
        company_col: int | None = None
        header_row = -1
        for row_index, row in enumerate(table[:12]):
            normalized = [re.sub(r"\s+", "", core.clean_text(cell)) for cell in row]
            for hint in HEADER_HINTS:
                hint_norm = re.sub(r"\s+", "", hint)
                for column_index, cell in enumerate(normalized):
                    if hint_norm == cell or hint_norm in cell:
                        company_col = column_index
                        header_row = row_index
                        break
                if company_col is not None:
                    break
            if company_col is not None:
                break
        if company_col is None:
            continue
        selected_tables += 1
        for row in table[header_row + 1 :]:
            if company_col < len(row):
                selected.append(row[company_col])
    return selected, selected_tables


def parse_attachment(context: BrowserContext, page_url: str, hrefs: list[str], source_index: int) -> list[str]:
    values: list[str] = []
    target_dir = WORK / "attachments" / f"{source_index:02d}"
    target_dir.mkdir(parents=True, exist_ok=True)
    for attachment_index, href in enumerate(dict.fromkeys(hrefs)):
        absolute = urljoin(page_url, href)
        path = urlparse(absolute).path
        match = re.search(r"\.(xlsx|xlsm|xls|docx|doc|pdf|csv|txt)$", path, re.I)
        if not match:
            continue
        try:
            response = context.request.get(absolute, timeout=90_000)
            if not response.ok:
                core.log("official attachment", absolute, f"HTTP {response.status}", 0)
                continue
            extension = "." + match.group(1).lower()
            local = target_dir / f"attachment_{attachment_index:02d}{extension}"
            local.write_bytes(response.body())
            text = core.attachment_text(local)
            values.extend(extract_corporations(text))
            # Spreadsheets/documents are often represented as one long string;
            # line-level parsing recovers the individual legal entities.
            values.extend(unique(text.splitlines()))
        except Exception as exc:
            core.log("official attachment", absolute, "failed", 0, repr(exc))
    return unique(values)


def read_source(page: Page, context: BrowserContext, source: dict[str, Any], source_index: int) -> list[str]:
    try:
        page.goto(source["url"], wait_until="domcontentloaded", timeout=90_000)
        page.wait_for_timeout(1_200)
        tables = page.eval_on_selector_all(
            "table",
            "tables => tables.map(t => Array.from(t.rows).map(r => Array.from(r.cells).map(c => (c.innerText || '').trim())))",
        )
        chosen_cells, selected_tables = table_company_cells(tables)
        names = unique(chosen_cells)
        body = page.locator("body").inner_text(timeout=30_000)
        hrefs = page.eval_on_selector_all("a[href]", "els => els.map(e => e.getAttribute('href'))")
        attachment_values = parse_attachment(context, source["url"], hrefs, source_index)
        names = unique([*names, *attachment_values])

        # Only use whole-page fallback when no named company column/attachment was usable.
        if not names:
            names = unique(body.splitlines())

        status = "ok" if names else "no_names"
        core.log(
            source["name"], source["url"], status, len(names),
            f"expected_rows={source['expected']}; tables={len(tables)}; selected_tables={selected_tables}; attachments={len(attachment_values)}",
        )
        return names
    except Exception as exc:
        core.log(source["name"], source["url"], "failed", 0, repr(exc))
        return []


def build_chongqing(context: BrowserContext) -> list[dict[str, Any]]:
    page = context.new_page()
    aggregate: dict[str, dict[str, Any]] = {}
    priority = {"直接IT/数字化服务": 3, "智能制造用人企业": 2, "科技型/先进制造潜在IT用人企业": 1}
    for source_index, source in enumerate(core.CQ_SOURCES, 1):
        for name in read_source(page, context, source, source_index):
            key = core.norm_name(name)
            row = aggregate.setdefault(
                key,
                {
                    "region": "重庆", "sample_name": name, "full_name": name, "stock_code": "",
                    "name_basis": "重庆官方名单企业列/附件法人全称", "city": "重庆", "district": "待核实",
                    "sample_level": source["level"], "source_names": [], "source_urls": [],
                    "latest_source_date": "", "official_confirmed": "是",
                },
            )
            row["source_names"].append(source["name"])
            row["source_urls"].append(source["url"])
            row["latest_source_date"] = max(row["latest_source_date"], source["date"])
            if priority.get(source["level"], 0) > priority.get(row["sample_level"], 0):
                row["sample_level"] = source["level"]
    page.close()
    rows = list(aggregate.values())
    for row in rows:
        row["source_names"] = "；".join(sorted(set(row["source_names"])))
        row["source_urls"] = "；".join(sorted(set(row["source_urls"])))
        row["source_count"] = len(row["source_names"].split("；")) if row["source_names"] else 0
    rows.sort(key=lambda item: core.norm_name(item["sample_name"]))
    core.log("重庆35个官方名单按企业列重建去重", "35 official pages and attachments", "ok" if rows else "failed", len(rows), "minimum target=1000; source workbook=1059")
    return rows


def main() -> None:
    core.SOURCE_LOG.clear()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        context = browser.new_context(user_agent=core.UA, locale="zh-CN")
        chongqing = build_chongqing(context)
        outside = old.build_outside(context)
        context.close()
        browser.close()

    companies = chongqing + outside
    for index, row in enumerate(companies, 1):
        row["sample_id"] = index
    summary = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "chongqing_companies": len(chongqing), "outside_companies": len(outside), "total_companies": len(companies),
        "minimum_target": {"重庆": 1000, "重庆外": 1000, "合计": 2000},
        "source_workbook_reference": {"重庆": 1059, "重庆外": 1000, "合计": 2059},
        "method": "按官方表格企业列及附件法人全称抽取；不把项目/产品/工厂名称计作企业",
    }
    old.write_csv(OUT / "company_pool.csv", companies)
    old.write_csv(OUT / "pool_source_log.csv", core.SOURCE_LOG)
    (OUT / "pool_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
