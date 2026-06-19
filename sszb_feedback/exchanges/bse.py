"""Beijing Stock Exchange (北交所) scraper.

支持 IPO / 再融资 / 重大资产重组三大业务类型。
北交所 IPO、定向发行（再融资）、重大资产重组都走 projectNewsController 同一披露系统，
通过文档标题关键词区分业务类型。
"""
import re
import json
import time
from datetime import datetime, timedelta
from pathlib import Path

from ..downloader import download_pdf, get_session
from ..parser import parse_pdf
from ..models import FeedbackDocument, ProjectFeedback, FeedbackReport, BusinessType
from .. import config
from .base import ExchangeBase


class BSE(ExchangeBase):
    """北交所 deal feedback scraper."""

    EXCHANGE = "bse"
    BASE_URL = "https://www.bse.cn"
    LIST_API = "/projectNewsController/infoResult.do"
    DETAIL_API = "/projectNewsController/infoDetailResult.do"

    # 不同业务类型下"主文件（招股书/募集说明书/重组报告书）"的标题关键词
    PROSPECTUS_KEYWORDS = {
        "ipo": ("招股说明书",),
        "refinance": ("募集说明书", "发行情况报告书"),
        "asset_purchase": ("重组报告书", "发行股份购买资产", "重组草案"),
    }

    def __init__(self, business_type: str = "ipo"):
        """business_type ∈ {ipo, refinance, asset_purchase}."""
        self.business_type = business_type

    def _parse_jsonp(self, text: str):
        """Parse JSONP response (wrapped in null(...)) or plain JSON."""
        text = text.strip()
        for pattern in [r"null\((.*)\)", r"callback\((.*)\)"]:
            match = re.search(pattern, text, re.DOTALL)
            if match:
                return json.loads(match.group(1))
        return json.loads(text)

    def _classify_doc(self, title: str) -> str:
        """问询函 / 回复 / skip 分类。"""
        if "问询函" in title and "回复" not in title:
            return "inquiry"
        if "回复" in title and "会计师" not in title and "律师事务所" not in title:
            return "reply"
        return "skip"

    def _business_match(self, title: str) -> bool:
        """判断文档标题是否属于当前 business_type。"""
        if not title:
            return self.business_type == "ipo"
        return BusinessType.from_title(title).value == self.business_type

    def _is_prospectus_doc(self, title: str) -> bool:
        """判断文档标题是否为本业务类型的主文件（招股书/募集说明书/重组报告书）。"""
        keywords = self.PROSPECTUS_KEYWORDS.get(self.business_type, ())
        return any(k in title for k in keywords)

    def fetch_projects(self, days: int = 7) -> FeedbackReport:
        """Fetch projects with feedback from the past N days."""
        import sys
        from concurrent.futures import ThreadPoolExecutor, as_completed

        session = get_session()
        cutoff = datetime.now() - timedelta(days=days)
        date_range = f"{cutoff.strftime('%Y-%m-%d')} ~ {datetime.now().strftime('%Y-%m-%d')}"

        biz_label = {"ipo": "IPO", "refinance": "再融资", "asset_purchase": "重大资产重组"}[self.business_type]
        print(f"📋 Fetching BSE {biz_label} project list...", file=sys.stderr)

        candidate_items = []
        page = 0
        while page < 100:
            resp = session.post(
                f"{self.BASE_URL}{self.LIST_API}",
                data={
                    "page": page,
                    "isNewThree": "1",
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

        print(f"📋 Found {len(candidate_items)} candidate projects, fetching details...", file=sys.stderr)

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
            p.reply.publish_date if p.reply else
            p.prospectus.publish_date if p.prospectus else ""
        ), reverse=True)

        print(f"✅ Found {len(all_projects)} {biz_label} projects matching business type", file=sys.stderr)
        return FeedbackReport(
            exchange=self.EXCHANGE,
            business_type=self.business_type,
            date_range=date_range,
            projects=all_projects,
        )

    def _process_project(self, session, item: dict, cutoff: datetime) -> ProjectFeedback | None:
        """处理单个项目，按当前 business_type 提取问询函、回复、主文件。"""
        pid = item["id"]
        company = item["stockName"]
        code = item["stockCode"]

        resp = session.post(f"{self.BASE_URL}{self.DETAIL_API}?id={pid}")
        time.sleep(config.REQUEST_DELAY)

        detail = self._parse_jsonp(resp.text)
        wxhfh = detail[0].get("wxhfhInfo", [])
        xxgk = detail[0].get("xxgkInfo", {})

        inquiry_doc = None
        reply_doc = None
        prospectus_doc = None

        # 问询函 / 回复（从 wxhfhInfo 中按 business_type 筛选）
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

            # 业务类型筛选
            if not self._business_match(title):
                continue

            pdf_url = f"{self.BASE_URL}{doc.get('destFilePath', '')}"
            exchange_dir = config.DOWNLOADS_DIR / config.EXCHANGE_NAMES[self.EXCHANGE]
            filename = self._make_filename(pub_date, company, title)
            pdf_path = exchange_dir / filename

            fb_doc = FeedbackDocument(
                exchange=self.EXCHANGE,
                company_name=company,
                stock_code=code,
                doc_type=cat,
                business_type=self.business_type,
                title=title,
                publish_date=pub_date,
                pdf_url=pdf_url,
                pdf_path=str(pdf_path),
            )

            if cat == "inquiry" and inquiry_doc is None:
                inquiry_doc = fb_doc
            elif cat == "reply" and reply_doc is None:
                reply_doc = fb_doc

        # 主文件（招股书/募集说明书/重组报告书）
        # IPO: 从 GPFXSMS.BHG 取注册稿；再融资和资产重组：扫描全部公告找主文件
        if self.business_type == "ipo":
            sms = xxgk.get("GPFXSMS", {})
            doc_list = sms.get("BHG", [])
        else:
            # 再融资和资产重组：从所有公开披露文件中过滤
            doc_list = []
            for category, items in xxgk.items():
                if isinstance(items, dict):
                    for sub_items in items.values():
                        if isinstance(sub_items, list):
                            doc_list.extend(sub_items)
                elif isinstance(items, list):
                    doc_list.extend(items)
            # 也加入 wxhfhInfo 中的文件
            doc_list.extend(wxhfh)

        for doc in doc_list:
            pub_date = doc.get("publishDate", "")
            title = doc.get("disclosureTitle", "")
            if not pub_date:
                continue
            try:
                if datetime.strptime(pub_date, "%Y-%m-%d") < cutoff:
                    continue
            except ValueError:
                continue

            if self.business_type == "ipo":
                # IPO 默认 GPFXSMS.BHG 都是注册稿
                final_title = title or "招股说明书（注册稿）"
            else:
                # 再融资/资产重组：必须命中主文件关键词
                if not self._is_prospectus_doc(title):
                    continue
                final_title = title

            pdf_url = f"{self.BASE_URL}{doc.get('destFilePath', '')}"
            exchange_dir = config.DOWNLOADS_DIR / config.EXCHANGE_NAMES[self.EXCHANGE]
            filename = self._make_filename(pub_date, company, final_title)
            pdf_path = exchange_dir / filename

            prospectus_doc = FeedbackDocument(
                exchange=self.EXCHANGE,
                company_name=company,
                stock_code=code,
                doc_type="prospectus",
                business_type=self.business_type,
                title=final_title,
                publish_date=pub_date,
                pdf_url=pdf_url,
                pdf_path=str(pdf_path),
            )
            break

        if inquiry_doc is None and reply_doc is None and prospectus_doc is None:
            return None

        return ProjectFeedback(
            company_name=company,
            stock_code=code,
            business_type=self.business_type,
            inquiry=inquiry_doc,
            reply=reply_doc,
            prospectus=prospectus_doc,
        )

    def _make_filename(self, date: str, company: str, title: str) -> str:
        """Generate a clean filename."""
        clean_title = title
        if ":" in title:
            clean_title = title.split(":", 1)[1]
        if "：" in title:
            clean_title = title.split("：", 1)[1]
        clean_title = re.sub(r'[\\/:*?"<>|]', "", clean_title).strip()
        company = re.sub(r'[\\/:*?"<>|]', "", company).strip()
        return f"{date}_{company}_{clean_title}.pdf"

    def download_and_parse(self, report: FeedbackReport, parse_text: bool = True) -> FeedbackReport:
        """Download PDFs first, then parse text."""
        import sys
        from concurrent.futures import ThreadPoolExecutor, as_completed

        session = get_session()
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
