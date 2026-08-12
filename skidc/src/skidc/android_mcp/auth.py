from __future__ import annotations

from pathlib import Path
from secrets import compare_digest
from typing import Literal


AuthorizationResult = Literal["disabled", "missing", "invalid", "accepted"]


class BearerTokenAuth:
    """Validate one operator-provided Bridge token without exposing its value."""

    def __init__(self, token: str | None = None, *, disabled: bool = False) -> None:
        self._token = token.encode("utf-8") if token is not None else None
        self._disabled = disabled

    @classmethod
    def from_file(cls, token_file: Path | None) -> "BearerTokenAuth":
        if token_file is None:
            return cls(disabled=True)
        if not token_file.is_file():
            raise ValueError("token file must be a regular file")
        token = token_file.read_text(encoding="utf-8").strip()
        if not token:
            raise ValueError("token file must not be empty")
        if any(character.isspace() for character in token):
            raise ValueError("token file must contain one token without whitespace")
        return cls(token)

    def authorize(self, authorization: str | None) -> AuthorizationResult:
        if self._disabled:
            return "disabled"
        if authorization is None:
            return "missing"
        scheme, separator, credential = authorization.partition(" ")
        if not separator or scheme.casefold() != "bearer" or not credential:
            return "missing"
        if self._token is None or not compare_digest(
            credential.encode("utf-8"),
            self._token,
        ):
            return "invalid"
        return "accepted"
