from __future__ import annotations

import ctypes
import json
import warnings
import winreg
from ctypes import wintypes
from typing import Any


HRESULT = getattr(wintypes, "HRESULT", ctypes.c_long)

_SHLoadIndirectString = ctypes.windll.shlwapi.SHLoadIndirectString
_SHLoadIndirectString.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.UINT, wintypes.LPVOID]
_SHLoadIndirectString.restype = HRESULT

_ExpandEnvironmentStringsW = ctypes.windll.kernel32.ExpandEnvironmentStringsW
_ExpandEnvironmentStringsW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
_ExpandEnvironmentStringsW.restype = wintypes.DWORD


_SECTION_BASES = {
    "folder": [r"Directory\shell", r"Folder\shell"],
    "background": [r"Directory\Background\shell"],
}

_DEFAULT_USER_BASE = {
    "folder": r"HKCU\Software\Classes\Directory\shell",
    "background": r"HKCU\Software\Classes\Directory\Background\shell",
}

_PROTECTED_ENTRIES = {
    ("folder", "open"),
    ("folder", "opennewprocess"),
    ("folder", "opennewtab"),
    ("folder", "opennewwindow"),
    ("folder", "pintohome"),
}

_ENTRY_FIELDS = ("text", "command", "icon", "extended", "registry_path", "submenu")
_SEARCH_FIELDS = ("key", "text", "command", "icon", "registry_path")


def _expand_env(text: str) -> str:
    needed = _ExpandEnvironmentStringsW(text, None, 0)
    buf = ctypes.create_unicode_buffer(needed)
    _ExpandEnvironmentStringsW(text, buf, needed)
    return buf.value


def _resolve_indirect(text: str) -> str:
    expanded = _expand_env(text)
    buf = ctypes.create_unicode_buffer(4096)
    hr = _SHLoadIndirectString(expanded, buf, len(buf), None)
    return buf.value if hr == 0 and buf.value else expanded


def _clean_text(text: str) -> str:
    return text.replace("&&", "\0").replace("&", "").replace("\0", "&").strip()


def _normalize_path(path: str) -> str:
    return path.replace("/", "\\")


def _split_registry_path(registry_path: str) -> tuple[str, Any, str]:
    path = _normalize_path(registry_path)
    root, _, subpath = path.partition("\\")
    roots = {
        "HKCU": winreg.HKEY_CURRENT_USER,
        "HKEY_CURRENT_USER": winreg.HKEY_CURRENT_USER,
        "HKCR": winreg.HKEY_CLASSES_ROOT,
        "HKEY_CLASSES_ROOT": winreg.HKEY_CLASSES_ROOT,
        "HKLM": winreg.HKEY_LOCAL_MACHINE,
        "HKEY_LOCAL_MACHINE": winreg.HKEY_LOCAL_MACHINE,
    }
    try:
        return root.upper(), roots[root.upper()], subpath
    except KeyError as exc:
        raise ValueError(f"Unsupported registry root in path: {registry_path!r}") from exc


def _target_registry_path(registry_path: str, *, all_users: bool) -> tuple[Any, str]:
    root_name, root, subpath = _split_registry_path(registry_path)
    if not all_users and root_name in {"HKCR", "HKEY_CLASSES_ROOT"}:
        return winreg.HKEY_CURRENT_USER, rf"Software\Classes\{subpath}"
    return root, subpath


def _path_key(registry_path: str) -> str:
    return _normalize_path(registry_path).rstrip("\\").rsplit("\\", 1)[-1]


def _delete_recursive(root, path: str) -> None:
    try:
        with winreg.OpenKey(root, path, 0, winreg.KEY_ALL_ACCESS) as key:
            while True:
                try:
                    _delete_recursive(key, winreg.EnumKey(key, 0))
                except OSError:
                    break
        winreg.DeleteKey(root, path)
    except FileNotFoundError:
        pass


