#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlencode

from playwright.sync_api import Page, sync_playwright

import verify_2059 as core

OUT = Path("stage_output")
OUT.mkdir(exist_ok=True)

KEYWORDS_51 = [
    "Java", "软件开发", "嵌入式", "软件测试", "前端开发", "Python",
    "人工智能", "运维", "网络安全", "数据开发", "C++", "鸿蒙",
]
KEYWORDS_BOSS = ["Java", "软件开发", "嵌入式", "测试", "前端", "Python", "算法", "运维", "网络安全", "数据开发", "C++", "鸿蒙"]


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


def page_fetch_json(page: Page, url: str, timeout_ms: int = 15_000) -> Optional[dict[str, Any]]:
    script = """
    async ({url, timeoutMs}) => {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), timeoutMs);
      try {
        const response = await fetch(url, {
          credentials: 'include',
          headers: {'Accept': 'application/json, text/plain, */*'},
          signal: controller.signal,
        });
        const text = await response.text();
        return {ok: response.ok, status: response.status, text};
      } catch (error) {
        return {ok: false, status: 0, text: '', error: String(error && error.message || error)};
      } finally {
        clearTimeout(timer);
      }
    }
    """
    try:
        result = page.evaluate(script, {"url": url, "timeoutMs": timeout_ms})
    except Exception:
        return None
    if not result or not result.get("ok"):
        return None
    text = str(result.get("text", ""))
    if not text or text.lstrip().startswith("<"):
        return None
    try:
        payload = json.loads(text)
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def collect_51job() -> dict[str, Any]:
    seen: set[Any] = set()
    requests_attempted = 0
    failed_groups = 0
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        context = browser.new_context(user_agent=core.UA, locale="zh-CN")
        page = context.new_page()
        try:
            page.goto(
                "https://we.51job.com/pc/search?jobArea=060000&keyword=Java&searchType=2&sortType=0",
                wait_until="domcontentloaded",
                timeout=60_000,
            )
            page.wait_for_timeout(3_500)
        except Exception as exc:
            core.log("51Job浏览器初始化", "https://we.51job.com/pc/search", "failed", 0, repr(exc))

        # Five 50-row pages per keyword/area give a broad snapshot without
        # allowing one anti-bot response to keep the workflow running indefinitely.
        for area_name, area_code in [("重庆", "060000"), ("全国", "000000")]:
            for keyword in KEYWORDS_51:
                consecutive_failures = 0
                for page_number in range(1, 6):
                    params = {
                        "api_key": "51job",
                        "timestamp": str(int(time.time() * 1000)),
                        "keyword": keyword,
                        "searchType": 2,
                        "function": "",
                        "industry": "",
                        "jobArea": area_code,
                        "jobArea2": "",
                        "landmark": "",
                        "metro": "",
                        "salary": "",
                        "workYear": "",
                        "degree": "",
                        "companyType": "",
                        "companySize": "",
                        "jobType": "",
                        "issueDate": "",
                        "sortType": 0,
                        "pageNum": page_number,
                        "pageSize": 50,
                        "source": 1,
                        "scene": 7,
                    }
                    url = "https://we.51job.com/api/job/search-pc?" + urlencode(params)
                    requests_attempted += 1
                    payload = page_fetch_json(page, url)
                    if not payload:
                        consecutive_failures += 1
                        if consecutive_failures >= 2:
                            failed_groups += 1
                            break
                        continue
                    consecutive_failures = 0
                    items = ((((payload.get("resultbody") or {}).get("job") or {}).get("items")) or [])
                    if not items:
                        break
                    for item in items:
                        href = core.clean_text(item.get("jobHref"))
                        key = href or (
                            item.get("fullCompanyName") or item.get("companyName"),
                            item.get("jobName"),
                            item.get("jobAreaString"),
                        )
                        if key in seen:
                            continue
                        seen.add(key)
                        area_detail = item.get("jobAreaLevelDetail") or {}
                        core.add_job(
                            {
                                "company_name": item.get("fullCompanyName") or item.get("companyName"),
                                "job_title": item.get("jobName"),
                                "location": area_detail.get("cityString") or item.get("jobAreaString"),
                                "district": area_detail.get("districtString"),
                                "salary": item.get("provideSalaryString"),
                                "experience": item.get("workYearString"),
                                "education": item.get("degreeString"),
                                "company_size": item.get("companySizeString"),
                                "company_type": item.get("companyTypeString"),
                                "industry": item.get("industryType1Str") or item.get("industryType2Str"),
                                "job_desc": " ".join(item.get("jobTags") or []),
                                "source_platform": "51Job当前公开搜索",
                                "source_date": item.get("issueDateString") or datetime.now().date().isoformat(),
                                "source_url": href,
                                "time_scope": "当前",
                                "search_area": area_name,
                                "search_keyword": keyword,
                            }
                        )
                    page.wait_for_timeout(60)
        context.close()
        browser.close()

    status = "ok" if core.JOBS_RAW else "访问受限或无返回"
    core.log(
        "51Job浏览器公开搜索",
        "https://we.51job.com/pc/search",
        status,
        len(core.JOBS_RAW),
        f"attempted={requests_attempted}; failed keyword-area groups={failed_groups}; bounded timeout=15s",
    )
    return {"requests_attempted": requests_attempted, "failed_groups": failed_groups}


