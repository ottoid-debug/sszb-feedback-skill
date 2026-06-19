# 沪深北 Deal Feedback Skill

[![BSE](https://img.shields.io/badge/BSE-IPO%20%2B%20再融资%20%2B%20重组-brightgreen)](#) [![SSE](https://img.shields.io/badge/SSE-IPO-brightgreen)](#) [![SZSE](https://img.shields.io/badge/SZSE-IPO-brightgreen)](#) [![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](#) [![License](https://img.shields.io/badge/License-MIT-green)](#)

> 一站式抓取沪深北三家交易所 **IPO / 再融资 / 重大资产重组** 三大业务类型的审核反馈材料（问询函、回复、招股书、募集说明书、重组报告书），从 **投行承做 + 承揽双视角** 输出结构化分析。

本项目在 [corylcr/ipo-feedback-skill](https://github.com/corylcr/ipo-feedback-skill) 基础上扩展，新增再融资 / 资产重组业务类型 + 投行视角报告模板。MIT 协议。

## 业务覆盖

| 业务类型 | BSE 北交所 | SSE 上交所 | SZSE 深交所 |
|----------|-----------|-----------|-----------|
| **IPO 首发** | ✅ 问询 + 回复 + 招股书 | ✅ 回复 + 招股书 | ✅ 回复 + 招股书 |
| **再融资**（定增/配股/可转债） | 🚧 endpoint 待补充 | 🚧 待实现 | 🚧 待实现 |
| **重大资产重组**（发行股份购买资产） | 🚧 endpoint 待补充 | 🚧 待实现 | 🚧 待实现 |

> **当前状态**：三家 IPO 业务已完整覆盖。北交所再融资/重组走独立 controller，框架已预留 `--business-type refinance/asset_purchase` 接口与分类器（含 BusinessType.from_title 标题分类逻辑），endpoint 补全后立即可用。详见 [TODO_ENDPOINTS.md](./TODO_ENDPOINTS.md)。上交所/深交所不公开问询函原件，只发布回复 + 主文件。

## 安装

```bash
git clone https://github.com/ottoid/sszb-feedback-skill.git
cd sszb-feedback-skill
pip install -e ".[all]"   # 含 playwright（上交所抓取需要）
py -3.12 -m playwright install chromium   # 首次需下载约 200MB
```

装完获得全局命令 `sszb-feedback`。

## 快速开始

```bash
# 默认：抓昨天北交所 IPO
sszb-feedback fetch

# 抓近 7 天三家交易所 IPO，JSON 输出
sszb-feedback fetch --exchange all --days 7 --format json

# 抓近 30 天北交所再融资
sszb-feedback fetch --exchange bse --business-type refinance --days 30

# 抓近 30 天北交所资产重组
sszb-feedback fetch --exchange bse --business-type asset_purchase --days 30

# 抓三家 × 三业务 全量
sszb-feedback fetch --exchange all --business-type all --days 7

# 只列文件清单不下 PDF（最快）
sszb-feedback fetch --exchange all --days 7 --no-download
```

## 投行视角双视角报告模板

详见 [`SKILL.md`](./SKILL.md)，含：

- **承做视角模板**：问询函 Q&A 拆解、主文件概览章节摘要、底稿对照启示、监管口径变化信号
- **承揽视角模板**：新增受理项目表、重点行业分析、保荐机构市场份额、撤回项目跟踪、市场观察

并对各家交易所招股书/募集说明书/重组报告书的 **概览章节** 精细化抽取规范作了说明（必抽指标、章节定位口径、北交所与沪深所的章节差异）。

## 输出 JSON 结构

```jsonc
{
  "exchange": "bse",
  "business_type": "refinance",
  "business_label": "再融资（定增/配股/可转债）",
  "date_range": "YYYY-MM-DD ~ YYYY-MM-DD",
  "projects": [
    {
      "company_name": "公司名",
      "stock_code": "代码",
      "business_type": "refinance",
      "inquiry":    { "title": "...", "publish_date": "...", "pdf_url": "...", "content_text": "..." },
      "reply":      { "title": "...", "publish_date": "...", "pdf_url": "...", "content_text": "..." },
      "prospectus": { "title": "募集说明书", ... }
    }
  ]
}
```

## 与原项目的差异（致谢与扩展）

| 维度 | 原项目 [corylcr/ipo-feedback-skill](https://github.com/corylcr/ipo-feedback-skill) | 本项目 |
|------|-----------------------------------------------------------------------------------|--------|
| 业务类型 | IPO 首发 | IPO + 再融资 + 重大资产重组 |
| CLI 命令 | `ipo-feedback` | `sszb-feedback` |
| 包名 | `ipo_feedback` | `sszb_feedback` |
| 业务参数 | — | `--business-type {ipo, refinance, asset_purchase, all}` |
| 北交所覆盖 | IPO | IPO + 再融资 + 重组（同一披露系统按标题关键词分类） |
| 报告模板 | 仅 IPO，简单结构 | 投行承做 + 承揽双视角，含概览章节精细化抽取规范 |
| 主文件类型 | 招股书（注册稿） | 招股书 / 募集说明书 / 重组报告书 |

致谢原作者 [@corylcr](https://github.com/corylcr) 的抓取框架。

## License

MIT，与原项目一致。
