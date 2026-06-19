"""Prospectus key information extractor.

Extracts main business, industry, and financial data from the
overview section (第二节 概览) of a prospectus registration draft.
"""
import re
from pathlib import Path
import pdfplumber


def extract_prospectus_summary(pdf_path: Path, max_pages: int = 50) -> dict:
    """Extract key info from a prospectus PDF.

    Returns dict with: company_name, main_business, financials.
    """
    if not pdf_path.exists():
        return {"error": f"File not found: {pdf_path}"}

    try:
        with pdfplumber.open(pdf_path) as pdf:
            total_pages = len(pdf.pages)
            result = {
                "company_name": "",
                "main_business": "",
                "financials": {},
            }

            # Flatten all overview pages into one text (use more pages for SZSE)
            overview_text = ""
            for i in range(min(max_pages, total_pages)):
                text = pdf.pages[i].extract_text()
                if text:
                    overview_text += text + "\n"

            flat = overview_text.replace('\n', '')

            # Extract company name from page 1
            page1 = (pdf.pages[0].extract_text() or "").replace('\n', '')
            name_match = re.search(r"([一-龥]{2,20}(?:股份|有限)公司)", page1)
            if name_match:
                result["company_name"] = name_match.group(1)

            # --- Extract from 概览 section ---
            # Try different section title variations, skip TOC entries
            biz_start = -1
            for pattern in ["发行人主营业务情况", "发行人主营业务经营情况"]:
                idx = flat.find(pattern)
                # Skip TOC entries (followed by "...." dots)
                while idx >= 0 and idx + len(pattern) + 20 < len(flat):
                    after = flat[idx + len(pattern):idx + len(pattern) + 20]
                    if "...." in after:
                        idx = flat.find(pattern, idx + 1)
                    else:
                        biz_start = idx
                        break

            fin_start = -1
            fin_pattern = "主要财务数据"
            idx = flat.find(fin_pattern)
            while idx >= 0 and idx + len(fin_pattern) + 20 < len(flat):
                after = flat[idx + len(fin_pattern):idx + len(fin_pattern) + 20]
                if "...." in after:
                    idx = flat.find(fin_pattern, idx + 1)
                else:
                    fin_start = idx
                    break
            risk_start = flat.find("第三节 风险因素")

            # Main business
            if biz_start >= 0:
                biz_end = fin_start if fin_start > biz_start else (risk_start if risk_start > biz_start else biz_start + 3000)
                biz_text = flat[biz_start:biz_end]
                result["main_business"] = _clean_text(biz_text[:1500])

            # Financials
            if fin_start >= 0:
                fin_end = risk_start if risk_start > fin_start else fin_start + 3000
                fin_text = flat[fin_start:fin_end]
                result["financials"] = _extract_financials(fin_text)

            return result

    except Exception as e:
        return {"error": str(e)}


def _clean_text(text: str) -> str:
    """Clean extracted text: remove page markers, normalize spaces."""
    text = re.sub(r'\d+-\d+-\d+', '', text)  # Remove page markers like 1-1-13
    text = re.sub(r'\s+', ' ', text)
    text = text.strip()
    # Split into sentences and take the first few
    sentences = [s.strip() for s in re.split(r'(?<=[。])', text) if len(s.strip()) > 10]
    return ' '.join(sentences[:8])


def _extract_financials(text: str) -> dict:
    """Extract key financial data from the financial overview section."""
    financials = {}

    # Pattern: "营业收入(元) 214,940,632.42 184,823,028.85 173,911,217.01"
    rev_match = re.search(r"营业收入\(元\)\s*([\d,.]+)\s*([\d,.]+)\s*([\d,.]+)", text)
    if rev_match:
        financials["revenue"] = [rev_match.group(i).replace(',', '') for i in range(1, 4)]

    # Pattern: "净利润(元) 70,808,655.38 69,194,377.44 70,181,581.38" or negative values
    profit_match = re.search(r"净利润\(元\)\s*(-?[\d,.]+)\s*(-?[\d,.]+)\s*(-?[\d,.]+)", text)
    if profit_match:
        financials["net_profit"] = [profit_match.group(i).replace(',', '') for i in range(1, 4)]

    # Gross margin: "毛利率（%） 74.41 78.80 75.88"
    gm_match = re.search(r"毛利率[（(]%[）)]\s*([\d.]+)\s*([\d.]+)\s*([\d.]+)", text)
    if gm_match:
        financials["gross_margin"] = [f"{gm_match.group(i)}%" for i in range(1, 4)]

    # ROE: "加权平均净资产收益率（%）"
    roe_match = re.search(r"加权平均净资产收益率[（(]%[）)]\s*([\d.]+)\s*([\d.]+)\s*([\d.]+)", text)
    if roe_match:
        financials["roe"] = [f"{roe_match.group(i)}%" for i in range(1, 4)]

    # Revenue growth from narrative
    rev_growth = re.search(r"营业收入分别为([\d,.]+)\s*万元.*?([\d,.]+)\s*万元.*?([\d,.]+)\s*万元", text)
    if rev_growth:
        financials["revenue_wan"] = [rev_growth.group(i) for i in range(1, 4)]

    # SSE format: "营业收入（万元） 196,109.87 169,287.62 126,963.90"
    rev_match_wan = re.search(r"营业收入[（(]万元[）)]\s*([\d,.]+)\s*([\d,.]+)\s*([\d,.]+)", text)
    if rev_match_wan:
        financials["revenue"] = [rev_match_wan.group(i).replace(',', '') for i in range(1, 4)]

    # SSE format: "净利润（万元） 36,118.30 33,237.63 11,676.54" or negative values
    profit_match_wan = re.search(r"净利润[（(]万元[）)]\s*(-?[\d,.]+)\s*(-?[\d,.]+)\s*(-?[\d,.]+)", text)
    if profit_match_wan:
        financials["net_profit"] = [profit_match_wan.group(i).replace(',', '') for i in range(1, 4)]

    # SSE format: "加权平均净资产收益率 22.66% 25.90% 7.15%"
    roe_match_sse = re.search(r"加权平均净资产收益率\s+([\d.]+%)\s+([\d.]+%)\s+([\d.]+%)", text)
    if roe_match_sse:
        financials["roe"] = [roe_match_sse.group(i) for i in range(1, 4)]

    # SZSE format: negative ROE like "-61.16% -37.30% -23.87%"
    roe_match_neg = re.search(r"加权平均净资产收益率\s+(-?[\d.]+%)\s+(-?[\d.]+%)\s+(-?[\d.]+%)", text)
    if roe_match_neg:
        financials["roe"] = [roe_match_neg.group(i) for i in range(1, 4)]

    return financials
