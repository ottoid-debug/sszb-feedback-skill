"""SZSE 并购重组（发行股份购买资产/重组上市）反馈文件抓取器。"""
import re
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests

from ..downloader import download_pdf
from ..parser import parse_pdf
from ..models import FeedbackDocument, ProjectFeedback, FeedbackReport
from .. import config
from .base import ExchangeBase

SZSE_PDF_HOST = "https://reportdocs.static.szse.cn"


class SZSEMerger(ExchangeBase):
    """深交所并购重组反馈文件抓取器。"""

    EXCHANGE = "szse"
    BASE_URL = "https://www.szse.cn"
    API_URL = "/api/ras/infodisc/query"

    def _build_session(self) -> requests.Session:
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 Chrome/125.0.0.0 Safari/537.36",
            "Referer": f"{self.BASE_URL}/listing/disclosure/ma/index.html",
        })
        return session

    def fetch_projects(self, days: int = 7) -> FeedbackReport:
        import sys
        session = self._build_session()
        self._session = session
        cutoff = datetime.now() - timedelta(days=days)
        date_range = f"{cutoff.strftime('%Y-%m-%d')} ~ {datetime.now().strftime('%Y-%m-%d')}"
        print(f"📋 Fetching SZSE M&A since {cutoff.strftime('%Y-%m-%d')}...", file=sys.stderr)

        projects_map = {}
        page = 0

        while True:
            resp = session.get(
                f"{self.BASE_URL}{self.API_URL}",
                params={
                    "pageIndex": page, "pageSize": 50,
                    "keywords": "",
                    "disclosedStartDate": cutoff.strftime("%Y-%m-%d"),
                    "disclosedEndDate": datetime.now().strftime("%Y-%m-%d"),
                    "catalog": "",
                    "bizType": "3",  # 3 = 并购重组
                },
            )
            time.sleep(config.REQUEST_DELAY)
            data = resp.json()

            for proj in data.get("data", []):
                company = proj.get("cmpsnm", "")
                if company not in projects_map:
                    projects_map[company] = {
                        "company": company, "code": proj.get("cmpcode", ""),
                        "business_type": "发行股份购买资产", "items": [],
                    }

                for doc in proj.get("subInfoDisclosureList", []):
                    dfnm = doc.get("dfnm", "")
                    dfpth = doc.get("dfpth", "")
                    pub_date = proj.get("ddt", "")[:10]
                    if not dfpth or not pub_date:
                        continue
                    try:
                        if datetime.strptime(pub_date, "%Y-%m-%d") < cutoff:
                            continue
                    except ValueError:
                        continue

                    projects_map[company]["items"].append({
                        "title": dfnm, "date": pub_date, "path": dfpth,
                    })

                    if "重组上市" in dfnm:
                        projects_map[company]["business_type"] = "重组上市"
                    elif "吸收合并" in dfnm:
                        projects_map[company]["business_type"] = "吸收合并"

            if page + 1 >= data.get("totalPage", 1):
                break
            page += 1

        all_projects = []
        for info in projects_map.values():
            reply_doc = None
            restructure_doc = None

            for item_doc in info["items"]:
                title = item_doc["title"]
                pdf_url = f"{SZSE_PDF_HOST}{item_doc['path']}"
                exchange_dir = config.DOWNLOADS_DIR / config.EXCHANGE_NAMES[self.EXCHANGE] / "merger"
                filename = self._make_filename(item_doc["date"], info["company"], title)

                if "回复" in title and "会计师" not in title and "律师" not in title:
                    reply_doc = FeedbackDocument(
                        exchange=self.EXCHANGE, company_name=info["company"],
                        stock_code=info["code"], doc_type="reply",
                        title=title, publish_date=item_doc["date"],
                        pdf_url=pdf_url, pdf_path=str(exchange_dir / filename),
                    )
                elif "重组报告书" in title or "交易报告书" in title:
                    restructure_doc = FeedbackDocument(
                        exchange=self.EXCHANGE, company_name=info["company"],
                        stock_code=info["code"], doc_type="prospectus",
                        title=title, publish_date=item_doc["date"],
                        pdf_url=pdf_url, pdf_path=str(exchange_dir / filename),
                    )

            if reply_doc or restructure_doc:
                all_projects.append(ProjectFeedback(
                    company_name=info["company"], stock_code=info["code"],
                    business_type=info["business_type"],
                    reply=reply_doc, prospectus=restructure_doc,
                ))

        print(f"✅ Found {len(all_projects)} SZSE M&A projects", file=sys.stderr)
        return FeedbackReport(
            exchange=self.EXCHANGE, business_type="merger",
            date_range=date_range, ma_projects=all_projects,
        )

    def _make_filename(self, date: str, company: str, title: str) -> str:
        clean_title = title.replace(".pdf", "")
        clean_title = re.sub(r'[\\/:*?"<>|]', "", clean_title).strip()
        company = re.sub(r'[\\/:*?"<>|]', "", company).strip()
        return f"{date}_{company}_{clean_title}.pdf"

    def download_and_parse(self, report: FeedbackReport, parse_text: bool = True) -> FeedbackReport:
        import sys
        from concurrent.futures import ThreadPoolExecutor, as_completed

        session = getattr(self, '_session', None) or self._build_session()
        docs = []
        for project in (report.projects or []):
            for doc in [project.reply, project.prospectus]:
                if doc is not None:
                    docs.append(doc)

        if not docs:
            return report

        print(f"📥 Phase 1: Downloading {len(docs)} PDFs...", file=sys.stderr)
        def _download(doc):
            pdf_path = Path(doc.pdf_path)
            if not pdf_path.exists():
                success = download_pdf(doc.pdf_url, pdf_path, session)
                if not success:
                    doc.content_text = "[Download failed]"

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(_download, doc) for doc in docs]
            for i, _ in enumerate(as_completed(futures), 1):
                print(f"  ✓ [{i}/{len(docs)}] downloaded", file=sys.stderr)

        if parse_text:
            print(f"📄 Phase 2: Parsing {len(docs)} PDFs...", file=sys.stderr)
            for i, doc in enumerate(docs, 1):
                pdf_path = Path(doc.pdf_path)
                if pdf_path.exists() and not doc.content_text.startswith("["):
                    doc.content_text = parse_pdf(pdf_path, max_chars=config.PDF_TEXT_LIMIT)
                    print(f"  ✓ [{i}/{len(docs)}] parsed", file=sys.stderr)

        return report
