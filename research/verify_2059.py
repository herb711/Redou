#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rebuild and audit the 2059-company CS-employment sample.

Rules:
- No invented companies or jobs.
- Chongqing pool is rebuilt from the same 35 official list pages used by the source workbook.
- Outside pool is rebuilt from the official Shenzhen Stock Exchange A-share workbook.
- Enterprise cross-check uses public Aiqicha search only; no login, CAPTCHA bypass, or private data.
- Recruitment statistics separate current 51Job/BOSS attempts from historical public datasets.
- "not matched" means no match in the collected public snapshot, not proof that a company has no jobs.
"""
from __future__ import annotations

import csv
import hashlib
import hmac
import io
import json
import os
import random
import re
import shutil
import subprocess
import time
import uuid
import zipfile
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple
from urllib.parse import quote, urlencode, urljoin

import pandas as pd
import requests
from bs4 import BeautifulSoup
from docx import Document
from openpyxl import Workbook, load_workbook
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "research_work_verify"
OUT = ROOT / "research_output"
WORK.mkdir(exist_ok=True)
OUT.mkdir(exist_ok=True)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/149 Safari/537.36"
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"})
NOW = datetime.now().isoformat(timespec="seconds")

# Same 35 sources listed in the source workbook's “重庆来源统计” sheet.
CQ_SOURCES: List[Dict[str, Any]] = [
    {"name":"2026年重庆市专精特新“小巨人”申报/复核企业","date":"2026-06-22","expected":126,"level":"科技型/先进制造潜在IT用人企业","url":"https://jjxxw.cq.gov.cn/zwgk_213/gsgg/202606/t20260622_15766619.html"},
    {"name":"2026年重庆市潜在独角兽/瞪羚企业名单","date":"2026-06-22","expected":94,"level":"科技型/先进制造潜在IT用人企业","url":"https://jjxxw.cq.gov.cn/zwgk_213/gsgg/202606/t20260622_15767765.html"},
    {"name":"2026年重庆市软件企业“启明星/北斗星”第二批","date":"2026-06-15","expected":18,"level":"直接IT/数字化服务","url":"https://jjxxw.cq.gov.cn/zwgk_213/gsgg/202606/t20260615_15754096.html"},
    {"name":"2026年重庆市基础级和先进级智能工厂项目名单","date":"2026-06-15","expected":199,"level":"智能制造用人企业","url":"https://jjxxw.cq.gov.cn/zwgk_213/gsgg/202606/t20260615_15753499.html"},
    {"name":"2025年度重庆市市级工业设计中心名单","date":"2026-03-30","expected":48,"level":"科技型/先进制造潜在IT用人企业","url":"https://jjxxw.cq.gov.cn/zwgk_213/gsgg/202603/t20260330_15575828.html"},
    {"name":"2025年重庆市制造业中试平台单位","date":"2026-01-26","expected":24,"level":"科技型/先进制造潜在IT用人企业","url":"https://jjxxw.cq.gov.cn/zwgk_213/gsgg/202601/t20260126_15352657.html"},
    {"name":"2025年第三批重庆市首版次软件产品","date":"2025-11-03","expected":9,"level":"直接IT/数字化服务","url":"https://jjxxw.cq.gov.cn/zwgk_213/gsgg/202511/t20251103_15131127.html"},
    {"name":"2025年工业互联网标识解析建设项目","date":"2025-10-27","expected":4,"level":"智能制造用人企业","url":"https://jjxxw.cq.gov.cn/zwgk_213/gsgg/202510/t20251027_15116011.html"},
    {"name":"2025年重庆市5G工厂名单","date":"2025-10-27","expected":10,"level":"智能制造用人企业","url":"https://jjxxw.cq.gov.cn/zwgk_213/gsgg/202510/t20251027_15115990.html"},
    {"name":"2025年工业软件链式攻关揭榜单位","date":"2025-10-22","expected":7,"level":"直接IT/数字化服务","url":"https://jjxxw.cq.gov.cn/zwgk_213/gsgg/202510/t20251022_15102532.html"},
    {"name":"2025年第五批重庆市设计驱动型企业（机构）名单","date":"2025-08-26","expected":81,"level":"科技型/先进制造潜在IT用人企业","url":"https://jjxxw.cq.gov.cn/zwgk_213/gsgg/202508/t20250826_14935800.html"},
    {"name":"2025年重庆市服务型制造名单","date":"2025-08-11","expected":16,"level":"直接IT/数字化服务","url":"https://jjxxw.cq.gov.cn/zwgk_213/gsgg/202508/t20250811_14890625.html"},
    {"name":"2025年重庆市未来产业标志性产品名单","date":"2025-07-22","expected":30,"level":"科技型/先进制造潜在IT用人企业","url":"https://jjxxw.cq.gov.cn/zwgk_213/gsgg/202507/t20250722_14837174.html"},
    {"name":"2025年重庆市人工智能典型应用案例和需求场景","date":"2025-07-03","expected":48,"level":"直接IT/数字化服务","url":"https://jjxxw.cq.gov.cn/zwgk_213/gsgg/202507/t20250703_14774900.html"},
    {"name":"2025年工业领域细分行业产业大脑建设运营单位","date":"2025-06-18","expected":25,"level":"直接IT/数字化服务","url":"https://jjxxw.cq.gov.cn/zwgk_213/gsgg/202506/t20250618_14724898.html"},
    {"name":"2025年服务器方向揭榜单位","date":"2025-05-30","expected":3,"level":"直接IT/数字化服务","url":"https://jjxxw.cq.gov.cn/zwgk_213/gsgg/202505/t20250530_14672635.html"},
    {"name":"2024年度工业软件等软件产品和公共服务平台","date":"2025-01-21","expected":20,"level":"直接IT/数字化服务","url":"https://jjxxw.cq.gov.cn/zwgk_213/gsgg/202501/t20250121_14188753.html"},
    {"name":"2025年制造业产业链数字化金融应用单位","date":"2025-01-03","expected":5,"level":"直接IT/数字化服务","url":"https://jjxxw.cq.gov.cn/zwgk_213/gsgg/202501/t20250103_14046473.html"},
    {"name":"2024年第二批重庆市首版次软件产品","date":"2024-12-13","expected":10,"level":"直接IT/数字化服务","url":"https://jjxxw.cq.gov.cn/zwgk_213/gsgg/202412/t20241213_13943959.html"},
    {"name":"2024年关键软件方向第四批揭榜单位","date":"2024-10-18","expected":19,"level":"直接IT/数字化服务","url":"https://jjxxw.cq.gov.cn/zwgk_213/gsgg/202410/t20241018_13720168.html"},
    {"name":"2023年度软件及集成电路企业所得税优惠核查名单","date":"2024-10-14","expected":17,"level":"直接IT/数字化服务","url":"https://jjxxw.cq.gov.cn/zwgk_213/gsgg/202410/t20241014_13704561.html"},
    {"name":"2024年网络安全保险服务机构及联合单位","date":"2024-10-14","expected":23,"level":"直接IT/数字化服务","url":"https://jjxxw.cq.gov.cn/zwgk_213/gsgg/202410/t20241014_13703077.html"},
    {"name":"第九届创客中国重庆决赛获奖企业","date":"2024-09-30","expected":21,"level":"科技型/先进制造潜在IT用人企业","url":"https://jjxxw.cq.gov.cn/zwgk_213/gsgg/202409/t20240930_13678272.html"},
    {"name":"2024年度重庆市工业和信息化重点实验室依托单位","date":"2024-09-09","expected":12,"level":"科技型/先进制造潜在IT用人企业","url":"https://jjxxw.cq.gov.cn/zwgk_213/gsgg/202409/t20240909_13610591.html"},
    {"name":"2024年度重庆市企业技术中心名单","date":"2024-09-09","expected":55,"level":"科技型/先进制造潜在IT用人企业","url":"https://jjxxw.cq.gov.cn/zwgk_213/gsgg/202409/t20240909_13610626.html"},
    {"name":"第九届创客中国重庆赛道明星企业组","date":"2024-08-30","expected":53,"level":"科技型/先进制造潜在IT用人企业","url":"https://jjxxw.cq.gov.cn/zwgk_213/gsgg/202408/t20240830_13579833.html"},
    {"name":"2024年第一批重庆市首版次软件产品","date":"2024-05-09","expected":19,"level":"直接IT/数字化服务","url":"https://jjxxw.cq.gov.cn/zwgk_213/gsgg/202405/t20240509_13189879.html"},
    {"name":"2024年重庆市制造业数字化转型服务商资源池","date":"2024-02-05","expected":222,"level":"直接IT/数字化服务","url":"https://jjxxw.cq.gov.cn/zwgk_213/gsgg/202402/t20240205_12906694.html"},
    {"name":"2024年度重庆市“机器人+”典型应用场景","date":"2024-02-04","expected":13,"level":"直接IT/数字化服务","url":"https://jjxxw.cq.gov.cn/zwgk_213/gsgg/202402/t20240204_12904751.html"},
    {"name":"重庆市软件和信息服务业“满天星”示范企业（第一批）","date":"2024-01-05","expected":85,"level":"直接IT/数字化服务","url":"https://jjxxw.cq.gov.cn/zwgk_213/gsgg/202401/t20240105_12790389.html"},
    {"name":"2023年一链一网一平台试点示范企业","date":"2023-11-03","expected":4,"level":"智能制造用人企业","url":"https://jjxxw.cq.gov.cn/zwgk_213/gsgg/202311/t20231103_12516454.html"},
    {"name":"2023年第二批重庆市首版次软件产品","date":"2023-10-23","expected":53,"level":"直接IT/数字化服务","url":"https://jjxxw.cq.gov.cn/zwgk_213/gsgg/202310/t20231023_12457338.html"},
    {"name":"2023年重庆市启明星/北斗星软件企业","date":"2023-09-28","expected":39,"level":"直接IT/数字化服务","url":"https://jjxxw.cq.gov.cn/zwgk_213/gsgg/202309/t20230928_12391643.html"},
    {"name":"2023年重庆市好设计赋能高质量示范案例","date":"2023-09-26","expected":16,"level":"科技型/先进制造潜在IT用人企业","url":"https://jjxxw.cq.gov.cn/zwgk_213/gsgg/202309/t20230926_12384096.html"},
    {"name":"2023年重庆市重点软件和信息服务企业名单","date":"2023-06-19","expected":100,"level":"直接IT/数字化服务","url":"https://rlsbj.cq.gov.cn/zwxx_182/tzgg/202306/t20230619_12076811.html"},
]

SOURCE_LOG: List[Dict[str, Any]] = []
JOBS_RAW: List[Dict[str, Any]] = []

COMPANY_ENDINGS = (
    "集团股份有限公司|集团有限公司|股份有限公司|有限责任公司|有限公司|股份公司|"
    "重庆分公司|分公司|重庆市分行|重庆分行|分行|研究院有限公司|研究院|研究所|"
    "检测中心有限公司|中心有限公司|中心|卷烟厂|药厂|工厂"
)
COMPANY_RE = re.compile(rf"[\u4e00-\u9fffA-Za-z0-9（）()·&＋+\-]{2,90}(?:{COMPANY_ENDINGS})")
BAD_NAME_WORDS = ["附件", "名单", "公示", "通知", "申报", "项目名称", "产品名称", "单位名称", "企业名称", "备注"]

TECH_KW = [
    "软件","开发","程序","算法","数据","测试","运维","网络","系统","信息化","前端","后端","全栈",
    "java","python","c++","c#","php","golang","android","ios","嵌入式","单片机","驱动","硬件","芯片",
    "集成电路","通信","安全","数据库","云计算","大数据","人工智能","机器学习","深度学习","图像","视觉",
    "nlp","大模型","web","ui","ue","游戏","自动化","电子","物联网","plc","mes","gis","仿真","fpga",
    "arm","linux","鸿蒙","harmony","车载","智能座舱","机器人","产品经理","实施工程师","技术支持","erp",
    "sap","bi","数字化","计算机","研发工程师","架构师","信息安全","网络安全"
]
SKILLS = [
    "Java","Python","C++","C#","Go","PHP","JavaScript","TypeScript","Vue","React","Spring","Spring Boot",
    "MySQL","Oracle","Redis","Kafka","Linux","Docker","Kubernetes","Git","SQL","Hadoop","Spark","Flink",
    "PyTorch","TensorFlow","机器学习","深度学习","计算机视觉","NLP","大模型","嵌入式","RTOS","ARM","STM32",
    "FPGA","CAN","AUTOSAR","Android","HarmonyOS","鸿蒙","网络安全","渗透测试","自动化测试","PLC","MES","ERP"
]


def log(source: str, url: str, status: str, rows: int = 0, note: str = "") -> None:
    SOURCE_LOG.append({"source":source,"url":url,"status":status,"rows":rows,"note":note,"checked_at":NOW})


def clean_text(v: Any) -> str:
    if v is None:
        return ""
    s = str(v).replace("\u3000", " ").replace("\xa0", " ")
    s = BeautifulSoup(s, "html.parser").get_text(" ") if "<" in s and ">" in s else s
    return re.sub(r"\s+", " ", s).strip()


def norm_name(s: str) -> str:
    s = clean_text(s).replace("(", "（").replace(")", "）")
    s = re.sub(r"[\s·•—_\-]", "", s)
    return s.lower()


def short_alias(s: str) -> str:
    n = norm_name(s)
    for suffix in ["集团股份有限公司","集团有限公司","股份有限公司","有限责任公司","有限公司","股份公司","重庆市分公司","重庆分公司","分公司","重庆市分行","重庆分行","分行","研究院有限公司","研究院","研究所"]:
        if n.endswith(norm_name(suffix)):
            return n[:-len(norm_name(suffix))]
    return n


def valid_company_name(s: str) -> bool:
    s = clean_text(s).strip("，。；;、:：()（）[]【】")
    if len(s) < 4 or len(s) > 100:
        return False
    if any(w in s for w in BAD_NAME_WORDS):
        return False
    return bool(re.search(rf"(?:{COMPANY_ENDINGS})$", s))


def extract_company_names(text: str) -> List[str]:
    found: List[str] = []
    for raw_line in re.split(r"[\n\r\t]", text):
        line = clean_text(raw_line)
        if not line or len(line) > 260:
            continue
        line = re.sub(r"^[0-9一二三四五六七八九十百]+[.、）)]\s*", "", line)
        for m in COMPANY_RE.finditer(line):
            name = m.group(0).strip("，。；;、:：()（）[]【】")
            # Remove common leading column text while retaining the final legal name.
            name = re.sub(r"^(申报单位|建设单位|牵头单位|依托单位|企业名称|单位名称|使用单位|供应方|项目单位)[:：]?", "", name)
            if valid_company_name(name):
                found.append(name)
    return list(dict.fromkeys(found))


def request(url: str, **kwargs: Any) -> requests.Response:
    kwargs.setdefault("timeout", 35)
    r = SESSION.get(url, **kwargs)
    r.raise_for_status()
    return r


def attachment_text(path: Path) -> str:
    ext = path.suffix.lower()
    try:
        if ext in {".xlsx", ".xlsm"}:
            wb = load_workbook(path, read_only=True, data_only=True)
            vals = []
            for ws in wb.worksheets:
                for row in ws.iter_rows(values_only=True):
                    vals.extend(clean_text(v) for v in row if v is not None)
            return "\n".join(vals)
        if ext == ".xls":
            sheets = pd.read_excel(path, sheet_name=None, header=None)
            return "\n".join(clean_text(v) for df in sheets.values() for v in df.astype(str).values.ravel())
        if ext == ".docx":
            doc = Document(path)
            vals = [p.text for p in doc.paragraphs]
            for table in doc.tables:
                for row in table.rows:
                    vals.extend(cell.text for cell in row.cells)
            return "\n".join(vals)
        if ext == ".pdf":
            return "\n".join((p.extract_text() or "") for p in PdfReader(str(path)).pages)
        if ext == ".doc":
            p = subprocess.run(["antiword", str(path)], capture_output=True, timeout=90)
            return p.stdout.decode("utf-8", errors="replace") or p.stdout.decode("gb18030", errors="replace")
        if ext in {".txt", ".csv"}:
            data = path.read_bytes()
            for enc in ["utf-8-sig","gb18030","utf-8"]:
                try:
                    return data.decode(enc)
                except Exception:
                    pass
    except Exception as exc:
        log("attachment parser", str(path), "failed", note=repr(exc))
    return ""


def fetch_source_companies(src: Dict[str, Any], source_idx: int) -> List[str]:
    names: List[str] = []
    try:
        r = request(src["url"])
        r.encoding = r.apparent_encoding or "utf-8"
        soup = BeautifulSoup(r.text, "html.parser")
        # Structured cells and short paragraphs are preferred over whole-page prose.
        pieces: List[str] = []
        for tag in soup.select("td,th,li,p,span"):
            t = clean_text(tag.get_text(" "))
            if 3 < len(t) <= 220:
                pieces.append(t)
        names.extend(extract_company_names("\n".join(pieces)))
        links: List[str] = []
        for a in soup.find_all("a", href=True):
            href = urljoin(src["url"], a["href"])
            clean = href.split("#")[0]
            if re.search(r"\.(xlsx|xlsm|xls|docx|doc|pdf|csv|txt)(?:\?|$)", clean, re.I):
                links.append(clean)
        links = list(dict.fromkeys(links))
        attach_dir = WORK / "attachments" / f"{source_idx:02d}"
        attach_dir.mkdir(parents=True, exist_ok=True)
        for j, link in enumerate(links):
            try:
                rr = request(link)
                ext_match = re.search(r"\.(xlsx|xlsm|xls|docx|doc|pdf|csv|txt)", link, re.I)
                ext = "." + (ext_match.group(1).lower() if ext_match else "bin")
                p = attach_dir / f"attachment_{j:02d}{ext}"
                p.write_bytes(rr.content)
                names.extend(extract_company_names(attachment_text(p)))
            except Exception as exc:
                log(src["name"] + " attachment", link, "failed", note=repr(exc))
        names = list(dict.fromkeys(clean_text(n) for n in names if valid_company_name(n)))
        status = "ok" if names else "no_names"
        log(src["name"], src["url"], status, len(names), f"expected raw subjects={src['expected']}; attachments={len(links)}")
        return names
    except Exception as exc:
        log(src["name"], src["url"], "failed", 0, repr(exc))
        return []


def build_chongqing_pool() -> List[Dict[str, Any]]:
    agg: Dict[str, Dict[str, Any]] = {}
    for i, src in enumerate(CQ_SOURCES, 1):
        for name in fetch_source_companies(src, i):
            key = norm_name(name)
            row = agg.setdefault(key, {
                "region":"重庆","sample_name":name,"full_name":name,"stock_code":"","name_basis":"企业全称",
                "city":"重庆","district":"待核实","sample_level":src["level"],"source_names":[],"source_urls":[],
                "latest_source_date":"","official_confirmed":"是"
            })
            row["source_names"].append(src["name"])
            row["source_urls"].append(src["url"])
            if src["date"] > row["latest_source_date"]:
                row["latest_source_date"] = src["date"]
            # Prefer direct IT, then smart manufacturing, then potential IT.
            priority = {"直接IT/数字化服务":3,"智能制造用人企业":2,"科技型/先进制造潜在IT用人企业":1}
            if priority.get(src["level"],0) > priority.get(row["sample_level"],0):
                row["sample_level"] = src["level"]
    rows = list(agg.values())
    for row in rows:
        row["source_names"] = "；".join(sorted(set(row["source_names"])))
        row["source_urls"] = "；".join(sorted(set(row["source_urls"])))
        row["source_count"] = len(row["source_names"].split("；")) if row["source_names"] else 0
    rows.sort(key=lambda x: norm_name(x["sample_name"]))
    log("重庆35个官方名单重建去重", "source workbook methodology", "ok" if rows else "failed", len(rows), "target in source workbook=1059")
    return rows


def build_outside_pool() -> List[Dict[str, Any]]:
    url = "https://www.szse.cn/api/report/ShowReport"
    params = {"SHOWTYPE":"xlsx","CATALOGID":"1110","TABKEY":"tab1","random":str(random.random())}
    try:
        r = request(url, params=params)
        xls = pd.read_excel(io.BytesIO(r.content), dtype=str)
        xls.columns = [clean_text(c) for c in xls.columns]
        board_col = next((c for c in xls.columns if "板块" in c), "")
        code_col = next((c for c in xls.columns if "A股代码" in c or c == "证券代码"), "")
        short_col = next((c for c in xls.columns if "A股简称" in c or c == "证券简称"), "")
        full_col = next((c for c in xls.columns if "公司全称" in c or "中文全称" in c), "")
        addr_col = next((c for c in xls.columns if "注册地址" in c or "注册地" in c), "")
        industry_col = next((c for c in xls.columns if "所属行业" in c or c == "行业"), "")
        if board_col:
            xls = xls[xls[board_col].astype(str).str.contains("创业板", na=False)]
        records: List[Dict[str, Any]] = []
        for _, r0 in xls.iterrows():
            code = clean_text(r0.get(code_col,""))
            code = code.split(".")[0].zfill(6) if code else ""
            short = clean_text(r0.get(short_col,""))
            full = clean_text(r0.get(full_col,"")) or short
            addr = clean_text(r0.get(addr_col,""))
            if not short or (addr and "重庆" in addr):
                continue
            records.append({
                "region":"重庆外","sample_name":short,"full_name":full,"stock_code":code,"name_basis":"证券简称/交易所全称",
                "city":"待核实","district":"","sample_level":"上市公司样本","source_names":"深圳证券交易所A股列表",
                "source_urls":url,"source_count":1,"latest_source_date":datetime.now().date().isoformat(),
                "official_confirmed":"是","exchange_address":addr,"exchange_industry":clean_text(r0.get(industry_col,""))
            })
        records.sort(key=lambda x: x["stock_code"])
        records = records[:1000]
        log("深圳证券交易所创业板样本", url, "ok" if len(records)==1000 else "partial", len(records), f"columns={list(xls.columns)}")
        return records
    except Exception as exc:
        log("深圳证券交易所创业板样本", url, "failed", 0, repr(exc))
        return []


def recursive_dicts(obj: Any) -> Iterator[Dict[str, Any]]:
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from recursive_dicts(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from recursive_dicts(v)


def first(d: Dict[str, Any], keys: Sequence[str]) -> str:
    for k in keys:
        v = d.get(k)
        if isinstance(v, (str,int,float)) and clean_text(v):
            return clean_text(v)
    return ""


def aiqicha_query(company: Dict[str, Any]) -> Dict[str, Any]:
    query_name = company.get("full_name") or company["sample_name"]
    url = "https://aiqicha.baidu.com/s/advanceFilterAjax"
    result = {"aiqicha_checked":"否","aiqicha_exact_match":"否","aiqicha_name":"","business_status":"","credit_code":"","legal_person":"","registered_address":"","established_date":"","aiqicha_url":"","aiqicha_note":""}
    try:
        time.sleep(random.uniform(0.08,0.22))
        r = SESSION.get(url, params={"q":query_name,"p":1,"s":10,"f":"{}"}, headers={"Referer":"https://aiqicha.baidu.com/","X-Requested-With":"XMLHttpRequest","User-Agent":UA}, timeout=25)
        result["aiqicha_checked"] = "是"
        if r.status_code != 200:
            result["aiqicha_note"] = f"HTTP {r.status_code}"
            return result
        data = r.json()
        candidates = (((data.get("data") or {}).get("resultList")) or [])
        if not isinstance(candidates,list):
            candidates = []
        best: Optional[Dict[str, Any]] = None
        for item in candidates:
            if not isinstance(item,dict):
                continue
            nm = first(item,["entName","companyName","titleName","name","legalName"])
            if norm_name(nm) == norm_name(query_name) or norm_name(nm) == norm_name(company["sample_name"]):
                best = item; break
        if best is None and candidates:
            # For exchange short names, accept only a unique result whose name contains the normalized short alias.
            alias = short_alias(company["sample_name"])
            plausible = [x for x in candidates if isinstance(x,dict) and alias and alias in norm_name(first(x,["entName","companyName","titleName","name"]))]
            if len(plausible)==1:
                best = plausible[0]
        if best is None:
            result["aiqicha_note"] = "公开搜索无精确结果"
            return result
        nm = first(best,["entName","companyName","titleName","name","legalName"])
        result.update({
            "aiqicha_exact_match":"是" if norm_name(nm) in {norm_name(query_name),norm_name(company["sample_name"])} else "近似唯一匹配",
            "aiqicha_name":nm,
            "business_status":first(best,["openStatus","regStatus","status","operatingStatus"]),
            "credit_code":first(best,["creditCode","unifiedCode","socialCreditCode"]),
            "legal_person":first(best,["legalPerson","legalPersonName","legalRepresentative"]),
            "registered_address":first(best,["regAddr","regLocation","address","registeredAddress"]),
            "established_date":first(best,["startDate","estiblishTime","establishDate","foundDate"]),
            "aiqicha_url":"https://aiqicha.baidu.com/company_detail_" + first(best,["pid","id"]),
            "aiqicha_note":"公共搜索结果匹配"
        })
        return result
    except Exception as exc:
        result["aiqicha_note"] = "访问失败: " + repr(exc)[:180]
        return result


def verify_companies(companies: List[Dict[str, Any]]) -> None:
    # Low parallelism to avoid excessive pressure on a public site; no anti-bot bypass.
    with ThreadPoolExecutor(max_workers=3) as ex:
        futs = {ex.submit(aiqicha_query,c):i for i,c in enumerate(companies)}
        for fut in as_completed(futs):
            companies[futs[fut]].update(fut.result())
    for c in companies:
        aq_name = c.get("aiqicha_name","")
        addr = c.get("registered_address","") or c.get("exchange_address","")
        name_ok = c.get("aiqicha_exact_match") in {"是","近似唯一匹配"}
        if c["region"] == "重庆":
            loc = "一致" if "重庆" in addr else ("疑似不一致" if addr else "地址未取得")
        else:
            loc = "一致" if addr and "重庆" not in addr else ("疑似不一致" if "重庆" in addr else "地址未取得")
        c["location_consistency"] = loc
        c["name_consistency"] = "一致" if name_ok else ("商查未匹配" if c.get("aiqicha_checked")=="是" else "商查未完成")
        active = any(k in c.get("business_status","") for k in ["存续","在业","开业","正常","迁入"])
        if name_ok and loc == "一致":
            c["verification_result"] = "一致-商查匹配" + ("且经营正常" if active else "")
        elif c.get("official_confirmed")=="是" and c.get("stock_code"):
            c["verification_result"] = "一致-交易所官方确认；商查" + ("匹配" if name_ok else "未匹配")
        elif c.get("official_confirmed")=="是":
            c["verification_result"] = "官方名单确认；" + ("商查匹配" if name_ok else "商查未匹配/未完成")
        else:
            c["verification_result"] = "待核实"
    log("爱企查公共搜索批量交叉核验", "https://aiqicha.baidu.com/", "completed", sum(1 for c in companies if c.get("aiqicha_checked")=="是"), f"exact/near matches={sum(1 for c in companies if c.get('aiqicha_exact_match') in {'是','近似唯一匹配'})}")


def tech_job(title: str, desc: str = "") -> bool:
    t = (clean_text(title)+" "+clean_text(desc)).lower()
    return any(k.lower() in t for k in TECH_KW)


def job_category(title: str) -> str:
    t = clean_text(title).lower()
    groups = [
        ("AI/算法",["算法","人工智能","机器学习","深度学习","视觉","图像","大模型","nlp"]),
        ("嵌入式/硬件",["嵌入式","单片机","驱动","fpga","硬件","芯片","arm","车载","autosar"]),
        ("后端开发",["java","python","c++","c#","php","go开发","后端","服务端"]),
        ("前端/客户端",["前端","vue","react","javascript","android","ios","鸿蒙","harmony"]),
        ("测试",["测试","qa","质量保证"]),
        ("运维/云/网络",["运维","网络","云计算","linux","devops","数据库","dba"]),
        ("数据",["数据分析","数据开发","大数据","数据工程","bi"]),
        ("安全",["安全","渗透","等保"]),
        ("工业软件/自动化",["mes","erp","plc","自动化","工业软件","实施工程师","数字化"]),
        ("产品/项目/技术支持",["产品经理","项目经理","技术支持","售前","实施"]),
    ]
    for name,kws in groups:
        if any(k in t for k in kws): return name
    return "其他计算机相关"


def salary_mid(s: str) -> Optional[float]:
    s = clean_text(s).lower().replace("元/月","").replace("薪资面议","").replace("面议","")
    nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", s)]
    if not nums: return None
    factor = 1.0
    if "万" in s: factor = 10.0
    elif "k" not in s and "千" not in s and max(nums)>100: factor = 0.001
    if "年" in s and "/年" in s: factor /= 12
    return (sum(nums[:2])/min(2,len(nums)))*factor


def add_job(row: Dict[str, Any]) -> None:
    title = clean_text(row.get("job_title"))
    if not tech_job(title, clean_text(row.get("job_desc"))): return
    row = {k:clean_text(v) for k,v in row.items()}
    row["job_category"] = job_category(title)
    row["salary_mid_k"] = salary_mid(row.get("salary",""))
    text = title + " " + row.get("job_desc","")
    row["skills"] = "；".join(s for s in SKILLS if s.lower() in text.lower())
    JOBS_RAW.append(row)


def fetch_51job_current(max_pages: int = 14) -> None:
    secret = b"abfc8f9dcf8c3f3d8aa294ac5f2cf2cc7767e5592590f39c3f503271dd68562b"
    keywords = ["Java","软件开发","嵌入式","软件测试","前端开发","Python","人工智能","运维","网络安全","数据开发","C++","鸿蒙","工业软件","算法工程师"]
    seen = set(); count=0; failures=0
    for area in ["040000","000000"]: # Chongqing, nationwide
        for keyword in keywords:
            for page in range(1,max_pages+1):
                ts=str(int(time.time()))
                params=[("api_key","51job"),("timestamp",ts),("keyword",keyword),("searchType","2"),("function",""),("industry",""),("jobArea",area),("jobArea2",""),("landmark",""),("metro",""),("salary",""),("workYear",""),("degree",""),("companyType",""),("companySize",""),("jobType",""),("issueDate",""),("sortType","0"),("pageNum",str(page)),("requestId",""),("pageSize","50"),("source","1"),("accountId",""),("pageCode","sou|sou|soulb")]
                query=urlencode(params,quote_via=quote,safe="|")
                pq="/open/noauth/search-pc?"+query
                sign=hmac.new(secret,pq.encode(),hashlib.sha256).hexdigest()
                try:
                    r=SESSION.get("https://cupid.51job.com"+pq,headers={"Accept":"application/json, text/plain, */*","From-Domain":"51job_web","Origin":"https://we.51job.com","Referer":"https://we.51job.com/","sign":sign,"uuid":uuid.uuid4().hex,"User-Agent":UA},timeout=25)
                    if r.status_code!=200: failures+=1; break
                    items=((((r.json().get("resultbody") or {}).get("job") or {}).get("items")) or [])
                    if not items: break
                    for x in items:
                        href=clean_text(x.get("jobHref")); key=href or (x.get("fullCompanyName"),x.get("jobName"),x.get("jobAreaString"))
                        if key in seen: continue
                        seen.add(key)
                        add_job({"company_name":x.get("fullCompanyName") or x.get("companyName"),"job_title":x.get("jobName"),"location":x.get("jobAreaString"),"salary":x.get("provideSalaryString"),"experience":x.get("workYearString"),"education":x.get("degreeString"),"company_size":x.get("companySizeString"),"company_type":x.get("companyTypeString"),"industry":x.get("industryType1Str") or x.get("industryType2Str"),"job_desc":"","source_platform":"51Job当前公开搜索","source_date":x.get("issueDateString") or datetime.now().date().isoformat(),"source_url":href,"time_scope":"当前"})
                        count+=1
                    time.sleep(0.12)
                except Exception:
                    failures+=1; break
    log("51Job当前公开搜索接口","https://we.51job.com/pc/search","ok" if count else "blocked_or_empty",count,f"failures={failures}")


def fetch_boss_current(max_pages: int = 5) -> None:
    keywords=["Java","软件开发","嵌入式","测试","前端","Python","算法","运维","网络安全","数据开发"]
    count=0; failures=0; seen=set()
    for kw in keywords:
        for page in range(1,max_pages+1):
            url="https://www.zhipin.com/wapi/zpgeek/search/joblist.json"
            try:
                r=SESSION.get(url,params={"scene":1,"query":kw,"city":"100010000","page":page,"pageSize":30},headers={"Referer":"https://www.zhipin.com/web/geek/job","User-Agent":UA},timeout=20)
                if r.status_code!=200: failures+=1; break
                data=r.json(); jobs=(((data.get("zpData") or {}).get("jobList")) or [])
                if not jobs: break
                for x in jobs:
                    key=clean_text(x.get("encryptJobId")) or (x.get("brandName"),x.get("jobName"),x.get("cityName"))
                    if key in seen: continue
                    seen.add(key)
                    add_job({"company_name":x.get("brandName") or x.get("companyName"),"job_title":x.get("jobName"),"location":x.get("cityName") or x.get("areaDistrict"),"salary":x.get("salaryDesc"),"experience":x.get("jobExperience"),"education":x.get("jobDegree"),"company_size":x.get("brandScaleName"),"company_type":x.get("brandStageName"),"industry":x.get("brandIndustry"),"job_desc":"","source_platform":"BOSS直聘当前公开搜索","source_date":datetime.now().date().isoformat(),"source_url":"https://www.zhipin.com/job_detail/"+clean_text(x.get("encryptJobId"))+".html","time_scope":"当前"})
                    count+=1
                time.sleep(0.15)
            except Exception:
                failures+=1; break
    log("BOSS直聘当前公开搜索接口","https://www.zhipin.com/web/geek/job","ok" if count else "blocked_or_empty",count,f"failures={failures}")


def clone_sparse(repo_url: str, dest: Path, paths: Sequence[str]) -> bool:
    if dest.exists(): shutil.rmtree(dest)
    try:
        subprocess.run(["git","clone","--depth","1","--filter=blob:none","--sparse",repo_url,str(dest)],check=True,timeout=900)
        subprocess.run(["git","-C",str(dest),"sparse-checkout","set",*paths],check=True,timeout=300)
        return True
    except Exception as exc:
        log("GitHub historical dataset",repo_url,"failed",0,repr(exc)); return False


def parse_historical_jobs() -> None:
    # Zhilian industry × city dataset (approximately 2018).
    d1=WORK/"zhilian_city"
    if clone_sparse("https://github.com/andinsbing/Analysis-of-College-Graduates-Employment-Orientation.git",d1,["src/DataClean/bigdata"]):
        base=d1/"src/DataClean/bigdata"; n=0
        for p in base.glob("*.org"):
            city=p.stem.rsplit("_",1)[-1] if "_" in p.stem else ""
            try: blocks=[x.strip() for x in p.read_text(encoding="utf-8",errors="replace").split("\n**********\n") if x.strip()]
            except Exception: continue
            for i in range(0,len(blocks)-4,5):
                head,_,meta,desc,info=blocks[i:i+5]; lines=[clean_text(x) for x in head.splitlines() if clean_text(x)]
                if len(lines)<2: continue
                def fv(label:str)->str:
                    m=re.search(re.escape(label)+r"[：:]\s*([^\n]+)",meta); return clean_text(m.group(1)) if m else ""
                add_job({"company_name":lines[1],"job_title":lines[0],"location":fv("工作地点") or city,"salary":fv("职位月薪"),"experience":fv("工作经验"),"education":fv("最低学历"),"industry":p.stem.rsplit("_",1)[0],"job_desc":desc[:2500],"source_platform":"智联招聘历史公开数据集","source_date":"约2018","source_url":"https://github.com/andinsbing/Analysis-of-College-Graduates-Employment-Orientation","time_scope":"历史"}); n+=1
        log("智联招聘历史行业×城市数据","https://github.com/andinsbing/Analysis-of-College-Graduates-Employment-Orientation","ok",n)
    # Zhilian role CSV dataset (2019-09).
    d2=WORK/"zhilian_roles"
    if clone_sparse("https://github.com/liuaichao/python-work.git",d2,["机器学习/智联招聘预测/data"]):
        base=d2/"机器学习/智联招聘预测/data"; n=0
        for p in base.glob("*.csv"):
            try:
                df=pd.read_csv(p,encoding="utf-8-sig",dtype=str,on_bad_lines="skip")
            except Exception: continue
            for _,x in df.iterrows():
                add_job({"company_name":x.get("公司名称",""),"job_title":x.get("职位名称",""),"location":x.get("工作地点",""),"salary":x.get("职位月薪",""),"experience":x.get("工作经验",""),"education":x.get("工作要求",""),"company_size":x.get("公司规模",""),"company_type":x.get("公司类型",""),"industry":x.get("工作类型",""),"job_desc":"","source_platform":"智联招聘历史岗位CSV","source_date":x.get("发布时间","2019-09"),"source_url":"https://github.com/liuaichao/python-work","time_scope":"历史"}); n+=1
        log("智联招聘历史岗位方向CSV","https://github.com/liuaichao/python-work","ok",n)


def match_jobs(companies: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    full_map: Dict[str,List[int]]=defaultdict(list); alias_map: Dict[str,List[int]]=defaultdict(list)
    for i,c in enumerate(companies):
        for nm in {c.get("sample_name",""),c.get("full_name","")}:
            if nm: full_map[norm_name(nm)].append(i)
        for nm in {c.get("sample_name",""),c.get("full_name","")}:
            a=short_alias(nm)
            if len(a)>=3: alias_map[a].append(i)
    matched=[]; dedup=set()
    for j in JOBS_RAW:
        jn=norm_name(j.get("company_name","")); idx=None; method=""
        if len(set(full_map.get(jn,[])))==1:
            idx=full_map[jn][0]; method="企业全称精确匹配"
        else:
            a=short_alias(j.get("company_name",""))
            if len(set(alias_map.get(a,[])))==1:
                idx=alias_map[a][0]; method="去后缀唯一匹配"
            elif len(a)>=5:
                cands=set()
                for alias,inds in alias_map.items():
                    if len(alias)>=5 and (alias in a or a in alias): cands.update(inds)
                if len(cands)==1: idx=next(iter(cands)); method="名称包含唯一匹配"
        if idx is None: continue
        c=companies[idx]
        key=(idx,j.get("job_title"),j.get("location"),j.get("salary"),j.get("source_url"))
        if key in dedup: continue
        dedup.add(key)
        row={"company_index":idx+1,"sample_company":c["sample_name"],"sample_region":c["region"],"stock_code":c.get("stock_code",""),"match_method":method}
        row.update(j); matched.append(row)
    log("招聘记录与2059企业样本名称匹配","internal","ok",len(matched),f"raw tech jobs={len(JOBS_RAW)}")
    return matched


def aggregate_jobs(companies: List[Dict[str, Any]], jobs: List[Dict[str, Any]]) -> None:
    by=defaultdict(list)
    for j in jobs: by[int(j["company_index"])-1].append(j)
    for i,c in enumerate(companies):
        js=by.get(i,[]); current=[x for x in js if x.get("time_scope")=="当前"]; hist=[x for x in js if x.get("time_scope")=="历史"]
        c["current_job_count"]=len(current); c["historical_job_count"]=len(hist)
        c["recruitment_verification"]="当前公开招聘有匹配" if current else ("仅历史招聘样本有匹配" if hist else "公开采集样本未匹配到")
        c["current_platforms"]="；".join(sorted({x.get("source_platform","") for x in current if x.get("source_platform")}))
        c["job_categories"]="；".join(k for k,_ in Counter(x.get("job_category","") for x in js).most_common(5) if k)
        c["top_skills"]="；".join(k for k,_ in Counter(s for x in js for s in x.get("skills","").split("；") if s).most_common(12))
        mids=[x.get("salary_mid_k") for x in current if isinstance(x.get("salary_mid_k"),(int,float))]
        c["current_salary_mid_k_avg"]=round(sum(mids)/len(mids),2) if mids else ""


def write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    if not rows: path.write_text("",encoding="utf-8"); return
    fields=[]
    for r in rows:
        for k in r:
            if k not in fields: fields.append(k)
    with path.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore"); w.writeheader(); w.writerows(rows)


def write_xlsx(path: Path, companies: List[Dict[str, Any]], jobs: List[Dict[str, Any]], summary: Dict[str, Any]) -> None:
    wb=Workbook(); ws=wb.active; ws.title="核验总览"
    ws.append(["指标","数值"])
    for k,v in summary.items(): ws.append([k,json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v])
    for title,rows in [("企业核验明细",companies),("计算机招聘明细",jobs),("来源日志",SOURCE_LOG)]:
        sh=wb.create_sheet(title)
        if not rows: continue
        fields=[]
        for r in rows:
            for k in r:
                if k not in fields: fields.append(k)
        sh.append(fields)
        for r in rows: sh.append([r.get(k,"") for k in fields])
        sh.freeze_panes="A2"; sh.auto_filter.ref=sh.dimensions
    wb.save(path)


def main() -> None:
    cq=build_chongqing_pool(); outside=build_outside_pool(); companies=cq+outside
    for i,c in enumerate(companies,1): c["sample_id"]=i
    verify_companies(companies)
    fetch_51job_current(); fetch_boss_current(); parse_historical_jobs()
    jobs=match_jobs(companies); aggregate_jobs(companies,jobs)
    verification_counts=Counter(c.get("verification_result","") for c in companies)
    recruitment_counts=Counter(c.get("recruitment_verification","") for c in companies)
    current_jobs=[j for j in jobs if j.get("time_scope")=="当前"]
    summary={
        "generated_at":NOW,
        "reconstructed_chongqing_companies":len(cq),
        "outside_exchange_companies":len(outside),
        "total_companies":len(companies),
        "source_workbook_target":{"重庆":1059,"重庆外":1000,"合计":2059},
        "alignment_note":"重庆池由原表35个官方来源重建；若数量不等于1059，表示网页/附件结构变化，未强行凑数。重庆外为深交所创业板当前快照前1000家（剔除注册地址含重庆）。",
        "aiqicha_checked":sum(c.get("aiqicha_checked")=="是" for c in companies),
        "aiqicha_exact_or_near_matches":sum(c.get("aiqicha_exact_match") in {"是","近似唯一匹配"} for c in companies),
        "location_suspected_mismatch":sum(c.get("location_consistency")=="疑似不一致" for c in companies),
        "verification_result_counts":dict(verification_counts),
        "raw_computer_job_records":len(JOBS_RAW),
        "matched_computer_job_records":len(jobs),
        "matched_current_job_records":len(current_jobs),
        "companies_with_current_jobs":sum(c.get("current_job_count",0)>0 for c in companies),
        "companies_with_historical_jobs_only":sum(c.get("current_job_count",0)==0 and c.get("historical_job_count",0)>0 for c in companies),
        "recruitment_status_counts":dict(recruitment_counts),
        "current_job_platform_counts":dict(Counter(j.get("source_platform","") for j in current_jobs)),
        "current_job_category_counts":dict(Counter(j.get("job_category","") for j in current_jobs)),
        "current_job_city_counts":dict(Counter(j.get("location","").split("-")[0] for j in current_jobs).most_common(30)),
        "current_education_counts":dict(Counter(j.get("education","") for j in current_jobs).most_common()),
        "current_experience_counts":dict(Counter(j.get("experience","") for j in current_jobs).most_common()),
        "current_skill_counts":dict(Counter(s for j in current_jobs for s in j.get("skills","").split("；") if s).most_common(40)),
        "important_limitation":"爱企查/招聘平台可能因公开接口风控而未返回；未匹配不等于企业不存在或没有招聘。历史招聘记录单独标记，不与当前在招混算。"
    }
    write_csv(OUT/"company_verification.csv",companies)
    write_csv(OUT/"computer_jobs_matched.csv",jobs)
    write_csv(OUT/"source_log.csv",SOURCE_LOG)
    (OUT/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    write_xlsx(OUT/"company_verification_and_jobs_raw.xlsx",companies,jobs,summary)
    report=["# 2059家企业真实性与计算机招聘核验（自动化原始结果）","",f"生成时间：{NOW}","",f"- 重庆官方来源重建：{len(cq)}家（原表目标1059）",f"- 重庆外交易所样本：{len(outside)}家（目标1000）",f"- 爱企查完成请求：{summary['aiqicha_checked']}家；精确/唯一近似匹配：{summary['aiqicha_exact_or_near_matches']}家",f"- 匹配到当前计算机岗位：{summary['matched_current_job_records']}条，涉及企业{summary['companies_with_current_jobs']}家",f"- 匹配到历史计算机岗位：{summary['matched_computer_job_records']-summary['matched_current_job_records']}条","","注意：平台未匹配不等于企业不存在或没有招聘；详见 source_log.csv 与明细中的核验状态。"]
    (OUT/"README.md").write_text("\n".join(report),encoding="utf-8")
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