def collect_boss() -> dict[str, Any]:
    seen: set[Any] = set()
    requests_attempted = 0
    failed_groups = 0
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        context = browser.new_context(user_agent=core.UA, locale="zh-CN")
        page = context.new_page()
        try:
            page.goto(
                "https://www.zhipin.com/web/geek/job?query=Java&city=101040100",
                wait_until="domcontentloaded",
                timeout=60_000,
            )
            page.wait_for_timeout(4_000)
        except Exception as exc:
            core.log("BOSS浏览器初始化", "https://www.zhipin.com/web/geek/job", "failed", 0, repr(exc))

        for city_name, city_code in [("重庆", "101040100"), ("全国", "100010000")]:
            for keyword in KEYWORDS_BOSS:
                consecutive_failures = 0
                for page_number in range(1, 5):
                    url = "https://www.zhipin.com/wapi/zpgeek/search/joblist.json?" + urlencode(
                        {"scene": 1, "query": keyword, "city": city_code, "page": page_number, "pageSize": 30}
                    )
                    requests_attempted += 1
                    payload = page_fetch_json(page, url)
                    if not payload:
                        consecutive_failures += 1
                        if consecutive_failures >= 2:
                            failed_groups += 1
                            break
                        continue
                    consecutive_failures = 0
                    items = (((payload.get("zpData") or {}).get("jobList")) or [])
                    if not items:
                        break
                    for item in items:
                        job_id = core.clean_text(item.get("encryptJobId"))
                        key = job_id or (item.get("brandName"), item.get("jobName"), item.get("cityName"))
                        if key in seen:
                            continue
                        seen.add(key)
                        core.add_job(
                            {
                                "company_name": item.get("brandName") or item.get("companyName"),
                                "job_title": item.get("jobName"),
                                "location": item.get("cityName") or item.get("areaDistrict"),
                                "district": item.get("areaDistrict"),
                                "salary": item.get("salaryDesc"),
                                "experience": item.get("jobExperience"),
                                "education": item.get("jobDegree"),
                                "company_size": item.get("brandScaleName"),
                                "company_type": item.get("brandStageName"),
                                "industry": item.get("brandIndustry"),
                                "job_desc": " ".join(item.get("skills") or []),
                                "source_platform": "BOSS直聘当前公开搜索",
                                "source_date": datetime.now().date().isoformat(),
                                "source_url": "https://www.zhipin.com/job_detail/" + job_id + ".html" if job_id else "",
                                "time_scope": "当前",
                                "search_area": city_name,
                                "search_keyword": keyword,
                            }
                        )
                    page.wait_for_timeout(80)
        context.close()
        browser.close()

    status = "ok" if core.JOBS_RAW else "访问受限或无返回"
    core.log(
        "BOSS直聘浏览器公开搜索",
        "https://www.zhipin.com/web/geek/job",
        status,
        len(core.JOBS_RAW),
        f"attempted={requests_attempted}; failed keyword-city groups={failed_groups}; bounded timeout=15s",
    )
    return {"requests_attempted": requests_attempted, "failed_groups": failed_groups}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform", choices=["51job", "boss"], required=True)
    args = parser.parse_args()

    core.JOBS_RAW.clear()
    core.SOURCE_LOG.clear()
    diagnostics = collect_51job() if args.platform == "51job" else collect_boss()
    rows = list(core.JOBS_RAW)
    write_csv(OUT / f"current_jobs_{args.platform}.csv", rows)
    write_csv(OUT / f"current_jobs_{args.platform}_source_log.csv", core.SOURCE_LOG)
    summary = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "platform": args.platform,
        "raw_tech_jobs": len(rows),
        "access_interpretation": "0条且日志显示访问受限时，不得解释为企业无招聘",
        **diagnostics,
        "cities": dict(Counter(item.get("location", "") for item in rows).most_common(30)),
        "categories": dict(Counter(item.get("job_category", "") for item in rows)),
        "education": dict(Counter(item.get("education", "") for item in rows)),
        "experience": dict(Counter(item.get("experience", "") for item in rows)),
    }
    (OUT / f"current_jobs_{args.platform}_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
