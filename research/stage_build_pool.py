#!/usr/bin/env python3
from __future__ import annotations
import csv, json, re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any
import requests
import verify_2059 as core
import verify_2059_browser as browser

OUT = Path("stage_output"); OUT.mkdir(exist_ok=True)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields=[]
    for row in rows:
        for key in row:
            if key not in fields: fields.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w=csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(rows)


def enrich(c: dict[str, Any]) -> dict[str, str]:
    code=c.get("stock_code", "")
    result={"exchange_full_name":"","exchange_registered_address":"","exchange_established_date":"","exchange_legal_person":"","exchange_business":"","exchange_profile_status":"未取得"}
    if not code: return result
    url="https://emweb.securities.eastmoney.com/PC_HSF10/CompanySurvey/PageAjax"
    try:
        r=requests.get(url, params={"code":"SZ"+code}, headers={"User-Agent":core.UA,"Referer":"https://emweb.securities.eastmoney.com/"}, timeout=8)
        r.raise_for_status(); data=r.json(); rows=data.get("jbzl") or data.get("JBZL") or []
        if isinstance(rows, dict): rows=[rows]
        if not rows: return result
        x=rows[0]
        def pick(*keys: str) -> str:
            for k in keys:
                v=core.clean_text(x.get(k))
                if v: return v
            return ""
        result.update({
            "exchange_full_name":pick("ORG_NAME","COMPANY_NAME","SECURITY_NAME_ABBR"),
            "exchange_registered_address":pick("REG_ADDRESS","REGISTERED_ADDRESS"),
            "exchange_established_date":pick("FOUND_DATE","ESTABLISH_DATE"),
            "exchange_legal_person":pick("LEGAL_PERSON","LEGAL_REPRESENTATIVE"),
            "exchange_business":pick("BUSINESS_SCOPE","MAIN_BUSINESS"),
            "exchange_profile_status":"已取得",
        })
    except Exception as exc:
        result["exchange_profile_status"]="访问失败:"+repr(exc)[:100]
    return result


def main() -> None:
    core.SOURCE_LOG.clear()
    cq=browser.build_chongqing_reader()
    outside=browser.eastmoney_list()
    with ThreadPoolExecutor(max_workers=24) as ex:
        futs={ex.submit(enrich, row):i for i,row in enumerate(outside)}
        for fut in as_completed(futs): outside[futs[fut]].update(fut.result())
    for row in outside:
        row["official_confirmed"]="是"
        if row.get("exchange_full_name"): row["full_name"]=row["exchange_full_name"]
        row["exchange_address"]=row.get("exchange_registered_address", "")
    companies=cq+outside
    for i,row in enumerate(companies,1): row["sample_id"]=i
    summary={
        "generated_at":datetime.now().isoformat(timespec="seconds"),
        "chongqing_companies":len(cq),"outside_companies":len(outside),"total_companies":len(companies),
        "target":{"重庆":1059,"重庆外":1000,"合计":2059},
        "difference":{"重庆":len(cq)-1059,"重庆外":len(outside)-1000,"合计":len(companies)-2059},
        "outside_profiles_obtained":sum(x.get("exchange_profile_status")=="已取得" for x in outside),
    }
    write_csv(OUT/"company_pool.csv", companies)
    write_csv(OUT/"pool_source_log.csv", core.SOURCE_LOG)
    (OUT/"pool_summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=="__main__": main()
