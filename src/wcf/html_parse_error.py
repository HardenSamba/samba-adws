from typing import Tuple, Optional

class HTMLParseError(Exception):
    """Exception raised for all parse errors."""

    def __init__(self, msg: str, position: Tuple[Optional[int], Optional[int]] = (None, None)):
        # Déclaration initiale
        self.msg: str = msg
        self.lineno: Optional[int] = position[0]
        self.offset: Optional[int] = position[1]
        super().__init__(self.msg)

    def __str__(self) -> str:
        # Déclaration initiale
        result: str = self.msg
        
        if self.lineno is not None:
            result = f"{result}, at line {self.lineno}"
        if self.offset is not None:
            result = f"{result}, column {self.offset + 1}"
        return result