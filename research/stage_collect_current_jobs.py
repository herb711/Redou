#!/usr/bin/env python3
from __future__ import annotations
import argparse, csv, json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any
import verify_2059 as core
import verify_2059_browser as browser

OUT=Path("stage_output"); OUT.mkdir(exist_ok=True)


def write_csv(path: Path, rows: list[dict[str,Any]]) -> None:
    fields=[]
    for row in rows:
        for k in row:
            if k not in fields: fields.append(k)
    with path.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)


def main() -> None:
    ap=argparse.ArgumentParser(); ap.add_argument("--platform",choices=["51job","boss"],required=True); args=ap.parse_args()
    core.JOBS_RAW.clear(); core.SOURCE_LOG.clear()
    if args.platform=="51job": browser.collect_51job_browser()
    else: browser.collect_boss_browser()
    rows=list(core.JOBS_RAW)
    write_csv(OUT/f"current_jobs_{args.platform}.csv",rows)
    write_csv(OUT/f"current_jobs_{args.platform}_source_log.csv",core.SOURCE_LOG)
    summary={
        "generated_at":datetime.now().isoformat(timespec="seconds"),"platform":args.platform,"raw_tech_jobs":len(rows),
        "cities":dict(Counter(x.get("location","") for x in rows).most_common(30)),
        "categories":dict(Counter(x.get("job_category","") for x in rows)),
        "education":dict(Counter(x.get("education","") for x in rows)),
        "experience":dict(Counter(x.get("experience","") for x in rows)),
    }
    (OUT/f"current_jobs_{args.platform}_summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(summary,ensure_ascii=False))

if __name__=="__main__": main()