class ContextMenuEntry:
    """Single Windows context menu entry for one context."""

    def __init__(
        self,
        data: dict[str, Any],
        *,
        context: str,
        state: str = "clean",
    ):
        if context not in _SECTION_BASES:
            raise ValueError(f"Unsupported context: {context!r}")

        self._context = context
        self._state = state
        self._initializing = True

        self.text = data.get("text")
        self.command = data.get("command")
        self.icon = data.get("icon")
        self.extended = bool(data.get("extended", False))
        self.registry_path = data.get("registry_path") or self._default_registry_path(data)
        self.submenu = list(data.get("submenu", []))

        self._original = self.to_dict()
        self._initializing = False

    def __setattr__(self, name: str, value: Any) -> None:
        object.__setattr__(self, name, value)
        if name in _ENTRY_FIELDS and not getattr(self, "_initializing", True):
            if self._state == "clean":
                object.__setattr__(self, "_state", "modified")

    @property
    def context(self) -> str:
        return self._context

    @property
    def state(self) -> str:
        return self._state

    @property
    def key(self) -> str:
        return _path_key(self.registry_path)

    @property
    def protected(self) -> bool:
        return (self.context, self.key.lower()) in _PROTECTED_ENTRIES

    def delete(self, *, force: bool = False) -> None:
        if self.protected and not force:
            raise PermissionError(f"Refusing to delete protected context menu entry: {self.context}:{self.key}")
        self._state = "deleted"

    def to_dict(self) -> dict[str, Any]:
        return {field: getattr(self, field) for field in _ENTRY_FIELDS}

    def _mark_clean(self) -> None:
        self._state = "clean"
        self._original = self.to_dict()

    def _default_registry_path(self, data: dict[str, Any]) -> str:
        text = str(data.get("text") or "Command")
        key = "".join(ch for ch in text if ch.isalnum()) or "Command"
        return rf"{_DEFAULT_USER_BASE[self.context]}\{key}"

    def __repr__(self) -> str:
        return (
            f"ContextMenuEntry(context={self.context!r}, key={self.key!r}, "
            f"text={self.text!r}, state={self.state!r})"
        )

    def __str__(self) -> str:
        return (
            "ContextMenuEntry\n"
            f"  context: {self.context}\n"
            f"  key: {self.key}\n"
            f"  text: {self.text}\n"
            f"  command: {self.command}\n"
            f"  icon: {self.icon}\n"
            f"  extended: {self.extended}\n"
            f"  registry_path: {self.registry_path}\n"
            f"  state: {self.state}\n"
            f"  protected: {self.protected}"
        )


class ContextMenuSection:
    """Collection of context menu entries for one context."""

    def __init__(self, context: str, entries: list[ContextMenuEntry] | None = None):
        if context not in _SECTION_BASES:
            raise ValueError(f"Unsupported context: {context!r}")
        self.context = context
        self.entries = entries or []

    def add(self, entry: dict[str, Any] | ContextMenuEntry) -> ContextMenuEntry:
        item = entry if isinstance(entry, ContextMenuEntry) else ContextMenuEntry(entry, context=self.context, state="new")
        if item.context != self.context:
            raise ValueError(f"Cannot add {item.context!r} entry to {self.context!r} section")
        if self.get(item.key) is not None:
            raise ValueError(f"Context menu entry already exists: {self.context}:{item.key}")
        self.entries.append(item)
        return item

    def get(self, key: str) -> ContextMenuEntry | None:
        wanted = key.lower()
        for entry in self.entries:
            if entry.key.lower() == wanted and entry.state != "deleted":
                return entry
        return None

    def remove(self, key: str, *, force: bool = False) -> ContextMenuEntry | None:
        entry = self.get(key)
        if entry is not None:
            entry.delete(force=force)
        return entry

    def find(self, value: str | None = None, **filters: str) -> list[ContextMenuEntry]:
        results = [entry for entry in self.entries if entry.state != "deleted"]
        if value is not None:
            needle = value.lower()
            results = [
                entry
                for entry in results
                if any(needle in str(getattr(entry, field, "") or "").lower() for field in _SEARCH_FIELDS)
            ]

        for field, expected in filters.items():
            needle = str(expected).lower()
            results = [
                entry
                for entry in results
                if needle in str(getattr(entry, field, "") or "").lower()
            ]

        return results

    def changed(self, *, force: bool = False) -> list[ContextMenuEntry]:
        return [
            entry
            for entry in self.entries
            if entry.state != "clean"
            if force or not entry.protected
        ]

    def to_list(self) -> list[dict[str, Any]]:
        return [entry.to_dict() for entry in self.entries if entry.state != "deleted"]

    def __repr__(self) -> str:
        return (
            f"ContextMenuSection(context={self.context!r}, entries={len(self.find())}, "
            f"changed={len(self.changed())})"
        )

    def __str__(self) -> str:
        entries = self.find()
        changed = self.changed()
        keys = ", ".join(entry.key for entry in entries[:10])
        if len(entries) > 10:
            keys += f", ... +{len(entries) - 10} more"
        return (
            "ContextMenuSection\n"
            f"  context: {self.context}\n"
            f"  entries: {len(entries)}\n"
            f"  changed: {len(changed)}\n"
            f"  keys: {keys}"
        )


