# Normalises an LDAP filter string, tolerating bare NOT operands like AD does.
class FilterParser:

    # Initialises the cursor over the filter text.
    def __init__(self) -> None:
        self._pos = 0
        self._text = ""

    # Parses and returns a well-formed LDAP filter (or a default catch-all).
    def parse(self, filter_text: str) -> str:
        if not filter_text:
            return "(objectClass=*)"
        self._text = filter_text.strip()
        self._pos = 0
        normalized = self._read_expression()
        if self._pos != len(self._text):
            raise ValueError(f"Trailing characters at position {self._pos}")
        return normalized

    # Reads one parenthesised expression (compound or simple).
    def _read_expression(self) -> str:
        if self._pos >= len(self._text) or self._text[self._pos] != "(":
            raise ValueError(f"Expected '(' at position {self._pos}")
        self._pos += 1
        if self._pos < len(self._text) and self._text[self._pos] in "&|!":
            result = self._read_compound()
        else:
            result = self._read_simple()
        if self._pos >= len(self._text) or self._text[self._pos] != ")":
            raise ValueError(f"Expected ')' at position {self._pos}")
        self._pos += 1
        return result

    # Reads an &/|/! group, wrapping any bare operand in parentheses.
    def _read_compound(self) -> str:
        op = self._text[self._pos]
        self._pos += 1
        children = []
        while self._pos < len(self._text) and self._text[self._pos] != ")":
            if self._text[self._pos] == "(":
                children.append(self._read_expression())
            else:
                children.append(self._read_simple())
        return f"({op}{''.join(children)})"

    # Reads a simple attr=value assertion, returning it parenthesised.
    def _read_simple(self) -> str:
        start = self._pos
        while self._pos < len(self._text):
            ch = self._text[self._pos]
            if ch == "\\" and self._pos + 2 < len(self._text):
                self._pos += 3
                continue
            if ch == ")":
                break
            self._pos += 1
        if self._pos >= len(self._text):
            raise ValueError("Unterminated filter expression")
        return f"({self._text[start:self._pos]})"
