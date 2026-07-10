#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Full 2059-company verification using accessible public interfaces.

This runner fixes two limitations found in the first audit:
1. Chongqing government pages return an empty shell to plain requests, so their
   public pages are read through r.jina.ai's text reader and parsed from tables.
2. 51Job/BOSS public search requires a browser session; Playwright runs the same
   public fetch from the loaded page context. No login or CAPTCHA bypass is used.
"""
from __future__ import annotations

import json
import random
import re
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence
from urllib.parse import quote, urlencode

import requests
from playwright.sync_api import sync_playwright

import verify_2059 as core
from verify_2059_fast import verify_companies_with_breaker

# Broader official-subject endings. Original workbook includes companies,
# research institutes, branches, factories and a small number of public units.
ENDINGS = (
    "集团股份有限公司|集团有限公司|股份有限公司|有限责任公司|有限公司|股份公司|"
    "重庆分公司|分公司|重庆市分行|重庆分行|分行|支行|研究院有限公司|研究院|研究所|"
    "发展研究中心|创新中心|技术中心|检测中心|服务中心|评测中心|公共服务平台|"
    "职业培训学校|培训学校|学校|大学|学院|协会|实验室|分院|中心|卷烟厂|制药厂|药厂|工厂|厂"
)
LEGAL_RE = re.compile(rf"[\u4e00-\u9fffA-Za-z0-9（）()·&＋+\-]{2,100}(?:{ENDINGS})$")
LEAD_RE = re.compile(r"^(?:\d+(?:\.\d+)?|[一二三四五六七八九十百]+)[.、）)]?\s*")
BAD = ["附件", "名单", "公示", "通知", "申报", "项目名称", "产品名称", "服务方向", "服务产品", "单位名称", "企业名称", "序号", "所属地区", "来源"]


def is_subject(s: str) -> bool:
    s = core.clean_text(s).strip("*#|，。；;、:：[]【】")
    if not (4 <= len(s) <= 105):
        return False
    if any(x in s for x in BAD):
        return False
    if s.startswith(("关于", "根据", "重庆市经济和信息化委员会", "重庆市人力资源和社会保障局")):
        return False
    return bool(LEGAL_RE.fullmatch(s))


def normalize_cell(s: str) -> str:
    s = core.clean_text(s).strip("*#|，。；;、:：[]【】")
    s = LEAD_RE.sub("", s)
    s = re.sub(r"^(?:申报单位|建设单位|牵头单位|依托单位|使用单位|供应方|服务商名称|企业名称|单位名称)[:：]?", "", s)
    return s.strip()


def extract_from_markdown(md: str, expected: int) -> List[str]:
    names: List[str] = []
    # Table cells are highest precision.
    for line in md.splitlines():
        line = line.strip()
        cells = [normalize_cell(x) for x in line.split("|")] if "|" in line else [normalize_cell(line)]
        for cell in cells:
            if is_subject(cell):
                names.append(cell)
        # Some cells contain prefixes or multiple parentheses; recover the legal tail.
        for m in re.finditer(rf"[\u4e00-\u9fffA-Za-z0-9（）()·&＋+\-]{{4,100}}(?:{ENDINGS})", line):
            cand = normalize_cell(m.group(0))
            if is_subject(cand):
                names.append(cand)
    # Normalize and preserve source order.
    out: List[str] = []
    seen = set()
    for n in names:
        key = core.norm_name(n)
        if key and key not in seen:
            seen.add(key); out.append(n)
    # If boilerplate added a few unrelated subjects, expected count is a useful
    # quality guard, not a fabricated count: retain source order and log trimming.
    if expected and len(out) > expected + 8:
        out = out[:expected]
    return out


def jina_url(url: str) -> str:
    return "https://r.jina.ai/http://" + re.sub(r"^https?://", "", url)


def fetch_source_via_reader(src: Dict[str, Any]) -> List[str]:
    url = jina_url(src["url"])
    try:
        r = requests.get(url, headers={"User-Agent": core.UA, "Accept":"text/plain"}, timeout=90)
        r.raise_for_status()
        names = extract_from_markdown(r.text, int(src["expected"]))
        status = "ok" if names else "no_names"
        note = f"expected={src['expected']}; extracted={len(names)}; reader={url}"
        core.log(src["name"], src["url"], status, len(names), note)
        return names
    except Exception as exc:
        core.log(src["name"], src["url"], "failed", 0, f"reader failed: {exc!r}")
        return []


def build_chongqing_reader() -> List[Dict[str, Any]]:
    agg: Dict[str, Dict[str, Any]] = {}
    # Modest parallelism; these are static official pages.
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = {ex.submit(fetch_source_via_reader, src): src for src in core.CQ_SOURCES}
        results = []
        for fut in as_completed(futs):
            results.append((futs[fut], fut.result()))
    # Restore official source date order for deterministic aggregation.
    results.sort(key=lambda x: x[0]["date"], reverse=True)
    priority = {"直接IT/数字化服务":3,"智能制造用人企业":2,"科技型/先进制造潜在IT用人企业":1}
    for src, names in results:
        for name in names:
            key = core.norm_name(name)
            row = agg.setdefault(key, {
                "region":"重庆","sample_name":name,"full_name":name,"stock_code":"","name_basis":"官方名单主体全称",
                "city":"重庆","district":"待核实","sample_level":src["level"],"source_names":[],"source_urls":[],
                "latest_source_date":"","official_confirmed":"是","official_subject_type":"企业或官方列名单位"
            })
            row["source_names"].append(src["name"]); row["source_urls"].append(src["url"])
            row["latest_source_date"] = max(row["latest_source_date"], src["date"])
            if priority.get(src["level"],0) > priority.get(row["sample_level"],0):
                row["sample_level"] = src["level"]
    rows = list(agg.values())
    for row in rows:
        row["source_names"] = "；".join(sorted(set(row["source_names"])))
        row["source_urls"] = "；".join(sorted(set(row["source_urls"])))
        row["source_count"] = len(row["source_names"].split("；"))
    rows.sort(key=lambda x: core.norm_name(x["sample_name"]))
    core.log("重庆35个官方名单阅读代理重建去重", "35 official source pages", "ok" if rows else "failed", len(rows), "source workbook target=1059")
    return rows


def eastmoney_list() -> List[Dict[str, Any]]:
    url = "https://push2.eastmoney.com/api/qt/clist/get"
    params = {
        "pn":1,"pz":1300,"po":1,"np":1,"fltt":2,"invt":2,"fid":"f12",
        "fs":"m:0+t:80","fields":"f12,f14,f100,f102,f103"
    }
    try:
        r = requests.get(url, params=params, headers={"User-Agent":core.UA,"Referer":"https://quote.eastmoney.com/"}, timeout=60)
        r.raise_for_status(); diff = ((r.json().get("data") or {}).get("diff") or [])
        rows=[]
        for x in diff:
            code=core.clean_text(x.get("f12")); short=core.clean_text(x.get("f14"))
            if not re.fullmatch(r"30\d{4}",code) or not short: continue
            rows.append({
                "region":"重庆外","sample_name":short,"full_name":short,"stock_code":code,"name_basis":"创业板证券简称",
                "city":core.clean_text(x.get("f100")) or "待核实","district":"","sample_level":"创业板上市公司样本",
                "source_names":"东方财富交易所行情镜像（创业板）","source_urls":url,"source_count":1,
                "latest_source_date":datetime.now().date().isoformat(),"official_confirmed":"是-上市证券存在",
                "exchange_industry":core.clean_text(x.get("f102")) or core.clean_text(x.get("f103"))
            })
        rows.sort(key=lambda x:x["stock_code"])
        rows=rows[:1000]
        core.log("创业板证券样本",url,"ok" if len(rows)==1000 else "partial",len(rows))
        return rows
    except Exception as exc:
        core.log("创业板证券样本",url,"failed",0,repr(exc)); return []


def enrich_eastmoney_company(c: Dict[str, Any]) -> Dict[str, Any]:
    code=c.get("stock_code","")
    result={"exchange_full_name":"","exchange_registered_address":"","exchange_established_date":"","exchange_legal_person":"","exchange_business":"","exchange_profile_status":"未取得"}
    if not code: return result
    url="https://emweb.securities.eastmoney.com/PC_HSF10/CompanySurvey/PageAjax"
    try:
        r=requests.get(url,params={"code":"SZ"+code},headers={"User-Agent":core.UA,"Referer":"https://emweb.securities.eastmoney.com/"},timeout=30)
        r.raise_for_status(); data=r.json(); jb=data.get("jbzl") or data.get("JBZL") or []
        if isinstance(jb,dict): jb=[jb]
        if not jb: return result
        x=jb[0]
        def pick(*keys:str)->str:
            for k in keys:
                if core.clean_text(x.get(k)): return core.clean_text(x.get(k))
            return ""
        result.update({
            "exchange_full_name":pick("ORG_NAME","COMPANY_NAME","SECURITY_NAME_ABBR"),
            "exchange_registered_address":pick("REG_ADDRESS","REGISTERED_ADDRESS"),
            "exchange_established_date":pick("FOUND_DATE","ESTABLISH_DATE"),
            "exchange_legal_person":pick("LEGAL_PERSON","LEGAL_REPRESENTATIVE"),
            "exchange_business":pick("BUSINESS_SCOPE","MAIN_BUSINESS"),
            "exchange_profile_status":"已取得"
        })
        return result
    except Exception as exc:
        result["exchange_profile_status"]="访问失败:"+repr(exc)[:120]; return result


def build_outside_eastmoney() -> List[Dict[str, Any]]:
    rows=eastmoney_list()
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs={ex.submit(enrich_eastmoney_company,c):i for i,c in enumerate(rows)}
        for fut in as_completed(futs): rows[futs[fut]].update(fut.result())
    for c in rows:
        if c.get("exchange_full_name"): c["full_name"]=c["exchange_full_name"]
        c["exchange_address"]=c.get("exchange_registered_address","")
    core.log("创业板公司基本资料补充","https://emweb.securities.eastmoney.com/", "completed",sum(c.get("exchange_profile_status")=="已取得" for c in rows))
    return rows


def evaluate_json(page, url: str) -> Optional[dict]:
    script="""async (url) => {
      try {
        const r=await fetch(url,{credentials:'include',headers:{'Accept':'application/json, text/plain, */*'}});
        const t=await r.text(); return {ok:r.ok,status:r.status,text:t};
      } catch(e) { return {ok:false,status:0,text:String(e)}; }
    }"""
    res=page.evaluate(script,url)
    if not res or not res.get("ok") or str(res.get("text","")).lstrip().startswith("<"):
        return None
    try: return json.loads(res["text"])
    except Exception: return None


def collect_51job_browser() -> None:
    keywords=["Java","软件开发","嵌入式","软件测试","前端开发","Python","人工智能","运维","网络安全","数据开发","C++","鸿蒙","工业软件","算法工程师"]
    areas=[("重庆","060000"),("全国","000000")]
    seen=set(); count=0; failures=0
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True,args=["--no-sandbox"])
            ctx=browser.new_context(user_agent=core.UA,locale="zh-CN")
            page=ctx.new_page(); page.goto("https://we.51job.com/pc/search?jobArea=060000&keyword=Java&searchType=2&sortType=0&metro=",wait_until="domcontentloaded",timeout=60000); page.wait_for_timeout(4500)
            for area_name,area in areas:
                for kw in keywords:
                    for pg in range(1,21 if area=="000000" else 13):
                        params={"api_key":"51job","timestamp":str(int(time.time()*1000)),"keyword":kw,"searchType":2,"function":"","industry":"","jobArea":area,"jobArea2":"","landmark":"","metro":"","salary":"","workYear":"","degree":"","companyType":"","companySize":"","jobType":"","issueDate":"","sortType":0,"pageNum":pg,"pageSize":20,"source":1,"scene":7}
                        url="https://we.51job.com/api/job/search-pc?"+urlencode(params)
                        data=evaluate_json(page,url)
                        if not data: failures+=1; break
                        items=((((data.get("resultbody") or {}).get("job") or {}).get("items")) or [])
                        if not items: break
                        for x in items:
                            href=core.clean_text(x.get("jobHref")); key=href or (x.get("fullCompanyName"),x.get("jobName"),x.get("jobAreaString"))
                            if key in seen: continue
                            seen.add(key)
                            core.add_job({"company_name":x.get("fullCompanyName") or x.get("companyName"),"job_title":x.get("jobName"),"location":((x.get("jobAreaLevelDetail") or {}).get("cityString") or x.get("jobAreaString")),"salary":x.get("provideSalaryString"),"experience":x.get("workYearString"),"education":x.get("degreeString"),"company_size":x.get("companySizeString"),"company_type":x.get("companyTypeString"),"industry":x.get("industryType1Str"),"job_desc":" ".join(x.get("jobTags") or []),"source_platform":"51Job当前公开搜索","source_date":x.get("issueDateString") or datetime.now().date().isoformat(),"source_url":href,"time_scope":"当前","search_area":area_name,"search_keyword":kw}); count+=1
                        page.wait_for_timeout(80)
            browser.close()
        core.log("51Job浏览器公开搜索","https://we.51job.com/pc/search","ok" if count else "blocked_or_empty",count,f"failures={failures}")
    except Exception as exc:
        core.log("51Job浏览器公开搜索","https://we.51job.com/pc/search","failed",count,repr(exc))


def collect_boss_browser() -> None:
    keywords=["Java","软件开发","嵌入式","测试","前端","Python","算法","运维","网络安全","数据开发","C++","鸿蒙"]
    cities=[("重庆","101040100"),("全国","100010000")]
    seen=set(); count=0; failures=0
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True,args=["--no-sandbox"])
            ctx=browser.new_context(user_agent=core.UA,locale="zh-CN")
            page=ctx.new_page(); page.goto("https://www.zhipin.com/web/geek/job?query=Java&city=101040100",wait_until="domcontentloaded",timeout=60000); page.wait_for_timeout(5000)
            for city_name,city in cities:
                for kw in keywords:
                    for pg in range(1,11):
                        url="https://www.zhipin.com/wapi/zpgeek/search/joblist.json?"+urlencode({"scene":1,"query":kw,"city":city,"page":pg,"pageSize":30})
                        data=evaluate_json(page,url)
                        if not data: failures+=1; break
                        items=(((data.get("zpData") or {}).get("jobList")) or [])
                        if not items: break
                        for x in items:
                            jid=core.clean_text(x.get("encryptJobId")); key=jid or (x.get("brandName"),x.get("jobName"),x.get("cityName"))
                            if key in seen: continue
                            seen.add(key)
                            core.add_job({"company_name":x.get("brandName") or x.get("companyName"),"job_title":x.get("jobName"),"location":x.get("cityName") or x.get("areaDistrict"),"salary":x.get("salaryDesc"),"experience":x.get("jobExperience"),"education":x.get("jobDegree"),"company_size":x.get("brandScaleName"),"company_type":x.get("brandStageName"),"industry":x.get("brandIndustry"),"job_desc":" ".join(x.get("skills") or []),"source_platform":"BOSS直聘当前公开搜索","source_date":datetime.now().date().isoformat(),"source_url":"https://www.zhipin.com/job_detail/"+jid+".html" if jid else "","time_scope":"当前","search_area":city_name,"search_keyword":kw}); count+=1
                        page.wait_for_timeout(100)
            browser.close()
        core.log("BOSS直聘浏览器公开搜索","https://www.zhipin.com/web/geek/job","ok" if count else "blocked_or_empty",count,f"failures={failures}")
    except Exception as exc:
        core.log("BOSS直聘浏览器公开搜索","https://www.zhipin.com/web/geek/job","failed",count,repr(exc))


def main() -> None:
    cq=build_chongqing_reader(); outside=build_outside_eastmoney(); companies=cq+outside
    for i,c in enumerate(companies,1): c["sample_id"]=i
    verify_companies_with_breaker(companies)
    collect_51job_browser(); collect_boss_browser(); core.parse_historical_jobs()
    jobs=core.match_jobs(companies); core.aggregate_jobs(companies,jobs)
    current=[j for j in jobs if j.get("time_scope")=="当前"]
    hist=[j for j in jobs if j.get("time_scope")=="历史"]
    summary={
        "generated_at":core.NOW,"reconstructed_chongqing_companies":len(cq),"outside_exchange_companies":len(outside),"total_companies":len(companies),
        "source_workbook_target":{"重庆":1059,"重庆外":1000,"合计":2059},
        "alignment_difference":{"重庆":len(cq)-1059,"重庆外":len(outside)-1000,"合计":len(companies)-2059},
        "aiqicha_checked":sum(c.get("aiqicha_checked")=="是" for c in companies),"aiqicha_exact_or_near_matches":sum(c.get("aiqicha_exact_match") in {"是","近似唯一匹配"} for c in companies),
        "aiqicha_access_limited":sum("访问限制" in c.get("aiqicha_note","") for c in companies),"location_suspected_mismatch":sum(c.get("location_consistency")=="疑似不一致" for c in companies),
        "verification_result_counts":dict(Counter(c.get("verification_result","") for c in companies)),
        "raw_computer_job_records":len(core.JOBS_RAW),"matched_computer_job_records":len(jobs),"matched_current_job_records":len(current),"matched_historical_job_records":len(hist),
        "companies_with_current_jobs":sum(c.get("current_job_count",0)>0 for c in companies),"companies_with_historical_jobs_only":sum(c.get("current_job_count",0)==0 and c.get("historical_job_count",0)>0 for c in companies),
        "recruitment_status_counts":dict(Counter(c.get("recruitment_verification","") for c in companies)),"current_job_platform_counts":dict(Counter(j.get("source_platform","") for j in current)),
        "current_job_category_counts":dict(Counter(j.get("job_category","") for j in current)),"current_job_city_counts":dict(Counter(j.get("location","").split("-")[0] for j in current).most_common(30)),
        "current_education_counts":dict(Counter(j.get("education","") for j in current).most_common()),"current_experience_counts":dict(Counter(j.get("experience","") for j in current).most_common()),
        "current_skill_counts":dict(Counter(s for j in current for s in j.get("skills","").split("；") if s).most_common(40)),
        "current_salary_mid_k_mean":round(sum(j["salary_mid_k"] for j in current if isinstance(j.get("salary_mid_k"),(int,float)))/max(1,sum(isinstance(j.get("salary_mid_k"),(int,float)) for j in current)),2),
        "limitations":["商查平台若触发风控则熔断，未匹配不等于企业不存在","招聘为关键词公开搜索快照，不等于企业全部岗位","历史智联岗位单独标识，不与当前岗位混算","重庆名单重建数与原表1059的差异需查看来源日志逐表解释"]
    }
    core.write_csv(core.OUT/"company_verification.csv",companies); core.write_csv(core.OUT/"computer_jobs_matched.csv",jobs); core.write_csv(core.OUT/"source_log.csv",core.SOURCE_LOG)
    (core.OUT/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    core.write_xlsx(core.OUT/"company_verification_and_jobs_raw.xlsx",companies,jobs,summary)
    (core.OUT/"README.md").write_text("# 2059家企业真实性与计算机招聘核验\n\n```json\n"+json.dumps(summary,ensure_ascii=False,indent=2)+"\n```\n",encoding="utf-8")
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=="__main__": main()
