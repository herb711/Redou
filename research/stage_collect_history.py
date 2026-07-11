#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

import verify_2059 as core

IN = Path("stage_input")
OUT = Path("stage_output")
OUT.mkdir(exist_ok=True)

# Strong technical terms may qualify directly from the job title. Broader terms
# such as product/project/implementation must also be supported by IT context.
STRONG_TITLE_TERMS = [
    "软件", "开发", "程序员", "程序设计", "算法", "数据分析", "数据开发", "数据工程", "大数据",
    "测试工程师", "软件测试", "自动化测试", "运维", "网络工程", "网络安全", "信息安全", "系统工程师",
    "信息化", "前端", "后端", "全栈", "java", "python", "c++", "c#", ".net", "php", "golang", "go工程师",
    "android", "ios", "客户端", "嵌入式", "单片机", "驱动工程师", "硬件工程师", "芯片", "集成电路",
    "数据库", "dba", "云计算", "云平台", "人工智能", "机器学习", "深度学习", "计算机视觉", "图像算法",
    "nlp", "大模型", "web工程师", "网页开发", "游戏开发", "游戏程序", "物联网", "fpga", "arm", "linux",
    "鸿蒙", "harmony", "车载软件", "autosar", "智能座舱", "机器人软件", "gis", "bi工程师", "架构师",
    "plc工程师", "mes工程师", "erp开发", "sap开发", "通信工程师", "电子工程师", "自动化工程师",
    "计算机教师", "计算机讲师", "软件讲师", "java讲师", "网络讲师",
]
CONTEXTUAL_TITLE_TERMS = [
    "产品经理", "项目经理", "实施工程师", "实施顾问", "技术支持", "技术服务", "售前工程师",
    "解决方案工程师", "应用工程师", "系统管理员", "信息管理员", "研发工程师",
]
IT_CONTEXT_TERMS = [
    "计算机", "软件", "互联网", "it服务", "信息技术", "信息系统", "数字化", "网络", "通信", "电子",
    "半导体", "集成电路", "物联网", "人工智能", "大数据", "云计算", "数据库", "工业互联网", "自动化",
    "mes", "erp", "sap", "平台", "系统集成", "智能制造", "车联网", "智能汽车",
]
EXCLUDE_TITLE_TERMS = [
    "销售", "客户经理", "大客户", "商务", "市场", "渠道", "招商主管", "招商经理", "电话客服",
    "运营专员", "运营经理", "行政", "人事", "招聘专员", "会计", "财务", "法务", "采购", "仓库",
    "物流", "物业", "施工", "土建", "暖通", "结构工程", "机械设计", "工艺工程", "品质工程",
    "生产主管", "生产经理", "医生", "护士", "药师", "平面设计", "室内设计", "建筑设计",
]


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


def lower(value: Any) -> str:
    return core.clean_text(value).lower()


def is_strict_computing_job(job: dict[str, Any]) -> tuple[bool, str]:
    title = lower(job.get("job_title"))
    industry = lower(job.get("industry"))
    description = lower(job.get("job_desc"))[:1500]
    context = " ".join([title, industry, description])

    if not title:
        return False, "无岗位名称"
    if any(term.lower() in title for term in EXCLUDE_TITLE_TERMS):
        return False, "标题含非计算机岗位排除词"
    if any(term.lower() in title for term in STRONG_TITLE_TERMS):
        return True, "岗位标题直接技术匹配"
    if any(term.lower() in title for term in CONTEXTUAL_TITLE_TERMS) and any(term.lower() in context for term in IT_CONTEXT_TERMS):
        return True, "岗位标题与IT行业/职责联合匹配"
    return False, "岗位标题不足以证明计算机相关"


def main() -> None:
    companies = read_csv(IN / "company_pool.csv")
    core.JOBS_RAW.clear()
    core.SOURCE_LOG.clear()
    core.parse_historical_jobs()
    raw_count = len(core.JOBS_RAW)

    strict_jobs: list[dict[str, Any]] = []
    exclusion_reasons: Counter[str] = Counter()
    for job in core.JOBS_RAW:
        keep, reason = is_strict_computing_job(job)
        if keep:
            copied = dict(job)
            copied["strict_relevance_basis"] = reason
            strict_jobs.append(copied)
        else:
            exclusion_reasons[reason] += 1
    core.JOBS_RAW[:] = strict_jobs

    matched = core.match_jobs(companies)
    write_csv(OUT / "historical_jobs_matched.csv", matched)
    write_csv(OUT / "historical_jobs_source_log.csv", core.SOURCE_LOG)
    summary = {
        "raw_candidate_jobs_before_strict_title_filter": raw_count,
        "strict_historical_computing_jobs": len(strict_jobs),
        "excluded_candidate_jobs": raw_count - len(strict_jobs),
        "exclusion_reasons": dict(exclusion_reasons),
        "matched_historical_jobs": len(matched),
        "matched_companies": len({item.get("company_index") for item in matched}),
        "platforms": dict(Counter(item.get("source_platform", "") for item in matched)),
        "job_categories": dict(Counter(item.get("job_category", "") for item in matched)),
        "quality_rule": "以岗位标题为主；产品/项目/实施/支持类须同时具备IT行业或职责证据；销售商务等标题直接排除",
    }
    (OUT / "historical_jobs_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
