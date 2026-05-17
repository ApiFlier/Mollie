from abc import ABC, abstractmethod


class BaseAdapter(ABC):
    source_key: str = None
    display_name: str = None

    @abstractmethod
    def fetch(self, coverage_days=60) -> list:
        """Fetch source data and return a list of normalized event dicts."""
        pass
