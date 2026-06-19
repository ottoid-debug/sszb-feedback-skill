"""CLI entry point for sszb-feedback.

支持 IPO / 再融资 / 重大资产重组三大业务类型。
"""
import argparse
import json
import sys
from datetime import datetime

from .exchanges.bse import BSE
from .exchanges.sse import SSE
from .exchanges.szse import SZSE
from .models import FeedbackReport, ProjectFeedback, FeedbackDocument, BusinessType
from . import config


BUSINESS_LABELS = {
    "ipo": "IPO（首次公开发行）",
    "refinance": "再融资（定增/配股/可转债）",
    "asset_purchase": "重大资产重组（发行股份购买资产）",
}

DOC_LABELS_BY_BIZ = {
    "ipo": {
        "inquiry": "审核问询函",
        "reply": "问询回复",
        "prospectus": "招股说明书（注册稿）",
    },
    "refinance": {
        "inquiry": "审核问询函",
        "reply": "问询回复",
        "prospectus": "募集说明书（注册稿）",
    },
    "asset_purchase": {
        "inquiry": "审核问询函",
        "reply": "问询回复",
        "prospectus": "重组报告书（上会稿/注册稿）",
    },
}


def fetch_report(exchange: str, business_type: str, days: int, download: bool, parse: bool) -> FeedbackReport:
    """Fetch feedback report from the specified exchange + business type."""
    if exchange == "bse":
        scraper = BSE(business_type=business_type)
    elif exchange == "sse":
        scraper = SSE(business_type=business_type)
    elif exchange == "szse":
        scraper = SZSE(business_type=business_type)
    else:
        print(f"⚠ Unknown exchange: {exchange}", file=sys.stderr)
        sys.exit(1)

    report = scraper.fetch_projects(days=days)

    if download and report.projects:
        report = scraper.download_and_parse(report, parse_text=parse)

    return report


def print_markdown(report: FeedbackReport, cleaned_files: list[str] | None = None):
    """Print raw extracted text for Agent to analyze with LLM."""
    biz_label = BUSINESS_LABELS.get(report.business_type, report.business_type)
    doc_labels = DOC_LABELS_BY_BIZ.get(report.business_type, DOC_LABELS_BY_BIZ["ipo"])

    print(f"\n# {report.exchange.upper()} {biz_label} - 审核反馈数据")
    print(f"**时间范围**: {report.date_range}\n")

    if not report.projects:
        print("本期间无新增审核反馈或主文件公告。\n")
        return

    inquiry_count = sum(1 for p in report.projects if p.inquiry)
    reply_count = sum(1 for p in report.projects if p.reply)
    prospectus_count = sum(1 for p in report.projects if p.prospectus)
    parts = []
    if inquiry_count:
        parts.append(f"{doc_labels['inquiry']} **{inquiry_count}**")
    if reply_count:
        parts.append(f"{doc_labels['reply']} **{reply_count}**")
    if prospectus_count:
        parts.append(f"{doc_labels['prospectus']} **{prospectus_count}**")
    print(f"共 **{len(report.projects)}** 个项目有更新：{', '.join(parts)}\n")
    print("---\n")

    for project in report.projects:
        code_str = f" ({project.stock_code})" if project.stock_code else ""
        print(f"## {project.company_name}{code_str}\n")

        for doc, label_key in [(project.inquiry, "inquiry"),
                                (project.reply, "reply"),
                                (project.prospectus, "prospectus")]:
            if doc is None:
                continue
            print(f"### {doc_labels[label_key]}\n")
            print(f"- 披露日期: {doc.publish_date}")
            print(f"- 标题: {doc.title}")
            print(f"- PDF: {doc.pdf_url}\n")
            if doc.content_text and not doc.content_text.startswith("["):
                preview_limit = 10000 if label_key == "prospectus" else 50000
                shown = doc.content_text[:preview_limit]
                print(f"**正文文本（已抽取）:**\n")
                print(f"```\n{shown}\n```\n")
                if len(doc.content_text) > preview_limit:
                    print(f"*[已截断: 完整正文 {len(doc.content_text)} 字, 显示前 {preview_limit} 字]*\n")
            else:
                print(f"*(正文未抽取或下载失败)*\n")

        print("---\n")

    if cleaned_files:
        print(f"**清理**: {len(cleaned_files)} 个 30 天前文件已移入回收站")


