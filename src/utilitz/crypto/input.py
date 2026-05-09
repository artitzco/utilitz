from __future__ import annotations

from dataclasses import dataclass, field
import io
import hashlib
import os
import pickle
import zipfile
from pathlib import Path
from typing import Any


def _normalize_exclude_patterns(
    exclude_patterns: str | list[str] | tuple[str, ...] | None,
) -> tuple[str, ...]:
    if exclude_patterns is None:
        return ()
    if isinstance(exclude_patterns, str):
        return (exclude_patterns,)
    return tuple(exclude_patterns)


def _normalize_include_patterns(
    include_patterns: str | list[str] | tuple[str, ...] | None,
) -> tuple[str, ...]:
    if include_patterns is None:
        return ()
    if isinstance(include_patterns, str):
        return (include_patterns,)
    return tuple(include_patterns)


def _collect_globbed_paths(base_path: Path, patterns: tuple[str, ...]) -> set[str]:
    matched: set[str] = set()
    for pattern in patterns:
        for candidate in base_path.glob(pattern):
            try:
                rel_path = candidate.relative_to(base_path).as_posix()
            except ValueError:
                continue
            if rel_path:
                matched.add(rel_path)
    return matched


def pack_directory_to_zip_bytes(
    directory_path: str,
    *,
    include_patterns: str | list[str] | tuple[str, ...] | None = None,
    exclude_patterns: str | list[str] | tuple[str, ...] | None = None,
) -> bytes:
    fixed_timestamp = (1980, 1, 1, 0, 0, 0)
    file_mode = 0o100644
    dir_mode = 0o040755
    include = _normalize_include_patterns(include_patterns)
    exclude = _normalize_exclude_patterns(exclude_patterns)

    buffer = io.BytesIO()
    base_path = Path(directory_path).resolve()
    root_dir_name = base_path.name
    included_paths = _collect_globbed_paths(base_path, include) if include else None
    excluded_paths = _collect_globbed_paths(base_path, exclude) if exclude else set()

    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        root_info = zipfile.ZipInfo(f"{root_dir_name}/", date_time=fixed_timestamp)
        root_info.compress_type = zipfile.ZIP_DEFLATED
        root_info.external_attr = dir_mode << 16
        zf.writestr(root_info, b"")

        for current_root, dirs, files in os.walk(base_path):
            current_path = Path(current_root)
            dirs[:] = sorted(
                d
                for d in dirs
                if (current_path / d).relative_to(base_path).as_posix() not in excluded_paths
            )
            files.sort()

            rel_root = "" if current_path == base_path else current_path.relative_to(base_path).as_posix()

            if not files and not dirs and current_path != base_path:
                zip_dir = f"{root_dir_name}/{rel_root}/" if rel_root else f"{root_dir_name}/"
                if included_paths is not None and rel_root not in included_paths:
                    continue
                if rel_root in excluded_paths:
                    continue
                dir_info = zipfile.ZipInfo(zip_dir, date_time=fixed_timestamp)
                dir_info.compress_type = zipfile.ZIP_DEFLATED
                dir_info.external_attr = dir_mode << 16
                zf.writestr(dir_info, b"")

            for filename in files:
                abs_file = os.path.join(current_root, filename)
                rel_file = (current_path / filename).relative_to(base_path).as_posix()
                if included_paths is not None and rel_file not in included_paths:
                    continue
                if rel_file in excluded_paths:
                    continue
                arcname = os.path.join(root_dir_name, rel_file).replace("\\", "/")
                file_info = zipfile.ZipInfo(arcname, date_time=fixed_timestamp)
                file_info.compress_type = zipfile.ZIP_DEFLATED
                file_info.external_attr = file_mode << 16
                with open(abs_file, "rb") as file_obj:
                    zf.writestr(file_info, file_obj.read())

    return buffer.getvalue()


@dataclass(frozen=True)
class CryptoInput:
    """
    Normalized crypto-ready input.

    The payload is always stored as bytes because that is the most natural
    representation for cryptographic primitives. Metadata is kept separately so
    callers can preserve origin information such as name and source kind.
    """

    content: bytes
    kind: str
    metadata: dict[str, Any] = field(default_factory=dict)
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "content_hash",
            hashlib.sha256(self.content).hexdigest(),
        )

    @property
    def size(self) -> int:
        return len(self.content)

    def to_bytes(self) -> bytes:
        return self.content

    def __repr__(self) -> str:
        return (
            f"CryptoInput(kind={self.kind!r}, size={self.size}, "
            f"content_hash={self.content_hash!r}, metadata={self.metadata!r})"
        )

    def __str__(self) -> str:
        return f"CryptoInput<{self.kind}, {self.size} bytes>"

    @classmethod
    def from_string(
        cls,
        text: str,
        *,
        encoding: str = "utf-8",
    ) -> "CryptoInput":
        if not isinstance(text, str):
            raise TypeError("text must be a string.")
        return cls(content=text.encode(encoding), kind="text", metadata={"encoding": encoding})

    @classmethod
    def from_file(
        cls,
        file_path: str | os.PathLike[str],
    ) -> "CryptoInput":
        path = os.path.abspath(os.path.expanduser(os.fspath(file_path)))
        if not os.path.isfile(path):
            raise FileNotFoundError(f"Input file not found: {path}")

        with open(path, "rb") as file_obj:
            content = file_obj.read()

        metadata = {"filename": os.path.basename(path)}
        return cls(content=content, kind="file", metadata=metadata)

    @classmethod
    def from_directory(
        cls,
        directory_path: str | os.PathLike[str],
        *,
        include_patterns: str | list[str] | tuple[str, ...] | None = None,
        exclude_patterns: str | list[str] | tuple[str, ...] | None = None,
    ) -> "CryptoInput":
        path = os.path.abspath(os.path.expanduser(os.fspath(directory_path)))
        if not os.path.isdir(path):
            raise FileNotFoundError(f"Input directory not found: {path}")

        content = pack_directory_to_zip_bytes(
            path,
            include_patterns=include_patterns,
            exclude_patterns=exclude_patterns,
        )
        return cls(content=content, kind="directory", metadata={})

    @classmethod
    def from_value(
        cls,
        value: Any,
    ) -> "CryptoInput":
        content = pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
        metadata = {
            "serializer": "pickle",
            "value_type": f"{type(value).__module__}.{type(value).__qualname__}",
        }
        return cls(content=content, kind="value", metadata=metadata)
