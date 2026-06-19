"""Abstract base class for exchange scrapers."""
from abc import ABC, abstractmethod
from ..models import FeedbackReport


class ExchangeBase(ABC):
    """Base class that all exchange scrapers must implement."""

    EXCHANGE: str  # e.g. "bse", "sse", "szse"

    @abstractmethod
    def fetch_projects(self, days: int = 7) -> FeedbackReport:
        """Fetch projects with feedback from the past N days."""
        ...

    @abstractmethod
    def download_and_parse(self, report: FeedbackReport, parse_text: bool = True) -> FeedbackReport:
        """Download PDFs and optionally parse text."""
        ...
