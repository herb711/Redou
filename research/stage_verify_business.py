#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import html
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests

import verify_2059 as core

IN = Path("stage_input")
OUT = Path("stage_output")
OUT.mkdir(exist_ok=True)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


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


def visible_text(value: Any) -> str:
    text = core.clean_text(value)
    text = text.replace("<\\/em>", "</em>").replace("\\u003c", "<").replace("\\u003e", ">")
    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", "", text)
    return core.clean_text(text)


def first(data: dict[str, Any], keys: list[str]) -> str:
    for key in keys:
        value = data.get(key)
        if isinstance(value, (str, int, float)) and visible_text(value):
            return visible_text(value)
    return ""


def direct_aiqicha(name: str) -> dict[str, str]:
    result = {
        "commercial_checked": "是",
        "commercial_match": "否",
        "commercial_name": "",
        "business_status": "",
        "credit_code": "",
        "legal_person": "",
        "registered_address": "",
        "established_date": "",
        "commercial_url": "",
        "commercial_source": "爱企查公共搜索",
        "commercial_note": "",
        "commercial_candidate_count": "0",
    }
    try:
        response = requests.get(
            "https://aiqicha.baidu.com/s/advanceFilterAjax",
            params={"q": name, "p": 1, "s": 10, "f": "{}"},
            headers={
                "User-Agent": core.UA,
                "Referer": "https://aiqicha.baidu.com/",
                "X-Requested-With": "XMLHttpRequest",
            },
            timeout=12,
        )
        if response.status_code != 200:
            result["commercial_note"] = f"HTTP {response.status_code}"
            return result
        payload = response.json()
        candidates = (((payload.get("data") or {}).get("resultList")) or [])
        if not isinstance(candidates, list):
            candidates = []
        result["commercial_candidate_count"] = str(len(candidates))

        exact: list[dict[str, Any]] = []
        target = core.norm_name(visible_text(name))
        for item in candidates:
            if not isinstance(item, dict):
                continue
            candidate_name = first(item, ["entName", "companyName", "titleName", "name", "legalName"])
            if core.norm_name(candidate_name) == target:
                exact.append(item)

        # A single exact legal-name result is required. This avoids accepting a
        # similarly named subsidiary or branch as the requested company.
        if len(exact) != 1:
            sample = "；".join(
                first(item, ["entName", "companyName", "titleName", "name", "legalName"])
                for item in candidates[:3]
                if isinstance(item, dict)
            )
            result["commercial_note"] = f"公开搜索无唯一精确结果；候选数={len(candidates)}；候选示例={sample[:180]}"
            return result

        item = exact[0]
        matched_name = first(item, ["entName", "companyName", "titleName", "name", "legalName"])
        pid = first(item, ["pid", "id"])
        result.update(
            {
                "commercial_match": "是",
                "commercial_name": matched_name,
                "business_status": first(item, ["openStatus", "regStatus", "status", "operatingStatus"]),
                "credit_code": first(item, ["creditCode", "unifiedCode", "socialCreditCode"]),
                "legal_person": first(item, ["legalPerson", "legalPersonName", "legalRepresentative"]),
                "registered_address": first(item, ["regAddr", "regLocation", "address", "registeredAddress"]),
                "established_date": first(item, ["startDate", "estiblishTime", "establishDate", "foundDate"]),
                "commercial_url": "https://aiqicha.baidu.com/company_detail_" + pid if pid else "",
                "commercial_note": "公共搜索企业全称唯一精确匹配（已去除高亮标签）",
            }
        )
        return result
    except Exception as exc:
        result["commercial_checked"] = "否"
        result["commercial_note"] = "访问失败:" + repr(exc)[:160]
        return result


def reader_exact(name: str) -> dict[str, str]:
    result = {"reader_checked": "否", "reader_exact": "否", "reader_note": ""}
    try:
        url = "https://r.jina.ai/http://aiqicha.baidu.com/s?q=" + quote(name)
        response = requests.get(url, headers={"User-Agent": core.UA, "Accept": "text/plain"}, timeout=14)
        result["reader_checked"] = "是"
        normalized_page = core.norm_name(visible_text(response.text))
        if response.status_code == 200 and core.norm_name(name) in normalized_page:
            result["reader_exact"] = "是"
            result["reader_note"] = "爱企查公开页面阅读结果包含企业全称"
        else:
            result["reader_note"] = f"未精确命中/HTTP {response.status_code}"
    except Exception as exc:
        result["reader_note"] = "访问失败:" + repr(exc)[:120]
    return result


def verify(row: dict[str, str]) -> dict[str, Any]:
    name = row.get("full_name") or row.get("sample_name", "")
    result = direct_aiqicha(name)
    if result.get("commercial_match") != "是":
        result.update(reader_exact(name))
    else:
        result.update({"reader_checked": "未需要", "reader_exact": "未需要", "reader_note": ""})

    address = (
        result.get("registered_address")
        or row.get("exchange_registered_address")
        or row.get("exchange_address", "")
    )
    region = row.get("region", "")
    if address:
        location = "一致" if ((region == "重庆" and "重庆" in address) or (region != "重庆" and "重庆" not in address)) else "疑似不一致"
    else:
        location = "地址未取得"

    name_ok = result.get("commercial_match") == "是" or result.get("reader_exact") == "是"
    exchange_ok = bool(row.get("stock_code")) and bool(row.get("exchange_full_name") or row.get("full_name"))
    active = any(word in result.get("business_status", "") for word in ["存续", "在业", "开业", "正常", "迁入"])

    if name_ok and location == "疑似不一致":
        verdict = "名称一致但注册地址疑似不一致"
    elif name_ok:
        verdict = "商查名称一致" + ("且经营状态正常" if active else "") + ("；" + location if location else "")
    elif exchange_ok:
        verdict = "交易所/行情资料确认；商查未匹配或受限"
    elif row.get("official_confirmed"):
        verdict = "政府官方名单确认；商查未匹配或受限"
    else:
        verdict = "待进一步核实"

    return {
        "sample_id": row.get("sample_id"),
        "sample_name": row.get("sample_name"),
        "region": region,
        **result,
        "location_consistency": location,
        "verification_result": verdict,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--shard", type=int, required=True)
    parser.add_argument("--total-shards", type=int, required=True)
    args = parser.parse_args()

    rows = read_csv(IN / "company_pool.csv")
    selected = [row for index, row in enumerate(rows) if index % args.total_shards == args.shard]
    output: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {executor.submit(verify, row): row for row in selected}
        for future in as_completed(futures):
            output.append(future.result())
    output.sort(key=lambda item: int(item.get("sample_id") or 0))

    write_csv(OUT / f"business_verification_{args.shard}.csv", output)
    summary = {
        "shard": args.shard,
        "rows": len(output),
        "commercial_exact": sum(item.get("commercial_match") == "是" for item in output),
        "reader_exact": sum(item.get("reader_exact") == "是" for item in output),
        "commercial_access_failures": sum(item.get("commercial_checked") == "否" for item in output),
        "commercial_zero_candidates": sum(item.get("commercial_candidate_count") == "0" for item in output),
        "suspected_location_mismatch": sum(item.get("location_consistency") == "疑似不一致" for item in output),
    }
    (OUT / f"business_summary_{args.shard}.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
