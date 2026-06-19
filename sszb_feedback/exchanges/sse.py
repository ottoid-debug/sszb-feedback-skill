"""Shanghai Stock Exchange (上交所) scraper."""
import re
import json
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests

from ..downloader import download_pdf
from ..parser import parse_pdf
from ..models import FeedbackDocument, ProjectFeedback, FeedbackReport, BusinessType
from .. import config
from .base import ExchangeBase

# PDF host for SSE (filePath needs /stock prefix)
SSE_PDF_HOST = "https://static.sse.com.cn/stock"


class SSE(ExchangeBase):
    """上交所 IPO feedback scraper.

    SSE only discloses inquiry REPLIES, not the original inquiry letters.
    Uses fileTypeMap=I3010 to filter "问询与回复" type documents.
    """

    EXCHANGE = "sse"
    API_URL = "https://query.sse.com.cn/commonSoaQuery.do"

    def __init__(self, business_type: str = "ipo"):
        """业务类型. SSE 目前只支持 IPO; 再融资/资产重组待实现。"""
        self.business_type = business_type

    def _build_session(self) -> requests.Session:
        session = requests.Session()
        session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            "Referer": "https://www.sse.com.cn/listing/disclosure/ipo/",
        })
        if config.HTTP_PROXY:
            session.proxies = {
                "http": config.HTTP_PROXY,
                "https": config.HTTP_PROXY,
            }
        return session

    def _parse_jsonp(self, text: str) -> dict:
        """Parse JSONP response."""
        match = re.search(r"\w+\((.*)\)", text, re.DOTALL)
        if match:
            return json.loads(match.group(1))
        return json.loads(text)

    def fetch_projects(self, days: int = 7) -> FeedbackReport:
        """Fetch IPO inquiry replies and registration drafts from the past N days."""
        session = self._build_session()
        cutoff = datetime.now() - timedelta(days=days)
        date_range = f"{cutoff.strftime('%Y-%m-%d')} ~ {datetime.now().strftime('%Y-%m-%d')}"
        import sys
        print(f"📋 Fetching SSE feedback since {cutoff.strftime('%Y-%m-%d')}...", file=sys.stderr)

        # Merge results by company name
        projects_map = {}

        # 1. Fetch inquiry replies (I3010)
        for file_type, doc_type_label in [("I3010", "reply"), ("I0013", "prospectus")]:
            page = 1
            while True:
                resp = session.get(self.API_URL, params={
                    "jsonCallBack": "cb",
                    "isPagination": "true",
                    "sqlId": "GP_COMMON_FILE_SEARCH",
                    "fileTitle": "",
                    "pageHelp.pageSize": "50",
                    "pageHelp.pageNo": str(page),
                    "pageHelp.beginPage": "1",
                    "pageHelp.cacheSize": "1",
                    "pageHelp.endPage": "1",
                    "fileTypeMap": file_type,
                    "marketType": "1,2",
                    "searchkeyword": "",
                    "startDate": cutoff.strftime("%Y-%m-%d"),
                    "endDate": datetime.now().strftime("%Y-%m-%d"),
                })
                time.sleep(config.REQUEST_DELAY)

                # Retry on connection errors
                for attempt in range(3):
                    try:
                        data = self._parse_jsonp(resp.text)
                        break
                    except Exception:
                        if attempt < 2:
                            time.sleep(2)
                            resp = session.get(self.API_URL, params={
                                "jsonCallBack": "cb",
                                "isPagination": "true",
                                "sqlId": "GP_COMMON_FILE_SEARCH",
                                "fileTitle": "",
                                "pageHelp.pageSize": "50",
                                "pageHelp.pageNo": str(page),
                                "pageHelp.beginPage": "1",
                                "pageHelp.cacheSize": "1",
                                "pageHelp.endPage": "1",
                                "fileTypeMap": file_type,
                                "marketType": "1,2",
                                "searchkeyword": "",
                                "startDate": cutoff.strftime("%Y-%m-%d"),
                                "endDate": datetime.now().strftime("%Y-%m-%d"),
                            })
                        else:
                            data = {"pageHelp": {"data": [], "totalPage": 1}}

                items = data.get("pageHelp", {}).get("data", [])

                if not items:
                    break

                for item in items:
                    upd_time = item.get("fileUpdTime", "")
                    if upd_time and len(upd_time) >= 8:
                        try:
                            item_date = datetime.strptime(upd_time[:8], "%Y%m%d").date()
                            if item_date < cutoff.date():
                                continue
                        except ValueError:
                            pass

                    company = item.get("companyAbbr", "")
                    if company not in projects_map:
                        projects_map[company] = ProjectFeedback(
                            company_name=company,
                            stock_code=item.get("companyCode", ""),
                        )

                    proj = projects_map[company]
                    doc = self._make_doc(item, doc_type_label)
                    if doc_type_label == "reply" and proj.reply is None:
                        proj.reply = doc
                    elif doc_type_label == "prospectus" and proj.prospectus is None:
                        proj.prospectus = doc

                total_pages = data.get("pageHelp", {}).get("totalPage", 1)
                if page >= total_pages:
                    break
                page += 1

        all_projects = [p for p in projects_map.values() if p.reply or p.prospectus]

        print(f"✅ Found {len(all_projects)} projects with inquiry replies", file=sys.stderr)
        return FeedbackReport(exchange=self.EXCHANGE, business_type=self.business_type, date_range=date_range, projects=all_projects)

    def _make_doc(self, item: dict, doc_type: str) -> FeedbackDocument | None:
        """Create a FeedbackDocument from an SSE API item."""
        company = item.get("companyAbbr", "")
        code = item.get("companyCode", "")
        title = item.get("fileTitle", "")
        file_path = item.get("filePath", "")
        upd_time = item.get("fileUpdTime", "")

        if not file_path:
            return None

        pub_date = ""
        if upd_time and len(upd_time) >= 8:
            pub_date = f"{upd_time[:4]}-{upd_time[4:6]}-{upd_time[6:8]}"

        pdf_url = f"{SSE_PDF_HOST}{file_path}"
        exchange_dir = config.DOWNLOADS_DIR / config.EXCHANGE_NAMES[self.EXCHANGE]
        filename = self._make_filename(pub_date, company, title)
        pdf_path = exchange_dir / filename

        return FeedbackDocument(
            exchange=self.EXCHANGE,
            company_name=company,
            stock_code=code,
            doc_type=doc_type,
            title=title,
            publish_date=pub_date,
            pdf_url=pdf_url,
            pdf_path=str(pdf_path),
            content_text="",
        )

    def _make_filename(self, date: str, company: str, title: str) -> str:
        """Generate a clean filename."""
        clean_title = re.sub(r'[\\/:*?"<>|]', "", title).strip()
        company = re.sub(r'[\\/:*?"<>|]', "", company).strip()
        return f"{date}_{company}_{clean_title}.pdf"

    def download_and_parse(self, report: FeedbackReport, parse_text: bool = True) -> FeedbackReport:
        """Download PDFs first, then parse text."""
        import sys
        from concurrent.futures import ThreadPoolExecutor, as_completed

        session = self._build_session()
        docs = []
        for project in report.projects:
            for doc in [project.reply, project.prospectus]:
                if doc is not None:
                    docs.append(doc)

        # Phase 1: Download
        print(f"📥 Phase 1: Downloading {len(docs)} PDFs...", file=sys.stderr)

        def _download(doc):
            pdf_path = Path(doc.pdf_path)
            if not pdf_path.exists():
                success = download_pdf(doc.pdf_url, pdf_path, session)
                if not success:
                    doc.content_text = "[Download failed]"

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(_download, doc) for doc in docs]
            for i, future in enumerate(as_completed(futures), 1):
                future.result()
                print(f"  ✓ [{i}/{len(docs)}] downloaded", file=sys.stderr)

        # Phase 2: Parse
        if parse_text:
            print(f"📄 Phase 2: Parsing {len(docs)} PDFs...", file=sys.stderr)
            for i, doc in enumerate(docs, 1):
                pdf_path = Path(doc.pdf_path)
                if pdf_path.exists() and not doc.content_text.startswith("["):
                    doc.content_text = parse_pdf(pdf_path, max_chars=config.PDF_TEXT_LIMIT)
                    print(f"  ✓ [{i}/{len(docs)}] parsed", file=sys.stderr)

        return report
