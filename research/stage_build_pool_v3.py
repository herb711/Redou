#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from playwright.sync_api import sync_playwright

import stage_build_pool_v2 as cq_parser
import verify_2059 as core

OUT = Path("stage_output")
OUT.mkdir(exist_ok=True)

CQ_GEM_CODES = {"300006", "300122", "300194", "300275", "300363"}
GEM_RAW_URL = (
    "https://raw.githubusercontent.com/khscience/OSkhQuant/"
    "7228f55741b445cb25116683e5753f82a5422825/"
    "data/%E5%88%9B%E4%B8%9A%E6%9D%BF_%E8%82%A1%E7%A5%A8%E5%88%97%E8%A1%A8.csv"
)


def build_outside_raw() -> list[dict[str, Any]]:
    response = requests.get(GEM_RAW_URL, headers={"User-Agent": core.UA}, timeout=90)
    response.raise_for_status()
    rows: list[dict[str, Any]] = []
    for record in csv.reader(response.text.lstrip("\ufeff").splitlines()):
        if len(record) < 2:
            continue
        code = core.clean_text(record[0]).split(".")[0].zfill(6)
        short = core.clean_text(record[1])
        if not re.fullmatch(r"30\d{4}", code) or not short or code in CQ_GEM_CODES:
            continue
        rows.append({
            "region": "重庆外",
            "sample_name": short,
            "full_name": short,
            "stock_code": code,
            "name_basis": "创业板证券代码与证券简称",
            "city": "待核实",
            "district": "",
            "sample_level": "创业板上市公司样本",
            "source_names": "现行创业板证券代码/简称清单",
            "source_urls": GEM_RAW_URL,
            "source_count": 1,
            "latest_source_date": "2026-07-10",
            "official_confirmed": "是-上市证券清单存在",
        })
    rows.sort(key=lambda row: row["stock_code"])
    rows = rows[:1000]
    core.log(
        "创业板证券代码/简称清单",
        GEM_RAW_URL,
        "ok" if len(rows) == 1000 else "partial",
        len(rows),
        "剔除300006、300122、300194、300275、300363后按证券代码取前1000",
    )
    return rows


def main() -> None:
    core.SOURCE_LOG.clear()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = browser.new_context(user_agent=core.UA, locale="zh-CN")
        chongqing = cq_parser.build_chongqing(context)
        context.close()
        browser.close()
    outside = build_outside_raw()

    companies = chongqing + outside
    for index, row in enumerate(companies, 1):
        row["sample_id"] = index
    summary = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "chongqing_companies": len(chongqing),
        "outside_companies": len(outside),
        "total_companies": len(companies),
        "minimum_target": {"重庆": 1000, "重庆外": 1000, "合计": 2000},
        "source_workbook_reference": {"重庆": 1059, "重庆外": 1000, "合计": 2059},
        "difference_from_source_workbook": {
            "重庆": len(chongqing) - 1059,
            "重庆外": len(outside) - 1000,
            "合计": len(companies) - 2059,
        },
        "method": "Playwright按35个重庆官方页面表格企业列及附件主体全称提取；外地按原表记录的创业板原始CSV剔除5个重庆代码后取1000",
    }
    cq_parser.old.write_csv(OUT / "company_pool.csv", companies)
    cq_parser.old.write_csv(OUT / "pool_source_log.csv", core.SOURCE_LOG)
    (OUT / "pool_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
