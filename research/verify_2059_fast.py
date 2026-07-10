#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Circuit-breaker wrapper around verify_2059.py.

It prevents thousands of repeated requests after a public business-information
site starts returning access-control responses. No access-control bypass is used.
"""
from __future__ import annotations

import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

import verify_2059 as core


def access_failure(result: dict) -> bool:
    note = str(result.get("aiqicha_note", ""))
    return any(x in note for x in ["HTTP 403", "HTTP 429", "HTTP 418", "访问失败", "ReadTimeout", "ConnectTimeout"])


def verify_companies_with_breaker(companies: list[dict]) -> None:
    probe_n = min(30, len(companies))
    probe_results = []
    for i in range(probe_n):
        r = core.aiqicha_query(companies[i])
        companies[i].update(r)
        probe_results.append(r)
    failures = sum(access_failure(x) for x in probe_results)
    exacts = sum(x.get("aiqicha_exact_match") in {"是", "近似唯一匹配"} for x in probe_results)
    breaker = failures >= 12 and exacts == 0
    if breaker:
        for c in companies[probe_n:]:
            c.update({
                "aiqicha_checked":"否",
                "aiqicha_exact_match":"否",
                "aiqicha_name":"",
                "business_status":"",
                "credit_code":"",
                "legal_person":"",
                "registered_address":"",
                "established_date":"",
                "aiqicha_url":"",
                "aiqicha_note":"公共商查接口触发访问限制，熔断后未继续请求"
            })
    else:
        with ThreadPoolExecutor(max_workers=3) as ex:
            futs = {ex.submit(core.aiqicha_query, c): i for i, c in enumerate(companies[probe_n:], start=probe_n)}
            for fut in as_completed(futs):
                companies[futs[fut]].update(fut.result())
    # Apply the same consistency rules as the base script.
    for c in companies:
        addr = c.get("registered_address", "") or c.get("exchange_address", "")
        name_ok = c.get("aiqicha_exact_match") in {"是", "近似唯一匹配"}
        if c["region"] == "重庆":
            loc = "一致" if "重庆" in addr else ("疑似不一致" if addr else "地址未取得")
        else:
            loc = "一致" if addr and "重庆" not in addr else ("疑似不一致" if "重庆" in addr else "地址未取得")
        c["location_consistency"] = loc
        c["name_consistency"] = "一致" if name_ok else ("商查未匹配" if c.get("aiqicha_checked") == "是" else "商查未完成")
        active = any(k in c.get("business_status", "") for k in ["存续", "在业", "开业", "正常", "迁入"])
        if name_ok and loc == "一致":
            c["verification_result"] = "一致-商查匹配" + ("且经营正常" if active else "")
        elif c.get("official_confirmed") == "是" and c.get("stock_code"):
            c["verification_result"] = "一致-交易所官方确认；商查" + ("匹配" if name_ok else "未匹配/受限")
        elif c.get("official_confirmed") == "是":
            c["verification_result"] = "官方名单确认；" + ("商查匹配" if name_ok else "商查未匹配/受限")
        else:
            c["verification_result"] = "待核实"
    core.log(
        "爱企查公共搜索批量交叉核验",
        "https://aiqicha.baidu.com/",
        "circuit_break" if breaker else "completed",
        sum(1 for c in companies if c.get("aiqicha_checked") == "是"),
        f"probe_failures={failures}; probe_exact={exacts}; breaker={breaker}; exact_total="
        f"{sum(1 for c in companies if c.get('aiqicha_exact_match') in {'是','近似唯一匹配'})}",
    )


def main() -> None:
    cq = core.build_chongqing_pool()
    outside = core.build_outside_pool()
    companies = cq + outside
    for i, c in enumerate(companies, 1):
        c["sample_id"] = i
    verify_companies_with_breaker(companies)
    core.fetch_51job_current(max_pages=10)
    core.fetch_boss_current(max_pages=4)
    core.parse_historical_jobs()
    jobs = core.match_jobs(companies)
    core.aggregate_jobs(companies, jobs)
    current_jobs = [j for j in jobs if j.get("time_scope") == "当前"]
    summary = {
        "generated_at": core.NOW,
        "reconstructed_chongqing_companies": len(cq),
        "outside_exchange_companies": len(outside),
        "total_companies": len(companies),
        "source_workbook_target": {"重庆": 1059, "重庆外": 1000, "合计": 2059},
        "alignment_note": "重庆池由原表35个官方来源重建；若数量不等于1059，表示网页/附件结构变化，未强行凑数。重庆外为深交所创业板当前快照前1000家（剔除注册地址含重庆）。",
        "aiqicha_checked": sum(c.get("aiqicha_checked") == "是" for c in companies),
        "aiqicha_exact_or_near_matches": sum(c.get("aiqicha_exact_match") in {"是", "近似唯一匹配"} for c in companies),
        "aiqicha_access_limited": sum("访问限制" in c.get("aiqicha_note", "") for c in companies),
        "location_suspected_mismatch": sum(c.get("location_consistency") == "疑似不一致" for c in companies),
        "verification_result_counts": dict(Counter(c.get("verification_result", "") for c in companies)),
        "raw_computer_job_records": len(core.JOBS_RAW),
        "matched_computer_job_records": len(jobs),
        "matched_current_job_records": len(current_jobs),
        "companies_with_current_jobs": sum(c.get("current_job_count", 0) > 0 for c in companies),
        "companies_with_historical_jobs_only": sum(c.get("current_job_count", 0) == 0 and c.get("historical_job_count", 0) > 0 for c in companies),
        "recruitment_status_counts": dict(Counter(c.get("recruitment_verification", "") for c in companies)),
        "current_job_platform_counts": dict(Counter(j.get("source_platform", "") for j in current_jobs)),
        "current_job_category_counts": dict(Counter(j.get("job_category", "") for j in current_jobs)),
        "current_job_city_counts": dict(Counter(j.get("location", "").split("-")[0] for j in current_jobs).most_common(30)),
        "current_education_counts": dict(Counter(j.get("education", "") for j in current_jobs).most_common()),
        "current_experience_counts": dict(Counter(j.get("experience", "") for j in current_jobs).most_common()),
        "current_skill_counts": dict(Counter(s for j in current_jobs for s in j.get("skills", "").split("；") if s).most_common(40)),
        "important_limitation": "爱企查/招聘平台可能因公开接口风控而未返回；未匹配不等于企业不存在或没有招聘。历史招聘记录单独标记，不与当前在招混算。",
    }
    core.write_csv(core.OUT / "company_verification.csv", companies)
    core.write_csv(core.OUT / "computer_jobs_matched.csv", jobs)
    core.write_csv(core.OUT / "source_log.csv", core.SOURCE_LOG)
    (core.OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    core.write_xlsx(core.OUT / "company_verification_and_jobs_raw.xlsx", companies, jobs, summary)
    (core.OUT / "README.md").write_text(
        "# 2059家企业真实性与计算机招聘核验\n\n" +
        f"- 重庆官方来源重建：{len(cq)}家（原表目标1059）\n" +
        f"- 重庆外交易所样本：{len(outside)}家（目标1000）\n" +
        f"- 爱企查实际请求：{summary['aiqicha_checked']}家；精确/唯一近似匹配：{summary['aiqicha_exact_or_near_matches']}家；访问限制熔断：{summary['aiqicha_access_limited']}家\n" +
        f"- 匹配当前计算机岗位：{summary['matched_current_job_records']}条，涉及{summary['companies_with_current_jobs']}家企业\n\n" +
        "未匹配表示本次公开快照未找到，不等于企业不存在或没有招聘。\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
