"""Auto-cleanup old downloaded PDFs (move to trash)."""
import sys
from datetime import datetime, timedelta
from pathlib import Path
from send2trash import send2trash


def cleanup_old_files(download_dir: Path, max_age_days: int = 30) -> list[str]:
    """Move PDF files older than max_age_days to trash.

    Returns list of deleted filenames.
    """
    if not download_dir.exists():
        return []

    cutoff = datetime.now() - timedelta(days=max_age_days)
    deleted = []

    for pdf_file in download_dir.rglob("*.pdf"):
        try:
            mtime = datetime.fromtimestamp(pdf_file.stat().st_mtime)
            if mtime < cutoff:
                send2trash(str(pdf_file))
                deleted.append(pdf_file.name)
        except OSError:
            pass

    if deleted:
        print(f"🗑️  Moved {len(deleted)} old files to trash (>{max_age_days} days)", file=sys.stderr)

    return deleted
