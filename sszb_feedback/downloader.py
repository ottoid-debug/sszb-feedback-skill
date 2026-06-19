"""PDF downloader with proxy support."""
import time
import requests
from pathlib import Path
from . import config


def _build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
    })
    if config.HTTP_PROXY:
        session.proxies = {
            "http": config.HTTP_PROXY,
            "https": config.HTTP_PROXY,
        }
    return session


def download_pdf(url: str, save_path: Path, session: requests.Session | None = None) -> bool:
    """Download a PDF file. Returns True on success."""
    if session is None:
        session = _build_session()

    save_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        resp = session.get(url, timeout=config.REQUEST_TIMEOUT)
        resp.raise_for_status()

        # Verify it's actually a PDF (check first bytes)
        if resp.content[:4] != b"%PDF":
            print(f"  ⚠ Not a valid PDF: {url}", file=__import__('sys').stderr)
            return False

        with open(save_path, "wb") as f:
            f.write(resp.content)
        return True
    except requests.RequestException as e:
        print(f"  ✗ Download failed: {url} — {e}", file=__import__('sys').stderr)
        return False


def get_session() -> requests.Session:
    """Get a configured session for BSE (with cookie initialization)."""
    session = _build_session()
    # BSE requires cookie initialization
    session.get("https://www.bse.cn/audit/project_news.html", timeout=config.REQUEST_TIMEOUT)
    time.sleep(config.REQUEST_DELAY)
    return session