def print_json(report: FeedbackReport):
    """Print report as JSON to stdout."""
    def doc_to_dict(doc: FeedbackDocument | None) -> dict | None:
        if doc is None:
            return None
        return {
            "doc_type": doc.doc_type,
            "business_type": doc.business_type,
            "title": doc.title,
            "publish_date": doc.publish_date,
            "pdf_url": doc.pdf_url,
            "pdf_path": doc.pdf_path,
            "content_text": doc.content_text,
        }

    output = {
        "exchange": report.exchange,
        "business_type": report.business_type,
        "business_label": BUSINESS_LABELS.get(report.business_type, report.business_type),
        "date_range": report.date_range,
        "projects": [
            {
                "company_name": p.company_name,
                "stock_code": p.stock_code,
                "business_type": p.business_type,
                "inquiry": doc_to_dict(p.inquiry),
                "reply": doc_to_dict(p.reply),
                "prospectus": doc_to_dict(p.prospectus),
            }
            for p in report.projects
        ],
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(
        prog="sszb-feedback",
        description="沪深北 Deal Feedback Skill — 抓取并解析三家交易所 IPO / 再融资 / 重大资产重组的审核反馈材料",
    )
    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    fetch_parser = subparsers.add_parser("fetch", help="抓取审核反馈材料")
    fetch_parser.add_argument(
        "--exchange", "-e",
        choices=["bse", "sse", "szse", "all"],
        default="bse",
        help="交易所，默认 bse（all 为三家全部）",
    )
    fetch_parser.add_argument(
        "--business-type", "-b",
        choices=["ipo", "refinance", "asset_purchase", "all"],
        default="ipo",
        help="业务类型（ipo=首发 / refinance=再融资 / asset_purchase=发行股份购买资产 / all=全部三类）",
    )
    fetch_parser.add_argument(
        "--days", "-d",
        type=int,
        default=1,
        choices=range(1, 41),
        metavar="[1-40]",
        help="回看天数，最多 40 天（默认 1，即昨天）",
    )
    fetch_parser.add_argument(
        "--no-download",
        action="store_true",
        help="只列文件不下载 PDF",
    )
    fetch_parser.add_argument(
        "--no-parse",
        action="store_true",
        help="下 PDF 但不抽文字",
    )
    fetch_parser.add_argument(
        "--format", "-f",
        choices=["markdown", "json"],
        default="markdown",
        help="输出格式（默认 markdown）",
    )

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    if args.command == "fetch":
        from .cleanup import cleanup_old_files
        cleaned = cleanup_old_files(config.DOWNLOADS_DIR, max_age_days=30)

        exchanges = ["bse", "sse", "szse"] if args.exchange == "all" else [args.exchange]
        biz_types = ["ipo", "refinance", "asset_purchase"] if args.business_type == "all" else [args.business_type]

        for biz in biz_types:
            for ex in exchanges:
                try:
                    report = fetch_report(
                        exchange=ex,
                        business_type=biz,
                        days=args.days,
                        download=not args.no_download,
                        parse=not args.no_parse and not args.no_download,
                    )
                    if args.format == "json":
                        print_json(report)
                    else:
                        print_markdown(report, cleaned_files=cleaned)
                except NotImplementedError:
                    print(f"⚠ {ex.upper()} {biz} 暂未实现，跳过", file=sys.stderr)
                except Exception as e:
                    print(f"✗ {ex.upper()} {biz} 抓取出错: {e}", file=sys.stderr)
                    import traceback
                    traceback.print_exc(file=sys.stderr)


if __name__ == "__main__":
    main()
