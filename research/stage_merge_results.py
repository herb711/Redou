#!/usr/bin/env python3
from __future__ import annotations
import csv, glob, json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any
import verify_2059 as core

IN=Path("stage_input"); OUT=Path("research_output_final"); OUT.mkdir(exist_ok=True)


def read_csv(path: Path) -> list[dict[str,str]]:
    if not path.exists() or path.stat().st_size==0: return []
    with path.open("r",encoding="utf-8-sig",newline="") as f: return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict[str,Any]]) -> None:
    fields=[]
    for row in rows:
        for k in row:
            if k not in fields: fields.append(k)
    with path.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)


def main() -> None:
    companies=read_csv(IN/"company_pool.csv")
    by_id={str(x.get("sample_id")):x for x in companies}
    business=[]
    for p in sorted(IN.glob("business_verification_*.csv")):
        business.extend(read_csv(p))
    for v in business:
        if str(v.get("sample_id")) in by_id: by_id[str(v["sample_id"])].update(v)
    for c in companies:
        if not c.get("verification_result"):
            c["verification_result"]="交易所当前证券资料确认；商查分片缺失" if c.get("stock_code") else "政府官方名单确认；商查分片缺失"
            c["location_consistency"]="地址未取得"
    core.JOBS_RAW.clear(); core.SOURCE_LOG.clear()
    raw_current=[]
    for p in [IN/"current_jobs_51job.csv",IN/"current_jobs_boss.csv"]:
        raw_current.extend(read_csv(p))
    for row in raw_current: core.add_job(row)
    current_matched=core.match_jobs(companies)
    history=read_csv(IN/"historical_jobs_matched.csv")
    for row in history: row["time_scope"]="历史"
    all_jobs=current_matched+history
    core.aggregate_jobs(companies,all_jobs)
    current=[x for x in current_matched if x.get("time_scope")=="当前"]
    mids=[x.get("salary_mid_k") for x in current if isinstance(x.get("salary_mid_k"),(int,float))]
    cq_current=[x for x in current if x.get("sample_region")=="重庆"]
    outside_current=[x for x in current if x.get("sample_region")!="重庆"]
    summary={
        "generated_at":datetime.now().isoformat(timespec="seconds"),
        "company_pool":{"重庆":sum(c.get("region")=="重庆" for c in companies),"重庆外":sum(c.get("region")!="重庆" for c in companies),"合计":len(companies)},
        "target":{"重庆":1059,"重庆外":1000,"合计":2059},
        "commercial_crosscheck":{"completed_rows":len(business),"exact_matches":sum(c.get("commercial_match")=="是" for c in companies),"reader_exact_matches":sum(c.get("reader_exact")=="是" for c in companies),"access_or_no_unique_result":sum(c.get("commercial_match")!="是" and c.get("reader_exact")!="是" for c in companies),"suspected_location_mismatch":sum(c.get("location_consistency")=="疑似不一致" for c in companies)},
        "verification_result_counts":dict(Counter(c.get("verification_result","") for c in companies)),
        "current_recruitment":{"raw_tech_jobs":len(raw_current),"matched_jobs":len(current),"matched_companies":len({x.get('company_index') for x in current}),"重庆_matched_jobs":len(cq_current),"重庆_matched_companies":len({x.get('company_index') for x in cq_current}),"重庆外_matched_jobs":len(outside_current),"重庆外_matched_companies":len({x.get('company_index') for x in outside_current}),"platform_counts":dict(Counter(x.get('source_platform','') for x in current)),"category_counts":dict(Counter(x.get('job_category','') for x in current)),"education_counts":dict(Counter(x.get('education','') for x in current)),"experience_counts":dict(Counter(x.get('experience','') for x in current)),"city_counts":dict(Counter(x.get('location','').split('-')[0] for x in current).most_common(40)),"skill_counts":dict(Counter(s for x in current for s in x.get('skills','').split('；') if s).most_common(50)),"salary_mid_k_mean":round(sum(mids)/len(mids),2) if mids else None},
        "historical_recruitment":{"matched_jobs":len(history),"matched_companies":len({x.get('company_index') for x in history})},
        "recruitment_status_counts":dict(Counter(c.get("recruitment_verification","") for c in companies)),
        "limitations":["商查公开接口未匹配不等于企业不存在；重庆企业仍有政府官方名单证据，外地企业仍有交易所/行情资料证据。","Boss直聘和51Job统计为本次公开关键词搜索快照，受平台风控、分页上限和名称匹配影响，不代表全部在招岗位。","历史招聘数据与2026年当前岗位严格分开统计。","名称一致但注册地址疑似不一致的主体需人工复核其分公司、项目单位或名单归属口径。"]
    }
    logs=[]
    for p in IN.glob("*source_log.csv"): logs.extend(read_csv(p))
    write_csv(OUT/"company_verification.csv",companies)
    write_csv(OUT/"current_computer_jobs_matched.csv",current)
    write_csv(OUT/"historical_computer_jobs_matched.csv",history)
    write_csv(OUT/"all_computer_jobs_matched.csv",all_jobs)
    write_csv(OUT/"source_log.csv",logs)
    (OUT/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    report=["# 计算机科学与技术就业企业真实性与招聘核验",f"生成时间：{summary['generated_at']}","",f"- 企业池：{len(companies)}家（重庆{summary['company_pool']['重庆']}家，重庆外{summary['company_pool']['重庆外']}家）",f"- 商查精确匹配：{summary['commercial_crosscheck']['exact_matches']}家；公开页面精确命中：{summary['commercial_crosscheck']['reader_exact_matches']}家",f"- 当前计算机岗位匹配：{summary['current_recruitment']['matched_jobs']}条，涉及{summary['current_recruitment']['matched_companies']}家企业",f"- 重庆当前计算机岗位匹配：{summary['current_recruitment']['重庆_matched_jobs']}条，涉及{summary['current_recruitment']['重庆_matched_companies']}家企业",f"- 历史招聘匹配：{summary['historical_recruitment']['matched_jobs']}条，仅作补充证据，不与当前招聘混算","","详见 summary.json、company_verification.csv 和招聘明细文件。"]
    (OUT/"REPORT.md").write_text("\n".join(report),encoding="utf-8")
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=="__main__": main()
