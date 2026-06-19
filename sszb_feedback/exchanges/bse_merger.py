"""BSE 并购重组（发行股份购买资产/重组上市）反馈文件抓取器。"""
import re
import json
import time
from datetime import datetime, timedelta
from pathlib import Path

from ..downloader import download_pdf, get_session
from ..parser import parse_pdf
from ..models import FeedbackDocument, ProjectFeedback, FeedbackReport
from .. import config
from .base import ExchangeBase


class BSEMerger(ExchangeBase):
    """北交所并购重组反馈文件抓取器。"""

    EXCHANGE = "bse"
    BASE_URL = "https://www.bse.cn"
    LIST_API = "/projectNewsController/infoResult.do"
    DETAIL_API = "/projectNewsController/infoDetailResult.do"

    def _parse_jsonp(self, text: str):
        text = text.strip()
        for pattern in [r"null\((.*)\)", r"callback\((.*)\)"]:
            match = re.search(pattern, text, re.DOTALL)
            if match:
                return json.loads(match.group(1))
        return json.loads(text)

    def _classify_doc(self, title: str) -> str:
        """分类并购重组文档。"""
        if any(kw in title for kw in ["重组问询", "审核问询函", "并购重组审核"]):
            if "回复" not in title:
                return "inquiry"
            return "reply"
        if "回复" in title and ("会计师" not in title and "律师" not in title):
            return "reply"
        if "重组报告书" in title or "交易报告书" in title:
            return "prospectus"
        return "skip"

    def _extract_business_type(self, title: str) -> str:
        if "重组上市" in title:
            return "重组上市"
        if "吸收合并" in title:
            return "吸收合并"
        return "发行股份购买资产"

    def fetch_projects(self, days: int = 7) -> FeedbackReport:
        import sys
        from concurrent.futures import ThreadPoolExecutor, as_completed

        session = get_session()
        self._session = session
        cutoff = datetime.now() - timedelta(days=days)
        date_range = f"{cutoff.strftime('%Y-%m-%d')} ~ {datetime.now().strftime('%Y-%m-%d')}"

        print(f"📋 Fetching BSE M&A projects...", file=sys.stderr)
        candidate_items = []
        page = 0
        while page < 100:
            resp = session.post(
                f"{self.BASE_URL}{self.LIST_API}",
                data={
                    "page": page,
                    "isNewThree": "0",
                    "sortfield": "updateDate",
                    "sorttype": "desc",
                },
            )
            time.sleep(config.REQUEST_DELAY)
            data = self._parse_jsonp(resp.text)
            items = data[0]["listInfo"]["content"]
            stop = False
            for item in items:
                ts = item["updateDate"]["time"] / 1000
                if datetime.fromtimestamp(ts) < cutoff:
                    stop = True
                    break
                candidate_items.append(item)
            if stop or data[0]["listInfo"]["lastPage"]:
                break
            page += 1

        print(f"📋 Found {len(candidate_items)} candidates, fetching details...", file=sys.stderr)

        all_projects = []
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {
                executor.submit(self._process_project, session, item, cutoff): item
                for item in candidate_items
            }
            for future in as_completed(futures):
                project = future.result()
                if project:
                    all_projects.append(project)

        all_projects.sort(key=lambda p: (
            p.inquiry.publish_date if p.inquiry else
            p.reply.publish_date if p.reply else ""
        ), reverse=True)

        print(f"✅ Found {len(all_projects)} M&A projects", file=sys.stderr)
        return FeedbackReport(
            exchange=self.EXCHANGE,
            business_type="merger",
            date_range=date_range,
            ma_projects=all_projects,
        )

    def _process_project(self, session, item: dict, cutoff: datetime) -> ProjectFeedback | None:
        pid = item["id"]
        company = item.get("stockName", "")
        code = item.get("stockCode", "")

        resp = session.post(f"{self.BASE_URL}{self.DETAIL_API}?id={pid}")
        time.sleep(config.REQUEST_DELAY)
        detail = self._parse_jsonp(resp.text)

        wxhfh = detail[0].get("wxhfhInfo", [])
        xxgk = detail[0].get("xxgkInfo", {})

        inquiry_doc = None
        reply_doc = None
        restructure_doc = None
        business_type = ""

        for doc in wxhfh:
            title = doc.get("disclosureTitle", "")
            pub_date = doc.get("publishDate", "")
            if not pub_date:
                continue
            try:
                if datetime.strptime(pub_date, "%Y-%m-%d") < cutoff:
                    continue
            except ValueError:
                continue

            cat = self._classify_doc(title)
            if cat == "skip":
                continue
            if not business_type:
                business_type = self._extract_business_type(title)

            exchange_dir = config.DOWNLOADS_DIR / config.EXCHANGE_NAMES[self.EXCHANGE] / "merger"
            filename = self._make_filename(pub_date, company, title)
            pdf_url = f"{self.BASE_URL}{doc.get('destFilePath', '')}"

            fb_doc = FeedbackDocument(
                exchange=self.EXCHANGE, company_name=company, stock_code=code,
                doc_type=cat, title=title, publish_date=pub_date,
                pdf_url=pdf_url, pdf_path=str(exchange_dir / filename),
            )

            if cat == "inquiry" and inquiry_doc is None:
                inquiry_doc = fb_doc
            elif cat == "reply" and reply_doc is None:
                reply_doc = fb_doc
            elif cat == "prospectus" and restructure_doc is None:
                restructure_doc = fb_doc

        # Check restructuring report in other sections
        for section_key in ["ZDBG", "GPGZDBG"]:
            for sub in xxgk.get(section_key, []) if isinstance(xxgk.get(section_key), list) else []:
                pub_date = sub.get("publishDate", "")
                if not pub_date:
                    continue
                try:
                    if datetime.strptime(pub_date, "%Y-%m-%d") < cutoff:
                        continue
                except ValueError:
                    continue
                title = sub.get("disclosureTitle", "重组报告书（注册稿）")
                exchange_dir = config.DOWNLOADS_DIR / config.EXCHANGE_NAMES[self.EXCHANGE] / "merger"
                filename = self._make_filename(pub_date, company, title)
                restructure_doc = FeedbackDocument(
                    exchange=self.EXCHANGE, company_name=company, stock_code=code,
                    doc_type="prospectus", title=title, publish_date=pub_date,
                    pdf_url=f"{self.BASE_URL}{sub.get('destFilePath', '')}",
                    pdf_path=str(exchange_dir / filename),
                )
                break

        if not (inquiry_doc or reply_doc or restructure_doc):
            return None

        return ProjectFeedback(
            company_name=company, stock_code=code,
            business_type=business_type or "发行股份购买资产",
            inquiry=inquiry_doc, reply=reply_doc,
            prospectus=restructure_doc,
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

        session = getattr(self, '_session', None) or get_session()
        docs = []
        for project in (report.projects or []):
            for doc in [project.inquiry, project.reply, project.prospectus]:
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
