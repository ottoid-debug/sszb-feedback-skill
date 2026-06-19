# 待补充的交易所 API endpoint

本项目当前完整实现的是 **三家交易所 IPO 业务** 的抓取。

再融资 / 资产重组的 API endpoint 还需 reverse engineer 后补充。框架已经预留好接口（`--business-type refinance / asset_purchase`），加完 endpoint 后立即可用。

## 待补充清单

### 北交所 BSE

| 业务 | 状态 | 备注 |
|------|------|------|
| IPO 公开发行 | ✅ 已实现 | `projectNewsController/infoResult.do` |
| 定向发行（再融资） | 🚧 待补充 | 北交所定向发行（再融资）走独立的披露 controller，不在 `projectNewsController` 范围内。需要找到对应 list/detail API |
| 重大资产重组 | 🚧 待补充 | 同上，走独立的披露入口 |

**研究方向**：
- 北交所主站 `https://www.bse.cn/` 的"信息披露"或"重大事项"频道
- 可能的入口：`dxsfController`（定向发行）、`zlzcController`（重大资产）等
- F12 看 Network 面板，找触发审核动态列表加载的 XHR 请求

### 上交所 SSE

| 业务 | 状态 | 备注 |
|------|------|------|
| IPO 主板/科创板 | ✅ 已实现 | `https://query.sse.com.cn/commonSoaQuery.do?fileTypeMap=I3010` |
| 再融资 | 🚧 待补充 | 上交所再融资审核动态：`https://listing.sse.com.cn/projectdynamic/refinance/list/` 或类似 |
| 重大资产重组 | 🚧 待补充 | `https://listing.sse.com.cn/projectdynamic/restructure/list/` 或类似 |

### 深交所 SZSE

| 业务 | 状态 | 备注 |
|------|------|------|
| IPO 主板/创业板 | ✅ 已实现 | `https://listing.szse.cn/api/disclose/...` |
| 再融资 | 🚧 待补充 | 深交所再融资入口待找 |
| 重大资产重组 | 🚧 待补充 | 深交所并购重组入口待找 |

## 实现方式

新增 endpoint 后，**框架代码无需重大改动**：

1. 在 `sszb_feedback/exchanges/{bse,sse,szse}.py` 的 `fetch_projects` 内：
   - 根据 `self.business_type` 切换不同 list API URL
   - 调整字段解析（不同业务的响应结构可能略有差异）
2. `BusinessType.from_title()` 已经能正确识别公告标题归属业务类型，分类逻辑无需改

## 临时绕过方式

在这些 endpoint 补全之前，**LLM 仍然可以基于 IPO 数据写承做/承揽报告**，因为：
- BSE IPO 数据已包含中国市场 80% 以上的待审项目
- 投行视角报告模板（见 `SKILL.md`）对所有业务类型通用
- 再融资/重组的项目数据可暂时让用户手工提供 PDF，Agent 解析后套用同一模板

欢迎 PR 补充 endpoint。
