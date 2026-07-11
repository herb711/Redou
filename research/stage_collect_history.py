#!/usr/bin/env python3
from __future__ import annotations
import csv, json
from collections import Counter
from pathlib import Path
from typing import Any
import verify_2059 as core

IN=Path("stage_input"); OUT=Path("stage_output"); OUT.mkdir(exist_ok=True)


def read_csv(path: Path) -> list[dict[str,str]]:
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
    core.JOBS_RAW.clear(); core.SOURCE_LOG.clear(); core.parse_historical_jobs()
    matched=core.match_jobs(companies)
    write_csv(OUT/"historical_jobs_matched.csv",matched)
    write_csv(OUT/"historical_jobs_source_log.csv",core.SOURCE_LOG)
    summary={"raw_historical_tech_jobs":len(core.JOBS_RAW),"matched_historical_jobs":len(matched),"matched_companies":len({x.get('company_index') for x in matched}),"platforms":dict(Counter(x.get('source_platform','') for x in matched))}
    (OUT/"historical_jobs_summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(summary,ensure_ascii=False))

if __name__=="__main__": main()
