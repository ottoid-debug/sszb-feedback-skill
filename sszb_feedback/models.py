"""Data models for SSZB (沪深北) deal feedback documents.

Covers three business types:
  - IPO 首次公开发行（BSE/SSE/SZSE 审核）
  - REFINANCE 再融资（定增/配股/可转债等）
  - ASSET_PURCHASE 发行股份购买资产（重大资产重组）
"""
from dataclasses import dataclass, field
from enum import Enum


class BusinessType(str, Enum):
    """业务类型."""
    IPO = "ipo"                       # 首次公开发行
    REFINANCE = "refinance"           # 再融资
    ASSET_PURCHASE = "asset_purchase" # 发行股份购买资产（重大资产重组）

    @classmethod
    def from_title(cls, title: str) -> "BusinessType":
        """根据公告标题判断业务类型。"""
        if not title:
            return cls.IPO
        # 资产重组 / 发行股份购买资产
        if any(kw in title for kw in (
            "发行股份购买资产", "重大资产重组", "吸收合并",
            "重组报告书", "重组草案", "重组之审核",
        )):
            return cls.ASSET_PURCHASE
        # 再融资
        if any(kw in title for kw in (
            "非公开发行", "向特定对象发行", "定向增发", "定增",
            "公开发行可转换公司债券", "可转债", "公开增发", "配股",
            "募集说明书", "向不特定对象发行可转换公司债券",
        )):
            return cls.REFINANCE
        # 默认 IPO
        return cls.IPO


@dataclass
class FeedbackDocument:
    """A single disclosure document (inquiry letter, reply, prospectus, offering memorandum, etc.)."""
    exchange: str           # "bse" / "sse" / "szse"
    company_name: str       # Company short name
    stock_code: str         # Stock code
    doc_type: str           # "inquiry" / "reply" / "prospectus" / "offering_memo" / "restructure_report"
    business_type: str = "ipo"  # BusinessType value (ipo / refinance / asset_purchase)
    title: str = ""         # Document title
    publish_date: str = ""  # Publication date YYYY-MM-DD
    pdf_url: str = ""       # PDF download URL
    pdf_path: str = ""      # Local save path
    content_text: str = ""  # Extracted text content


@dataclass
class ProjectFeedback:
    """Feedback documents for a single deal project (IPO / refinancing / asset restructuring)."""
    company_name: str
    stock_code: str
    business_type: str = "ipo"  # 项目所属业务大类
    inquiry: FeedbackDocument | None = None      # 审核问询函
    reply: FeedbackDocument | None = None        # 问询回复
    prospectus: FeedbackDocument | None = None   # 招股说明书 / 募集说明书 / 重组报告书
    # 注：prospectus 字段在不同业务类型下含义不同：
    #   ipo            -> 招股说明书（注册稿）
    #   refinance      -> 募集说明书 / 发行情况报告书
    #   asset_purchase -> 重组报告书（草案/上会稿/注册稿）


@dataclass
class FeedbackReport:
    """A collection of feedback from one exchange + one business type."""
    exchange: str
    business_type: str = "ipo"
    date_range: str = ""
    projects: list[ProjectFeedback] = field(default_factory=list)
