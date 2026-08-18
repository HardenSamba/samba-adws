import html
from typing import Any, List, Optional, Sequence, Tuple

from src.soap.namespaces import CUSTOM_ACTIONS, XSI

SERA = "http://schemas.microsoft.com/2003/10/Serialization/Arrays"

FieldPlan = Sequence[Tuple[str, str, str]]


class CaElement:

    @staticmethod
    def text(tag: str, value: Any) -> str:
        if value is None:
            return f'<{tag} xsi:nil="true"></{tag}>'
        return f"<{tag}>{html.escape(str(value))}</{tag}>"

    @staticmethod
    def array(tag: str, values: Optional[List[str]]) -> str:
        if values is None:
            return f'<{tag} xsi:nil="true" xmlns:sera="{SERA}"></{tag}>'
        items = "".join(
            f"<sera:string>{html.escape(str(v))}</sera:string>" for v in values
        )
        return f'<{tag} xmlns:sera="{SERA}">{items}</{tag}>'

    @staticmethod
    def response(operation: str, member: str, inner: str) -> str:
        return (
            f'<{operation} xmlns="{CUSTOM_ACTIONS}">'
            f'<{member} xmlns:xsi="{XSI}">{inner}</{member}>'
            f"</{operation}>"
        )

    @classmethod
    def fields(cls, plan: FieldPlan, data: Any) -> str:
        return "".join(cls._one(kind, tag, data.get(key)) for kind, tag, key in plan)

    @classmethod
    def _one(cls, kind: str, tag: str, value: Any) -> str:
        if kind == "array":
            return cls.array(tag, value)
        return cls.text(tag, value)
