#!/usr/bin/env python3
from __future__ import annotations
import argparse, csv, json, re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from urllib.parse import quote
import requests
import verify_2059 as core

IN=Path("stage_input"); OUT=Path("stage_output"); OUT.mkdir(exist_ok=True)


def read_csv(path: Path) -> list[dict[str,str]]:
    with path.open("r",encoding="utf-8-sig",newline="") as f: return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict[str,Any]]) -> None:
    fields=[]
    for row in rows:
        for key in row:
            if key not in fields: fields.append(key)
    with path.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)


def first(d: dict[str,Any], keys: list[str]) -> str:
    for k in keys:
        v=d.get(k)
        if isinstance(v,(str,int,float)) and core.clean_text(v): return core.clean_text(v)
    return ""


def direct_aiqicha(name: str) -> dict[str,str]:
    result={"commercial_checked":"是","commercial_match":"否","commercial_name":"","business_status":"","credit_code":"","legal_person":"","registered_address":"","established_date":"","commercial_url":"","commercial_source":"爱企查公共搜索","commercial_note":""}
    try:
        r=requests.get("https://aiqicha.baidu.com/s/advanceFilterAjax",params={"q":name,"p":1,"s":10,"f":"{}"},headers={"User-Agent":core.UA,"Referer":"https://aiqicha.baidu.com/","X-Requested-With":"XMLHttpRequest"},timeout=9)
        if r.status_code!=200:
            result["commercial_note"]=f"HTTP {r.status_code}"; return result
        payload=r.json(); candidates=(((payload.get("data") or {}).get("resultList")) or [])
        if not isinstance(candidates,list): candidates=[]
        exact=[]
        for item in candidates:
            if not isinstance(item,dict): continue
            nm=first(item,["entName","companyName","titleName","name","legalName"])
            if core.norm_name(nm)==core.norm_name(name): exact.append(item)
        if len(exact)!=1:
            result["commercial_note"]="公开搜索无唯一精确结果"; return result
        item=exact[0]; nm=first(item,["entName","companyName","titleName","name","legalName"])
        result.update({
            "commercial_match":"是","commercial_name":nm,
            "business_status":first(item,["openStatus","regStatus","status","operatingStatus"]),
            "credit_code":first(item,["creditCode","unifiedCode","socialCreditCode"]),
            "legal_person":first(item,["legalPerson","legalPersonName","legalRepresentative"]),
            "registered_address":first(item,["regAddr","regLocation","address","registeredAddress"]),
            "established_date":first(item,["startDate","estiblishTime","establishDate","foundDate"]),
            "commercial_url":"https://aiqicha.baidu.com/company_detail_"+first(item,["pid","id"]),
            "commercial_note":"公共搜索唯一精确匹配",
        })
        return result
    except Exception as exc:
        result["commercial_checked"]="否"; result["commercial_note"]="访问失败:"+repr(exc)[:120]; return result


def reader_exact(name: str) -> dict[str,str]:
    result={"reader_checked":"否","reader_exact":"否","reader_note":""}
    try:
        url="https://r.jina.ai/http://aiqicha.baidu.com/s?q="+quote(name)
        r=requests.get(url,headers={"User-Agent":core.UA,"Accept":"text/plain"},timeout=14)
        result["reader_checked"]="是"
        if r.status_code==200 and core.norm_name(name) in core.norm_name(r.text):
            result["reader_exact"]="是"; result["reader_note"]="爱企查公开页面阅读结果包含企业全称"
        else: result["reader_note"]=f"未精确命中/HTTP {r.status_code}"
    except Exception as exc: result["reader_note"]="访问失败:"+repr(exc)[:100]
    return result


def verify(row: dict[str,str]) -> dict[str,Any]:
    name=row.get("full_name") or row.get("sample_name","")
    res=direct_aiqicha(name)
    if res.get("commercial_match")!="是": res.update(reader_exact(name))
    else: res.update({"reader_checked":"未需要","reader_exact":"未需要","reader_note":""})
    addr=res.get("registered_address") or row.get("exchange_registered_address") or row.get("exchange_address","")
    region=row.get("region","")
    if addr:
        loc="一致" if ((region=="重庆" and "重庆" in addr) or (region!="重庆" and "重庆" not in addr)) else "疑似不一致"
    else: loc="地址未取得"
    name_ok=res.get("commercial_match")=="是" or res.get("reader_exact")=="是"
    exchange_ok=bool(row.get("stock_code")) and bool(row.get("exchange_full_name") or row.get("full_name"))
    active=any(x in res.get("business_status","") for x in ["存续","在业","开业","正常","迁入"])
    if name_ok and loc=="疑似不一致": verdict="名称一致但注册地址疑似不一致"
    elif name_ok: verdict="商查名称一致"+("且经营状态正常" if active else "")+("；"+loc if loc else "")
    elif exchange_ok: verdict="交易所/行情资料确认；商查未匹配或受限"
    elif row.get("official_confirmed"): verdict="政府官方名单确认；商查未匹配或受限"
    else: verdict="待进一步核实"
    return {"sample_id":row.get("sample_id"),"sample_name":row.get("sample_name"),"region":region,**res,"location_consistency":loc,"verification_result":verdict}


def main() -> None:
    ap=argparse.ArgumentParser(); ap.add_argument("--shard",type=int,required=True); ap.add_argument("--total-shards",type=int,required=True); args=ap.parse_args()
    rows=read_csv(IN/"company_pool.csv")
    selected=[r for i,r in enumerate(rows) if i%args.total_shards==args.shard]
    out=[]
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs={ex.submit(verify,r):r for r in selected}
        for fut in as_completed(futs): out.append(fut.result())
    out.sort(key=lambda x:int(x.get("sample_id") or 0))
    write_csv(OUT/f"business_verification_{args.shard}.csv",out)
    summary={"shard":args.shard,"rows":len(out),"commercial_exact":sum(x.get("commercial_match")=="是" for x in out),"reader_exact":sum(x.get("reader_exact")=="是" for x in out),"suspected_location_mismatch":sum(x.get("location_consistency")=="疑似不一致" for x in out)}
    (OUT/f"business_summary_{args.shard}.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(summary,ensure_ascii=False))

if __name__=="__main__": main()
