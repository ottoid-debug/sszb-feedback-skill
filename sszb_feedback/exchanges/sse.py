"""Shanghai Stock Exchange (上交所) scraper.

支持 IPO / 再融资 / 重大资产重组三大业务类型。
通过 commonSoaQuery.do 的 fileTypeMap 参数切换不同业务文件：
    IPO:   I3010 (问询回复) / I0013 (招股说明书)
    再融资: S3010 (问询回复) / S3020 (问询函) / S0011 (募集说明书)
    重组:   M3010 (问询回复) / M3020 (问询函) / M0011 (重组报告书)
"""
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

SSE_PDF_HOST = "https://static.sse.com.cn/stock"


class SSE(ExchangeBase):
    """上交所 deal feedback scraper."""

    EXCHANGE = "sse"
    API_URL = "https://query.sse.com.cn/commonSoaQuery.do"

    # 各业务类型对应的 fileTypeMap 组合 (file_type, doc_type_label)
    FILE_TYPE_MAP = {
        "ipo": [
            ("I3010", "reply"),
            ("I0013", "prospectus"),
        ],
        "refinance": [
            ("S3020", "inquiry"),
            ("S3010", "reply"),
            ("S0011", "prospectus"),
        ],
        "asset_purchase": [
            ("M3020", "inquiry"),
            ("M3010", "reply"),
            ("M0011", "prospectus"),
        ],
    }

    def __init__(self, business_type: str = "ipo"):
        self.business_type = business_type

    def _build_session(self) -> requests.Session:
        session = requests.Session()
        session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            "Referer": "https://www.sse.com.cn/",
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
        """Fetch deal feedback from the past N days for the configured business_type."""
        import sys

        session = self._build_session()
        cutoff = datetime.now() - timedelta(days=days)
        date_range = f"{cutoff.strftime('%Y-%m-%d')} ~ {datetime.now().strftime('%Y-%m-%d')}"

        biz_label = {"ipo": "IPO", "refinance": "再融资", "asset_purchase": "重大资产重组"}.get(self.business_type, self.business_type)
        print(f"📋 Fetching SSE {biz_label} since {cutoff.strftime('%Y-%m-%d')}...", file=sys.stderr)

        # 按公司名归集
        projects_map = {}

        file_type_pairs = self.FILE_TYPE_MAP.get(self.business_type, [])
        if not file_type_pairs:
            print(f"⚠ SSE 未配置 business_type={self.business_type}", file=sys.stderr)
            return FeedbackReport(exchange=self.EXCHANGE, business_type=self.business_type, date_range=date_range, projects=[])

        for file_type, doc_type_label in file_type_pairs:
            page = 1
            while True:
                params = {
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
                }
                resp = session.get(self.API_URL, params=params)
                time.sleep(config.REQUEST_DELAY)

                # Retry on connection errors
                for attempt in range(3):
                    try:
                        data = self._parse_jsonp(resp.text)
                        break
                    except Exception:
                        if attempt < 2:
                            time.sleep(2)
                            resp = session.get(self.API_URL, params=params)
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
                    if not company:
                        continue
                    if company not in projects_map:
                        projects_map[company] = ProjectFeedback(
                            company_name=company,
                            stock_code=item.get("companyCode", ""),
                            business_type=self.business_type,
                        )

                    proj = projects_map[company]
                    doc = self._make_doc(item, doc_type_label)
                    if doc is None:
                        continue
                    if doc_type_label == "inquiry" and proj.inquiry is None:
                        proj.inquiry = doc
                    elif doc_type_label == "reply" and proj.reply is None:
                        proj.reply = doc
                    elif doc_type_label == "prospectus" and proj.prospectus is None:
                        proj.prospectus = doc

                total_pages = data.get("pageHelp", {}).get("totalPage", 1)
                if page >= total_pages:
                    break
                page += 1

        all_projects = [p for p in projects_map.values() if p.inquiry or p.reply or p.prospectus]
        print(f"✅ Found {len(all_projects)} SSE {biz_label} projects", file=sys.stderr)
        return FeedbackReport(
            exchange=self.EXCHANGE,
            business_type=self.business_type,
            date_range=date_range,
            projects=all_projects,
        )

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
            business_type=self.business_type,
            title=title,
            publish_date=pub_date,
            pdf_url=pdf_url,
            pdf_path=str(pdf_path),
        )

    def _make_filename(self, date: str, company: str, title: str) -> str:
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
            for doc in [project.inquiry, project.reply, project.prospectus]:
                if doc is not None:
                    docs.append(doc)

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

        if parse_text:
            print(f"📄 Phase 2: Parsing {len(docs)} PDFs...", file=sys.stderr)
            for i, doc in enumerate(docs, 1):
                pdf_path = Path(doc.pdf_path)
                if pdf_path.exists() and not doc.content_text.startswith("["):
                    doc.content_text = parse_pdf(pdf_path, max_chars=config.PDF_TEXT_LIMIT)
                    print(f"  ✓ [{i}/{len(docs)}] parsed", file=sys.stderr)

        return report
