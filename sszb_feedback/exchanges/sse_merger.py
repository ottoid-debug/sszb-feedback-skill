"""SSE 并购重组（发行股份购买资产/重组上市）反馈文件抓取器。"""
import re
import json
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests

from ..downloader import download_pdf
from ..parser import parse_pdf
from ..models import FeedbackDocument, ProjectFeedback, FeedbackReport
from .. import config
from .base import ExchangeBase

SSE_PDF_HOST = "https://static.sse.com.cn/stock"


class SSEMerger(ExchangeBase):
    """上交所并购重组反馈文件抓取器。"""

    EXCHANGE = "sse"
    API_URL = "https://query.sse.com.cn/commonSoaQuery.do"

    def _build_session(self) -> requests.Session:
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 Chrome/125.0.0.0 Safari/537.36",
            "Referer": "https://www.sse.com.cn/disclosure/ma/",
        })
        return session

    def _parse_jsonp(self, text: str) -> dict:
        match = re.search(r"\w+\((.*)\)", text, re.DOTALL)
        if match:
            return json.loads(match.group(1))
        return json.loads(text)

    def fetch_projects(self, days: int = 7) -> FeedbackReport:
        import sys
        session = self._build_session()
        self._session = session
        cutoff = datetime.now() - timedelta(days=days)
        date_range = f"{cutoff.strftime('%Y-%m-%d')} ~ {datetime.now().strftime('%Y-%m-%d')}"
        print(f"📋 Fetching SSE M&A since {cutoff.strftime('%Y-%m-%d')}...", file=sys.stderr)

        projects_map = {}
        page = 0
        page_size = 50

        while True:
            params = {
                "jsonCallBack": "jsonpCallback",
                "isPagination": "true",
                "pageHelp.pageSize": str(page_size),
                "pageHelp.pageNo": str(page + 1),
                "pageHelp.beginPage": str(page + 1),
                "pageHelp.endPage": str(page + 1),
                "pageHelp.cacheSize": "1",
                "sqlName": "WEB_SSE_GP_CZBGPL",
                "order": "updateDate|desc,stockCode|asc",
                "startDate": cutoff.strftime("%Y-%m-%d"),
                "endDate": datetime.now().strftime("%Y-%m-%d"),
                "_": str(int(time.time() * 1000)),
            }
            resp = session.get(self.API_URL, params=params, timeout=config.REQUEST_TIMEOUT)
            time.sleep(config.REQUEST_DELAY)
            data = self._parse_jsonp(resp.text)
            result = data.get("result", [])
            if not result:
                break

            for item in result:
                company = item.get("companyFullName", "") or item.get("stockName", "")
                if company not in projects_map:
                    projects_map[company] = {
                        "company": company, "code": item.get("stockCode", ""), "items": [],
                    }
                title = item.get("announcementTitle", "")
                pub_date = item.get("announcementDate", "")[:10]
                if not pub_date:
                    continue
                try:
                    if datetime.strptime(pub_date, "%Y-%m-%d") < cutoff:
                        continue
                except ValueError:
                    continue
                projects_map[company]["items"].append({
                    "title": title, "date": pub_date,
                    "url": item.get("announcementURL", ""),
                })

            if len(result) < page_size:
                break
            page += 1

        all_projects = []
        for info in projects_map.values():
            business_type = ""
            reply_doc = None
            restructure_doc = None

            for item_doc in info["items"]:
                title = item_doc["title"]
                pdf_url = f"{SSE_PDF_HOST}{item_doc['url']}" if item_doc["url"].startswith("/") else item_doc["url"]
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

                if not business_type:
                    if "重组上市" in title: business_type = "重组上市"
                    elif "吸收合并" in title: business_type = "吸收合并"

            if reply_doc or restructure_doc:
                all_projects.append(ProjectFeedback(
                    company_name=info["company"], stock_code=info["code"],
                    business_type=business_type or "发行股份购买资产",
                    reply=reply_doc, prospectus=restructure_doc,
                ))

        print(f"✅ Found {len(all_projects)} SSE M&A projects", file=sys.stderr)
        return FeedbackReport(
            exchange=self.EXCHANGE, business_type="merger",
            date_range=date_range, ma_projects=all_projects,
        )

    def _make_filename(self, date: str, company: str, title: str) -> str:
        clean_title = title
        for sep in [":", "："]:
            if sep in title:
                clean_title = title.split(sep, 1)[1]
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
