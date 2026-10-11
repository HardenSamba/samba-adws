from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, List, Optional


@dataclass
class EnumerationContext:
    context_id: str
    created_at: datetime
    expires_at: datetime
    base_dn: str
    search_filter: str
    attributes: List[str] = field(default_factory=list)
    cached_results: List[Any] = field(default_factory=list)
    result_index: int = 0
    session_id: Optional[str] = None
    query: Optional[Any] = None

    @property
    def is_expired(self) -> bool:
        return datetime.utcnow() > self.expires_at

    @property
    def is_end_of_sequence(self) -> bool:
        return self.result_index >= len(self.cached_results)

    def get_next_batch(self, max_elements: int = 100) -> List[Any]:
        if self.is_end_of_sequence:
            return []
        start = self.result_index
        end = min(start + max_elements, len(self.cached_results))
        batch = self.cached_results[start:end]
        self.result_index = end
        return batch
