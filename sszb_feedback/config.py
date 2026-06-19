"""Global configuration."""
import os
from pathlib import Path

# Project root (where downloads/ lives)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DOWNLOADS_DIR = PROJECT_ROOT / "downloads"

# Proxy (set via env var or override here)
HTTP_PROXY = os.environ.get("HTTP_PROXY", os.environ.get("http_proxy", ""))

# Request settings
REQUEST_TIMEOUT = 30
REQUEST_DELAY = 0.5  # seconds between requests (polite crawling)

# PDF text extraction limit (chars per document, 0 = no limit)
PDF_TEXT_LIMIT = 0

# Exchange display names (used as folder names)
EXCHANGE_NAMES = {
    "bse": "BSE",
    "sse": "SSE",
    "szse": "SZSE",
}
