from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import os

from . import _utils


@dataclass(frozen=True)
class CryptoOutput:
    """
    Minimal wrapper for an encrypted artifact.
    """

    content: bytes
    created_at: datetime
    content_hash: str

    @classmethod
    def create(
        cls,
        content: bytes,
        *,
        created_at: datetime | None = None,
    ) -> "CryptoOutput":
        if created_at is None:
            created_at = datetime.now(timezone.utc)
        return cls(
            content=content,
            created_at=created_at,
            content_hash=hashlib.sha256(content).hexdigest(),
        )

    @property
    def size(self) -> int:
        return len(self.content)

    def to_bytes(self) -> bytes:
        return self.content

    def to_string(self, encoding: str = "utf-8") -> str:
        return self.content.decode(encoding)

    def to_clipboard(self, encoding: str = "utf-8") -> str:
        """
        Copy the encrypted artifact to the system clipboard as text.
        """
        return _utils.copy_text_to_clipboard(self.to_string(encoding=encoding))

    def to_file(
        self,
        file_path: str,
        *,
        encoding: str = "utf-8",
        overwrite: bool = False,
        binary: bool = False,
    ) -> str:
        path = os.path.abspath(os.path.expanduser(file_path))
        parent_dir = os.path.dirname(path)
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)

        if os.path.exists(path) and not overwrite:
            raise FileExistsError(
                f"Output file already exists: {path}. "
                "Set overwrite=True to overwrite it."
            )

        if binary:
            with open(path, "wb") as file_obj:
                file_obj.write(self.content)
        else:
            with open(path, "w", encoding=encoding, newline="\n") as file_obj:
                file_obj.write(self.to_string(encoding=encoding))

        return path

    def __repr__(self) -> str:
        return f"CryptoOutput(size={self.size}, hash={self.content_hash[:12]!r})"

    def __str__(self) -> str:
        return (
            "CryptoOutput\n"
            f"  size: {self.size} bytes\n"
            f"  created_at: {self.created_at.isoformat()}\n"
            f"  hash: {self.content_hash[:12]}"
        )
