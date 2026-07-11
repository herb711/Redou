#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
from pathlib import Path
from urllib.parse import quote

from playwright.sync_api import sync_playwright

OUT = Path("probe_output")
OUT.mkdir(exist_ok=True)

NAMES = [
    "中冶赛迪信息技术（重庆）有限公司",
    "中移物联网有限公司",
    "重庆长安汽车软件科技有限公司",
    "北京启明星辰信息技术股份有限公司",
    "世纪保险经纪股份有限公司",
]
SITES = {
    "qcc": "https://www.qcc.com/web/search?key={}",
    "tianyancha": "https://www.tianyancha.com/search?key={}",
    "aiqicha": "https://aiqicha.baidu.com/s?q={}",
}


def main() -> None:
    rows = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/149 Safari/537.36",
            locale="zh-CN",
        )
        page = context.new_page()
        for site, template in SITES.items():
            for name in NAMES:
                url = template.format(quote(name))
                status = ""
                final_url = ""
                title = ""
                body = ""
                error = ""
                try:
                    response = page.goto(url, wait_until="domcontentloaded", timeout=45_000)
                    page.wait_for_timeout(2_500)
                    status = str(response.status if response else "")
                    final_url = page.url
                    title = page.title()
                    body = page.locator("body").inner_text(timeout=15_000)
                except Exception as exc:
                    error = repr(exc)
                    try:
                        final_url = page.url
                        title = page.title()
                        body = page.locator("body").inner_text(timeout=5_000)
                    except Exception:
                        pass
                normalized = "".join(body.split())
                exact = name.replace(" ", "") in normalized
                blocked_terms = [term for term in ["验证码", "安全验证", "登录后", "访问过于频繁", "滑块", "异常访问"] if term in body]
                rows.append({
                    "site": site,
                    "query_name": name,
                    "http_status": status,
                    "final_url": final_url,
                    "title": title,
                    "body_chars": len(body),
                    "exact_name_visible": "是" if exact else "否",
                    "blocked_terms": "；".join(blocked_terms),
                    "error": error,
                    "body_preview": body[:1500].replace("\n", " | "),
                })
        context.close()
        browser.close()
    fields = list(rows[0])
    with (OUT / "commercial_probe.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader(); w.writerows(rows)
    summary = {
        site: {
            "queries": sum(r["site"] == site for r in rows),
            "exact_visible": sum(r["site"] == site and r["exact_name_visible"] == "是" for r in rows),
            "blocked": sum(r["site"] == site and bool(r["blocked_terms"]) for r in rows),
        }
        for site in SITES
    }
    (OUT / "commercial_probe_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
