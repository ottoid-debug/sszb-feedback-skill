"""Shenzhen Stock Exchange (深交所) scraper."""
import re
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests

from ..downloader import download_pdf
from ..parser import parse_pdf
from ..models import FeedbackDocument, ProjectFeedback, FeedbackReport, BusinessType
from .. import config
from .base import ExchangeBase

# PDF host for SZSE
SZSE_PDF_HOST = "https://reportdocs.static.szse.cn"


class SZSE(ExchangeBase):
    """深交所 IPO feedback scraper.

    SZSE only discloses inquiry REPLIES, not the original inquiry letters.
    Uses catalog=4 to filter "问询与回复" type documents.
    """

    EXCHANGE = "szse"

    def __init__(self, business_type: str = "ipo"):
        """业务类型. SZSE 目前只支持 IPO; 再融资/资产重组待实现。"""
        self.business_type = business_type

    BASE_URL = "https://www.szse.cn"
    API_URL = "/api/ras/infodisc/query"

    def _build_session(self) -> requests.Session:
        session = requests.Session()
        session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            "Referer": f"{self.BASE_URL}/listing/disclosure/ipo/index.html",
        })
        if config.HTTP_PROXY:
            session.proxies = {
                "http": config.HTTP_PROXY,
                "https": config.HTTP_PROXY,
            }
        # Initialize cookies
        session.get(f"{self.BASE_URL}/listing/disclosure/ipo/index.html",
                     timeout=config.REQUEST_TIMEOUT)
        time.sleep(config.REQUEST_DELAY)
        return session

    def fetch_projects(self, days: int = 7) -> FeedbackReport:
        """Fetch IPO inquiry replies from the past N days."""
        if self.business_type != "ipo":
            import sys
            print(f"⚠ SZSE {self.business_type} 抓取暂未实现（API 需 reverse engineering）", file=sys.stderr)
            from datetime import datetime, timedelta
            cutoff = datetime.now() - timedelta(days=days)
            date_range = f"{cutoff.strftime('%Y-%m-%d')} ~ {datetime.now().strftime('%Y-%m-%d')}"
            return FeedbackReport(exchange=self.EXCHANGE, business_type=self.business_type, date_range=date_range, projects=[])

        session = self._build_session()
        cutoff = datetime.now() - timedelta(days=days)
        date_range = f"{cutoff.strftime('%Y-%m-%d')} ~ {datetime.now().strftime('%Y-%m-%d')}"
        import sys
        print(f"📋 Fetching SZSE feedback since {cutoff.strftime('%Y-%m-%d')}...", file=sys.stderr)

        projects_map = {}
        page = 0

        while True:
            resp = session.get(
                f"{self.BASE_URL}{self.API_URL}",
                params={
                    "pageIndex": page,
                    "pageSize": 50,
                    "keywords": "",
                    "disclosedStartDate": cutoff.strftime("%Y-%m-%d"),
                    "disclosedEndDate": datetime.now().strftime("%Y-%m-%d"),
                    "catalog": "",  # Fetch all types
                    "bizType": "1",
                    "boardCode": "",
                },
            )
            time.sleep(config.REQUEST_DELAY)
            data = resp.json()

            for proj in data.get("data", []):
                company = proj.get("cmpsnm", "")
                if company not in projects_map:
                    projects_map[company] = ProjectFeedback(
                        company_name=company,
                        stock_code=proj.get("cmpcode", ""),
                    )

                fp = projects_map[company]
                for doc in proj.get("subInfoDisclosureList", []):
                    dtyp = doc.get("dtyp")
                    matcat = doc.get("matcat")
                    dfnm = doc.get("dfnm", "")
                    dfpth = doc.get("dfpth", "")
                    if not dfpth:
                        continue

                    # dtyp=4 → inquiry reply, dtyp=3+matcat=3 → registration draft
                    if dtyp == 4 and fp.reply is None:
                        fp.reply = self._make_doc(doc, company, proj.get("ddt", ""), "reply")
                    elif dtyp == 3 and matcat == 3 and fp.prospectus is None:
                        fp.prospectus = self._make_doc(doc, company, proj.get("ddt", ""), "prospectus")

            if page + 1 >= data.get("totalPage", 1):
                break
            page += 1

        all_projects = [p for p in projects_map.values() if p.reply or p.prospectus]
        print(f"✅ Found {len(all_projects)} projects with feedback", file=sys.stderr)
        return FeedbackReport(exchange=self.EXCHANGE, business_type=self.business_type, date_range=date_range, projects=all_projects)

    def _make_doc(self, doc: dict, company: str, pub_date: str, doc_type: str) -> FeedbackDocument:
        """Create a FeedbackDocument from a SZSE API document entry."""
        dfnm = doc.get("dfnm", "")
        dfpth = doc.get("dfpth", "")
        code = ""  # SZSE API doesn't return stock code in doc entries

        pdf_url = f"{SZSE_PDF_HOST}{dfpth}"
        exchange_dir = config.DOWNLOADS_DIR / config.EXCHANGE_NAMES[self.EXCHANGE]
        filename = self._make_filename(pub_date, company, dfnm)
        pdf_path = exchange_dir / filename

        return FeedbackDocument(
            exchange=self.EXCHANGE,
            company_name=company,
            stock_code=code,
            doc_type=doc_type,
            title=dfnm.replace(".pdf", ""),
            publish_date=pub_date,
            pdf_url=pdf_url,
            pdf_path=str(pdf_path),
            content_text="",
        )

    def _make_filename(self, date: str, company: str, title: str) -> str:
        """Generate a clean filename."""
        clean_title = title.replace(".pdf", "")
        clean_title = re.sub(r'[\\/:*?"<>|]', "", clean_title).strip()
        company = re.sub(r'[\\/:*?"<>|]', "", company).strip()
        return f"{date}_{company}_{clean_title}.pdf"

    def download_and_parse(self, report: FeedbackReport, parse_text: bool = True) -> FeedbackReport:
        """Download PDFs and optionally parse text."""
        import sys
        from concurrent.futures import ThreadPoolExecutor, as_completed

        session = self._build_session()
        docs_to_process = []
        for project in report.projects:
            for doc in [project.reply, project.prospectus]:
                if doc is not None:
                    docs_to_process.append(doc)

        # Phase 1: Download
        print(f"📥 Phase 1: Downloading {len(docs_to_process)} PDFs...", file=sys.stderr)

        def _download(doc):
            pdf_path = Path(doc.pdf_path)
            if not pdf_path.exists():
                success = download_pdf(doc.pdf_url, pdf_path, session)
                if not success:
                    doc.content_text = "[Download failed]"

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(_download, doc) for doc in docs_to_process]
            for i, future in enumerate(as_completed(futures), 1):
                future.result()
                print(f"  ✓ [{i}/{len(docs_to_process)}] downloaded", file=sys.stderr)

        # Phase 2: Parse
        if parse_text:
            print(f"📄 Phase 2: Parsing {len(docs_to_process)} PDFs...", file=sys.stderr)
            for i, doc in enumerate(docs_to_process, 1):
                pdf_path = Path(doc.pdf_path)
                if pdf_path.exists() and not doc.content_text.startswith("["):
                    doc.content_text = parse_pdf(pdf_path, max_chars=config.PDF_TEXT_LIMIT)
                    print(f"  ✓ [{i}/{len(docs_to_process)}] parsed", file=sys.stderr)

        return report
