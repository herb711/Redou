#!/usr/bin/env python3
from __future__ import annotations

import csv
import io
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urljoin, urlparse

import pandas as pd
from playwright.sync_api import BrowserContext, Page, sync_playwright

import verify_2059 as core
import verify_2059_browser as helper

OUT = Path("stage_output")
OUT.mkdir(exist_ok=True)
WORK = Path("stage_pool_work")
WORK.mkdir(exist_ok=True)

# The source workbook states that five Chongqing-registered GEM companies were
# removed from the initial exchange-ordered sample before taking 1,000 outside
# companies. These are the five Chongqing registrants occurring before the
# source sample's cut-off point in security-code order.
CQ_GEM_CODES = {"300006", "300122", "300194", "300275", "300363"}

BAD_TEXT = {
    "企业名称", "单位名称", "公司名称", "申报单位", "建设单位", "牵头单位",
    "服务商名称", "供应方", "序号", "名单", "附件", "项目名称", "产品名称",
}
PREFIX_RE = re.compile(r"^(?:序号)?\s*(?:\d+(?:\.\d+)?|[一二三四五六七八九十百]+)[、.．)）\-]?\s*")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        if not fields:
            f.write("")
            return
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def unique(values: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        value = core.clean_text(value).strip("*#|，。；;、:：[]【】")
        value = PREFIX_RE.sub("", value)
        value = re.sub(
            r"^(?:申报单位|建设单位|牵头单位|依托单位|使用单位|供应方|服务商名称|企业名称|单位名称|公司名称)[:：]?",
            "",
            value,
        ).strip()
        key = core.norm_name(value)
        if not key or key in seen:
            continue
        if any(value == bad or value.startswith(bad + "：") for bad in BAD_TEXT):
            continue
        if helper.is_subject(value) or core.valid_company_name(value):
            seen.add(key)
            out.append(value)
    return out


def extract_names(cells: list[str], body_text: str, expected: int) -> list[str]:
    # Table cells are much less likely than whole-page lines to contain prose.
    cell_names = unique(cells)
    line_names = unique(body_text.splitlines())
    names = unique([*cell_names, *line_names])

    # Recover legal subjects embedded inside a cell, e.g. “1 重庆××有限公司”.
    embedded: list[str] = []
    for text in [*cells, *body_text.splitlines()]:
        cleaned = core.clean_text(text)
        for match in helper.LEGAL_RE.finditer(cleaned):
            embedded.append(match.group(0))
    names = unique([*names, *embedded])

    # The official source gives an expected row count. It is used only as a
    # precision guard against footer/news-link contamination, never to invent rows.
    if expected and len(names) > expected + 8:
        names = names[:expected]
    return names


def attachment_names(context: BrowserContext, page_url: str, hrefs: list[str], source_index: int) -> list[str]:
    names: list[str] = []
    attach_dir = WORK / "attachments" / f"{source_index:02d}"
    attach_dir.mkdir(parents=True, exist_ok=True)
    for index, href in enumerate(dict.fromkeys(hrefs)):
        absolute = urljoin(page_url, href)
        path_part = urlparse(absolute).path
        match = re.search(r"\.(xlsx|xlsm|xls|docx|doc|pdf|csv|txt)$", path_part, re.I)
        if not match:
            continue
        try:
            response = context.request.get(absolute, timeout=90_000)
            if not response.ok:
                core.log("official attachment", absolute, f"HTTP {response.status}", 0)
                continue
            ext = "." + match.group(1).lower()
            target = attach_dir / f"attachment_{index:02d}{ext}"
            target.write_bytes(response.body())
            text = core.attachment_text(target)
            names.extend(core.extract_company_names(text))
        except Exception as exc:
            core.log("official attachment", absolute, "failed", 0, repr(exc))
    return unique(names)


def read_official_source(page: Page, context: BrowserContext, src: dict[str, Any], source_index: int) -> list[str]:
    try:
        page.goto(src["url"], wait_until="domcontentloaded", timeout=90_000)
        page.wait_for_timeout(1_500)
        body_text = page.locator("body").inner_text(timeout=30_000)
        try:
            cells = page.locator("td, th").all_inner_texts()
        except Exception:
            cells = []
        names = extract_names(cells, body_text, int(src["expected"]))
        hrefs = page.eval_on_selector_all("a[href]", "els => els.map(e => e.getAttribute('href'))")
        names = unique([*names, *attachment_names(context, src["url"], hrefs, source_index)])
        if src["expected"] and len(names) > int(src["expected"]) + 8:
            names = names[: int(src["expected"])]
        core.log(
            src["name"],
            src["url"],
            "ok" if names else "no_names",
            len(names),
            f"expected={src['expected']}; table_cells={len(cells)}; browser=chromium",
        )
        return names
    except Exception as exc:
        core.log(src["name"], src["url"], "failed", 0, repr(exc))
        return []


def build_chongqing(context: BrowserContext) -> list[dict[str, Any]]:
    page = context.new_page()
    aggregate: dict[str, dict[str, Any]] = {}
    priority = {"直接IT/数字化服务": 3, "智能制造用人企业": 2, "科技型/先进制造潜在IT用人企业": 1}
    for source_index, src in enumerate(core.CQ_SOURCES, 1):
        for name in read_official_source(page, context, src, source_index):
            key = core.norm_name(name)
            row = aggregate.setdefault(
                key,
                {
                    "region": "重庆",
                    "sample_name": name,
                    "full_name": name,
                    "stock_code": "",
                    "name_basis": "重庆官方名单主体全称",
                    "city": "重庆",
                    "district": "待核实",
                    "sample_level": src["level"],
                    "source_names": [],
                    "source_urls": [],
                    "latest_source_date": "",
                    "official_confirmed": "是",
                },
            )
            row["source_names"].append(src["name"])
            row["source_urls"].append(src["url"])
            row["latest_source_date"] = max(row["latest_source_date"], src["date"])
            if priority.get(src["level"], 0) > priority.get(row["sample_level"], 0):
                row["sample_level"] = src["level"]
    page.close()
    rows = list(aggregate.values())
    for row in rows:
        row["source_names"] = "；".join(sorted(set(row["source_names"])))
        row["source_urls"] = "；".join(sorted(set(row["source_urls"])))
        row["source_count"] = len(row["source_names"].split("；")) if row["source_names"] else 0
    rows.sort(key=lambda x: core.norm_name(x["sample_name"]))
    core.log("重庆35个官方名单浏览器重建去重", "35 official pages and attachments", "ok" if rows else "failed", len(rows), "source workbook target=1059")
    return rows


def parse_szse_xlsx(content: bytes) -> list[dict[str, Any]]:
    frame = pd.read_excel(io.BytesIO(content), dtype=str)
    frame.columns = [core.clean_text(column) for column in frame.columns]
    code_col = next((c for c in frame.columns if "A股代码" in c or c == "证券代码"), "")
    short_col = next((c for c in frame.columns if "A股简称" in c or c == "证券简称"), "")
    industry_col = next((c for c in frame.columns if "所属行业" in c or c == "行业"), "")
    if not code_col or not short_col:
        raise ValueError(f"SZSE workbook columns not recognized: {list(frame.columns)}")
    rows: list[dict[str, Any]] = []
    for _, record in frame.iterrows():
        code = core.clean_text(record.get(code_col, "")).split(".")[0].zfill(6)
        short = core.clean_text(record.get(short_col, ""))
        if not re.fullmatch(r"30\d{4}", code) or not short or code in CQ_GEM_CODES:
            continue
        rows.append(
            {
                "region": "重庆外",
                "sample_name": short,
                "full_name": short,
                "stock_code": code,
                "name_basis": "深交所证券代码与简称",
                "city": "待核实",
                "district": "",
                "sample_level": "创业板上市公司样本",
                "source_names": "深圳证券交易所A股列表",
                "source_urls": "https://www.szse.cn/api/report/ShowReport",
                "source_count": 1,
                "latest_source_date": datetime.now().date().isoformat(),
                "official_confirmed": "是-交易所证券存在",
                "exchange_industry": core.clean_text(record.get(industry_col, "")),
            }
        )
    rows.sort(key=lambda x: x["stock_code"])
    return rows[:1000]


def parse_wikipedia_gem(page: Page) -> list[dict[str, Any]]:
    url = "https://zh.wikipedia.org/wiki/深圳证券交易所创业板上市公司列表"
    page.goto(url, wait_until="domcontentloaded", timeout=90_000)
    text = page.locator("body").inner_text(timeout=30_000)
    rows: list[dict[str, Any]] = []
    pattern = re.compile(
        r"^(30\d{4})\s+(\S+)\s+(.+?(?:集团股份有限公司|股份有限公司|有限责任公司|有限公司|股份公司))\s+\1\s+\S+\s+\d{4}年\d{1,2}月\d{1,2}日\s+(.+)$"
    )
    for line in text.splitlines():
        match = pattern.match(core.clean_text(line))
        if not match:
            continue
        code, short, full, registered = match.groups()
        if code in CQ_GEM_CODES or "重庆" in registered:
            continue
        rows.append(
            {
                "region": "重庆外",
                "sample_name": short,
                "full_name": full,
                "stock_code": code,
                "name_basis": "公开创业板列表中的证券简称与公司全称",
                "city": registered,
                "district": "",
                "sample_level": "创业板上市公司样本",
                "source_names": "创业板上市公司公开列表（深交所清单失败时的交叉来源）",
                "source_urls": url,
                "source_count": 1,
                "latest_source_date": datetime.now().date().isoformat(),
                "official_confirmed": "是-上市证券公开记录",
                "exchange_address": registered,
            }
        )
    rows.sort(key=lambda x: x["stock_code"])
    return rows[:1000]


def build_outside(context: BrowserContext) -> list[dict[str, Any]]:
    api = "https://www.szse.cn/api/report/ShowReport?SHOWTYPE=xlsx&CATALOGID=1110&TABKEY=tab1&random=0.6180339887"
    try:
        response = context.request.get(
            api,
            timeout=90_000,
            headers={"Referer": "https://www.szse.cn/market/product/stock/list/index.html", "User-Agent": core.UA},
        )
        if not response.ok:
            raise RuntimeError(f"HTTP {response.status}")
        rows = parse_szse_xlsx(response.body())
        if len(rows) < 1000:
            raise RuntimeError(f"only {len(rows)} qualifying rows")
        core.log("深圳证券交易所创业板样本", api, "ok", len(rows), "excluded source-workbook Chongqing registrants")
        return rows
    except Exception as exc:
        core.log("深圳证券交易所创业板样本", api, "failed", 0, repr(exc))
        page = context.new_page()
        try:
            rows = parse_wikipedia_gem(page)
            core.log("创业板公开列表备用来源", "https://zh.wikipedia.org/wiki/深圳证券交易所创业板上市公司列表", "ok" if len(rows) == 1000 else "partial", len(rows))
            return rows
        finally:
            page.close()


def main() -> None:
    core.SOURCE_LOG.clear()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        context = browser.new_context(user_agent=core.UA, locale="zh-CN")
        cq = build_chongqing(context)
        outside = build_outside(context)
        context.close()
        browser.close()

    companies = cq + outside
    for index, row in enumerate(companies, 1):
        row["sample_id"] = index
    summary = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "chongqing_companies": len(cq),
        "outside_companies": len(outside),
        "total_companies": len(companies),
        "target": {"重庆": 1059, "重庆外": 1000, "合计": 2059},
        "difference": {"重庆": len(cq) - 1059, "重庆外": len(outside) - 1000, "合计": len(companies) - 2059},
        "method": "Chromium读取重庆35个官方页面及附件；深交所A股列表筛选创业板",
    }
    write_csv(OUT / "company_pool.csv", companies)
    write_csv(OUT / "pool_source_log.csv", core.SOURCE_LOG)
    (OUT / "pool_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