class ContextMenu:
    """Safe, incremental manager for Windows folder/background context menus."""

    def __init__(self):
        self.folder = ContextMenuSection("folder", self._read_section("folder"))
        self.background = ContextMenuSection("background", self._read_section("background"))

    @classmethod
    def from_system(cls) -> ContextMenu:
        warnings.warn(
            "ContextMenu.from_system() is deprecated. Use ContextMenu() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return cls()

    @classmethod
    def from_json(cls, path: str) -> ContextMenu:
        raise RuntimeError(
            "ContextMenu.from_json() was removed. Use ContextMenu() to read the system, "
            "then use add/get/remove/find and to_system()."
        )

    @classmethod
    def from_dict(cls, source: dict[str, list[dict]]) -> ContextMenu:
        raise RuntimeError(
            "ContextMenu.from_dict() was removed. Use ContextMenu() to read the system, "
            "then use add/get/remove/find and to_system()."
        )

    def get(self, key: str) -> tuple[ContextMenuEntry | None, ContextMenuEntry | None]:
        return self.folder.get(key), self.background.get(key)

    def find(self, value: str | None = None, **filters: str) -> list[ContextMenuEntry]:
        return self.folder.find(value, **filters) + self.background.find(value, **filters)

    def changed(self, *, force: bool = False) -> list[ContextMenuEntry]:
        return self.folder.changed(force=force) + self.background.changed(force=force)

    def to_dict(self) -> dict[str, list[dict[str, Any]]]:
        return {
            "folder": self.folder.to_list(),
            "background": self.background.to_list(),
        }

    def to_json(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=4, ensure_ascii=False)

    def to_system(
        self,
        *,
        force: bool = False,
        verbose: bool = True,
        all_users: bool = False,
    ) -> list[dict[str, str]] | None:
        applied = []
        for entry in self.changed(force=force):
            action = entry.state
            if entry.state == "deleted":
                self._delete_entry(entry, all_users=all_users)
            elif entry.state in {"new", "modified"}:
                self._write_entry(entry, all_users=all_users)
            applied.append({"action": action, "context": entry.context, "key": entry.key})
            entry._mark_clean()
        if verbose:
            self._print_summary(applied)
            return None
        return applied

    @staticmethod
    def _read_section(context: str) -> list[ContextMenuEntry]:
        entries: list[ContextMenuEntry] = []
        seen: set[tuple[str, str]] = set()

        for shell_path in _SECTION_BASES[context]:
            try:
                with winreg.OpenKeyEx(winreg.HKEY_CLASSES_ROOT, shell_path, 0, winreg.KEY_READ) as h_shell:
                    index = 0
                    while True:
                        try:
                            key = winreg.EnumKey(h_shell, index)
                            registry_path = rf"HKCR\{shell_path}\{key}"
                            entry = ContextMenu._read_entry(context, registry_path)
                            identity = (entry.context, entry.registry_path.lower()) if entry else None
                            if entry is not None and identity not in seen:
                                seen.add(identity)
                                entries.append(entry)
                            index += 1
                        except OSError:
                            break
            except OSError:
                pass

        return entries

    @staticmethod
    def _read_entry(context: str, registry_path: str) -> ContextMenuEntry | None:
        _, root, subpath = _split_registry_path(registry_path)
        try:
            with winreg.OpenKeyEx(root, subpath, 0, winreg.KEY_READ) as h:
                for guard in ("LegacyDisable", "ProgrammaticAccessOnly"):
                    try:
                        winreg.QueryValueEx(h, guard)
                        return None
                    except OSError:
                        pass

                text = ContextMenu._read_text(h)
                if not text:
                    return None

                icon = None
                try:
                    icon = _resolve_indirect(str(winreg.QueryValueEx(h, "Icon")[0]))
                except OSError:
                    pass

                extended = False
                try:
                    winreg.QueryValueEx(h, "Extended")
                    extended = True
                except OSError:
                    pass

                command = None
                try:
                    with winreg.OpenKeyEx(h, "command", 0, winreg.KEY_READ) as hc:
                        command = _expand_env(str(winreg.QueryValueEx(hc, "")[0]))
                except OSError:
                    pass

                return ContextMenuEntry(
                    {
                        "text": text,
                        "command": command,
                        "icon": icon,
                        "extended": extended,
                        "registry_path": registry_path,
                        "submenu": [],
                    },
                    context=context,
                )
        except OSError:
            return None

    @staticmethod
    def _read_text(key) -> str | None:
        try:
            raw = winreg.QueryValueEx(key, "MUIVerb")[0]
        except OSError:
            try:
                raw = winreg.QueryValue(key, "")
            except OSError:
                return None
        return _clean_text(_resolve_indirect(str(raw))) if raw else None

    @staticmethod
    def _write_entry(entry: ContextMenuEntry, *, all_users: bool = False) -> None:
        root, subpath = _target_registry_path(entry.registry_path, all_users=all_users)
        with winreg.CreateKeyEx(root, subpath, 0, winreg.KEY_ALL_ACCESS) as h:
            winreg.SetValueEx(h, "MUIVerb", 0, winreg.REG_SZ, entry.text or entry.key)
            winreg.SetValue(root, subpath, winreg.REG_SZ, entry.text or entry.key)

            if entry.icon:
                winreg.SetValueEx(h, "Icon", 0, winreg.REG_SZ, entry.icon)
            else:
                try:
                    winreg.DeleteValue(h, "Icon")
                except OSError:
                    pass

            if entry.extended:
                winreg.SetValueEx(h, "Extended", 0, winreg.REG_SZ, "")
            else:
                try:
                    winreg.DeleteValue(h, "Extended")
                except OSError:
                    pass

            if entry.command:
                with winreg.CreateKeyEx(h, "command", 0, winreg.KEY_ALL_ACCESS) as hc:
                    winreg.SetValueEx(hc, "", 0, winreg.REG_SZ, entry.command)

    @staticmethod
    def _delete_entry(entry: ContextMenuEntry, *, all_users: bool = False) -> None:
        root, subpath = _target_registry_path(entry.registry_path, all_users=all_users)
        _delete_recursive(root, subpath)

    @staticmethod
    def _print_summary(applied: list[dict[str, str]]) -> None:
        if not applied:
            print("ContextMenu: no changes to apply.")
            return

        counts = {"new": 0, "modified": 0, "deleted": 0}
        for item in applied:
            counts[item["action"]] = counts.get(item["action"], 0) + 1

        parts = [
            f"{counts[action]} {action}"
            for action in ("new", "modified", "deleted")
            if counts.get(action)
        ]
        total_label = "change" if len(applied) == 1 else "changes"
        print(f"ContextMenu: applied {len(applied)} {total_label}: {', '.join(parts)}.")

    def __repr__(self) -> str:
        return (
            f"ContextMenu(folder={len(self.folder.find())}, background={len(self.background.find())}, "
            f"changed={len(self.changed())})"
        )

    def __str__(self) -> str:
        changed = self.changed()
        changed_keys = ", ".join(f"{entry.context}:{entry.key}" for entry in changed[:10])
        if len(changed) > 10:
            changed_keys += f", ... +{len(changed) - 10} more"
        return (
            "ContextMenu\n"
            f"  folder entries: {len(self.folder.find())}\n"
            f"  background entries: {len(self.background.find())}\n"
            f"  changed: {len(changed)}\n"
            f"  changed keys: {changed_keys}"
        )
