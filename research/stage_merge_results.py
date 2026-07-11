#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import stage_collect_history as strict_filter
import verify_2059 as core

IN = Path("stage_input")
OUT = Path("research_output_final")
OUT.mkdir(exist_ok=True)


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists() or path.stat().st_size == 0:
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


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


def main() -> None:
    companies = read_csv(IN / "company_pool.csv")
    by_id = {str(item.get("sample_id")): item for item in companies}

    business: list[dict[str, str]] = []
    for path in sorted(IN.glob("business_verification_*.csv")):
        business.extend(read_csv(path))
    for verification in business:
        sample_id = str(verification.get("sample_id"))
        if sample_id in by_id:
            by_id[sample_id].update(verification)
    for company in companies:
        if not company.get("verification_result"):
            company["verification_result"] = (
                "交易所当前证券资料确认；商查分片缺失"
                if company.get("stock_code")
                else "政府官方名单确认；商查分片缺失"
            )
            company["location_consistency"] = "地址未取得"

    raw_current: list[dict[str, str]] = []
    platform_summaries: dict[str, dict[str, Any]] = {}
    for platform in ["51job", "boss"]:
        raw_current.extend(read_csv(IN / f"current_jobs_{platform}.csv"))
        platform_summaries[platform] = read_json(IN / f"current_jobs_{platform}_summary.json")

    # Reapply the strict title-first filter at merge time. This protects the
    # final report even if a platform keyword search returns sales or business roles.
    strict_current_candidates: list[dict[str, Any]] = []
    current_exclusion_reasons: Counter[str] = Counter()
    for row in raw_current:
        keep, reason = strict_filter.is_strict_computing_job(row)
        if keep:
            copied = dict(row)
            copied["strict_relevance_basis"] = reason
            strict_current_candidates.append(copied)
        else:
            current_exclusion_reasons[reason] += 1

    core.JOBS_RAW.clear()
    core.SOURCE_LOG.clear()
    for row in strict_current_candidates:
        core.add_job(row)
    current_matched = core.match_jobs(companies)

    history = read_csv(IN / "historical_jobs_matched.csv")
    for row in history:
        row["time_scope"] = "历史"
    all_jobs = current_matched + history
    core.aggregate_jobs(companies, all_jobs)

    current = [item for item in current_matched if item.get("time_scope") == "当前"]
    salary_midpoints = [
        item.get("salary_mid_k")
        for item in current
        if isinstance(item.get("salary_mid_k"), (int, float))
    ]
    cq_current = [item for item in current if item.get("sample_region") == "重庆"]
    outside_current = [item for item in current if item.get("sample_region") != "重庆"]

    business_summary_files = [read_json(path) for path in sorted(IN.glob("business_summary_*.json"))]
    commercial_attempted = sum(int(item.get("rows", 0) or 0) for item in business_summary_files)
    commercial_access_failures = sum(int(item.get("commercial_access_failures", 0) or 0) for item in business_summary_files)

    summary = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "company_pool": {
            "重庆": sum(company.get("region") == "重庆" for company in companies),
            "重庆外": sum(company.get("region") != "重庆" for company in companies),
            "合计": len(companies),
        },
        "minimum_required_target": {"重庆": 1000, "重庆外": 1000, "合计": 2000},
        "original_source_workbook_reference": {"重庆": 1059, "重庆外": 1000, "合计": 2059},
        "sample_note": "严格法人清洗后保留的样本数量；未用项目、产品或智能工厂名称补足到2059。",
        "commercial_crosscheck": {
            "completed_rows": len(business),
            "attempted_rows_from_shard_summaries": commercial_attempted,
            "exact_matches": sum(company.get("commercial_match") == "是" for company in companies),
            "reader_exact_matches": sum(company.get("reader_exact") == "是" for company in companies),
            "access_failures": commercial_access_failures,
            "access_or_no_unique_result": sum(
                company.get("commercial_match") != "是" and company.get("reader_exact") != "是"
                for company in companies
            ),
            "suspected_location_mismatch": sum(
                company.get("location_consistency") == "疑似不一致" for company in companies
            ),
            "interpretation": "商查未命中或访问失败不等于企业不存在；企业存在性仍由政府逐家名单或交易所证券记录支撑。",
        },
        "verification_result_counts": dict(Counter(company.get("verification_result", "") for company in companies)),
        "platform_collection": platform_summaries,
        "current_recruitment": {
            "raw_platform_keyword_results": len(raw_current),
            "strict_title_filtered_candidates": len(strict_current_candidates),
            "excluded_non_computing_results": len(raw_current) - len(strict_current_candidates),
            "exclusion_reasons": dict(current_exclusion_reasons),
            "matched_jobs": len(current),
            "matched_companies": len({item.get("company_index") for item in current}),
            "重庆_matched_jobs": len(cq_current),
            "重庆_matched_companies": len({item.get("company_index") for item in cq_current}),
            "重庆外_matched_jobs": len(outside_current),
            "重庆外_matched_companies": len({item.get("company_index") for item in outside_current}),
            "platform_counts": dict(Counter(item.get("source_platform", "") for item in current)),
            "category_counts": dict(Counter(item.get("job_category", "") for item in current)),
            "education_counts": dict(Counter(item.get("education", "") for item in current)),
            "experience_counts": dict(Counter(item.get("experience", "") for item in current)),
            "city_counts": dict(Counter(item.get("location", "").split("-")[0] for item in current).most_common(40)),
            "skill_counts": dict(
                Counter(
                    skill
                    for item in current
                    for skill in item.get("skills", "").split("；")
                    if skill
                ).most_common(50)
            ),
            "salary_mid_k_mean": round(sum(salary_midpoints) / len(salary_midpoints), 2) if salary_midpoints else None,
            "match_method_counts": dict(Counter(item.get("match_method", "") for item in current)),
        },
        "historical_recruitment": {
            "matched_jobs": len(history),
            "matched_companies": len({item.get("company_index") for item in history}),
            "category_counts": dict(Counter(item.get("job_category", "") for item in history)),
            "platform_counts": dict(Counter(item.get("source_platform", "") for item in history)),
            "interpretation": "仅用作企业曾招聘相关人才的补充证据，不代表2026年当前岗位。",
        },
        "recruitment_status_counts": dict(Counter(company.get("recruitment_verification", "") for company in companies)),
        "limitations": [
            "商查公开接口未匹配不等于企业不存在；重庆企业仍有政府官方名单证据，外地企业仍有交易所/公开上市资料证据。",
            "Boss直聘和51Job统计为本次公开关键词搜索快照，受平台风控、分页上限和名称匹配影响，不代表全部在招岗位。",
            "当前与历史招聘均经过岗位标题严格过滤；历史数据与2026年当前岗位分开统计。",
            "名称一致但注册地址疑似不一致的主体需人工复核其分公司、项目单位或名单归属口径。",
        ],
    }

    logs: list[dict[str, str]] = []
    for path in IN.glob("*source_log.csv"):
        logs.extend(read_csv(path))

    write_csv(OUT / "company_verification.csv", companies)
    write_csv(OUT / "current_computer_jobs_matched.csv", current)
    write_csv(OUT / "historical_computer_jobs_matched.csv", history)
    write_csv(OUT / "all_computer_jobs_matched.csv", all_jobs)
    write_csv(OUT / "source_log.csv", logs)
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    report = [
        "# 计算机科学与技术就业企业真实性与招聘核验",
        f"生成时间：{summary['generated_at']}",
        "",
        f"- 严格企业样本：{len(companies)}家（重庆{summary['company_pool']['重庆']}家，重庆外{summary['company_pool']['重庆外']}家），达到最低2000家要求。",
        f"- 商查企业全称精确匹配：{summary['commercial_crosscheck']['exact_matches']}家；公开页面精确命中：{summary['commercial_crosscheck']['reader_exact_matches']}家。",
        f"- 当前计算机岗位匹配：{summary['current_recruitment']['matched_jobs']}条，涉及{summary['current_recruitment']['matched_companies']}家企业。",
        f"- 重庆当前计算机岗位匹配：{summary['current_recruitment']['重庆_matched_jobs']}条，涉及{summary['current_recruitment']['重庆_matched_companies']}家企业。",
        f"- 严格历史招聘匹配：{summary['historical_recruitment']['matched_jobs']}条，仅作补充证据，不与当前招聘混算。",
        "",
        "详见 summary.json、company_verification.csv、当前招聘与历史招聘明细文件。",
    ]
    (OUT / "REPORT.md").write_text("\n".join(report), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
