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

_ENTRY_FIELDS = (
    "text",
    "command",
    "icon",
    "extended",
    "registry_path",
    "submenu",
)
_SEARCH_FIELDS = ("key", "text", "command", "icon", "registry_path")
_KNOWN_VALUE_NAMES = {"MUIVerb", "Icon", "Extended"}
_INTERNAL_DATA_FIELDS = set(_ENTRY_FIELDS) | {"registry_values"}


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


class ContextMenuCommand:
    """Command subkey for a context menu entry."""

    def __init__(
        self,
        value: str | dict[str, Any] | None = None,
        *,
        extra_values: dict[str, Any] | None = None,
        on_change=None,
    ):
        self._on_change = on_change
        self._extra_value_types = {}
        self._initializing = True

        if isinstance(value, dict):
            self.value = value.get("value")
            raw_extras = {key: val for key, val in value.items() if key != "value"}
        else:
            self.value = value
            raw_extras = extra_values or {}

        for name, item in raw_extras.items():
            if isinstance(item, dict) and "value" in item and "type" in item:
                self._extra_value_types[name] = item["type"]
                setattr(self, name, item["value"])
            else:
                self._extra_value_types[name] = winreg.REG_SZ
                setattr(self, name, item)

        self._initializing = False

    def __setattr__(self, name: str, value: Any) -> None:
        object.__setattr__(self, name, value)
        if not name.startswith("_") and not getattr(self, "_initializing", True):
            on_change = getattr(self, "_on_change", None)
            if on_change is not None:
                on_change()

    def __getitem__(self, name: str) -> Any:
        if name == "value":
            return self.value
        if name in self._extra_value_types:
            return getattr(self, name)
        raise KeyError(name)

    def __setitem__(self, name: str, value: Any) -> None:
        if name == "value":
            self.value = value
            return
        if name not in self._extra_value_types:
            self._extra_value_types[name] = winreg.REG_SZ
        setattr(self, name, value)

    def __contains__(self, name: str) -> bool:
        return name == "value" or name in self._extra_value_types

    def to_dict(self) -> dict[str, Any]:
        data = {"value": self.value}
        for name in self._extra_value_types:
            data[name] = getattr(self, name)
        return data

    def _registry_extra_values(self) -> dict[str, dict[str, Any]]:
        return {
            name: {"value": getattr(self, name), "type": registry_type}
            for name, registry_type in self._extra_value_types.items()
        }

    def __repr__(self) -> str:
        return f"ContextMenuCommand(value={self.value!r}, extras={len(self._extra_value_types)})"

    def __str__(self) -> str:
        lines = ["ContextMenuCommand", f"  value: {self.value}"]
        lines.extend(f"  {name}: {getattr(self, name)}" for name in self._extra_value_types)
        return "\n".join(lines)


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
        command = data.get("command")
        if isinstance(command, ContextMenuCommand):
            command._on_change = self._mark_modified
            self.command = command
        else:
            self.command = ContextMenuCommand(
                command,
                on_change=self._mark_modified,
            )
        self.icon = data.get("icon")
        self.extended = bool(data.get("extended", False))
        self.registry_path = data.get("registry_path") or self._default_registry_path(data)
        self.submenu = list(data.get("submenu", []))
        self._extra_value_types = {}

        for name, value in self._entry_extra_values(data).items():
            self._extra_value_types[name] = value.get("type", winreg.REG_SZ)
            setattr(self, name, value.get("value"))

        self._original = self.to_dict()
        self._initializing = False

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "command" and not isinstance(value, ContextMenuCommand):
            value = ContextMenuCommand(value, on_change=self._mark_modified)
        object.__setattr__(self, name, value)
        if not name.startswith("_") and not getattr(self, "_initializing", True):
            if self._state == "clean":
                object.__setattr__(self, "_state", "modified")

    def __getitem__(self, name: str) -> Any:
        if name in self.to_dict():
            return self.to_dict()[name]
        raise KeyError(name)

    def __setitem__(self, name: str, value: Any) -> None:
        if name in _INTERNAL_DATA_FIELDS:
            setattr(self, name, value)
            return

        if name not in self._extra_value_types:
            self._extra_value_types[name] = winreg.REG_SZ
        setattr(self, name, value)

    def __contains__(self, name: str) -> bool:
        return name in self.to_dict()

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
        data = {field: getattr(self, field) for field in _ENTRY_FIELDS if field != "command"}
        data["command"] = self.command.to_dict()
        for name in self._extra_value_types:
            data[name] = getattr(self, name)
        return data

    def _mark_modified(self) -> None:
        if not getattr(self, "_initializing", True) and self._state == "clean":
            self._state = "modified"

    def _mark_clean(self) -> None:
        self._state = "clean"
        self._original = self.to_dict()

    def _default_registry_path(self, data: dict[str, Any]) -> str:
        text = str(data.get("text") or "Command")
        key = "".join(ch for ch in text if ch.isalnum()) or "Command"
        return rf"{_DEFAULT_USER_BASE[self.context]}\{key}"

    @staticmethod
    def _entry_extra_values(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
        values = dict(data.get("registry_values", {}))
        for name, value in data.items():
            if name not in _INTERNAL_DATA_FIELDS:
                if isinstance(value, dict) and "value" in value and "type" in value:
                    values[name] = value
                else:
                    values[name] = {"value": value, "type": winreg.REG_SZ}
        return values

    def _entry_extra_registry_values(self) -> dict[str, dict[str, Any]]:
        return {
            name: {"value": getattr(self, name), "type": registry_type}
            for name, registry_type in self._extra_value_types.items()
        }

    def _search_text(self, field: str) -> str:
        if field == "command":
            return str(self.command.value or "").lower()
        return str(getattr(self, field, "") or "").lower()

    def __repr__(self) -> str:
        return (
            f"ContextMenuEntry(context={self.context!r}, key={self.key!r}, "
            f"text={self.text!r}, state={self.state!r})"
        )

    def __str__(self) -> str:
        lines = [
            "ContextMenuEntry",
            f"  context: {self.context}",
            f"  key: {self.key}",
            f"  text: {self.text}",
            f"  command: {self.command.value}",
            f"  icon: {self.icon}",
            f"  extended: {self.extended}",
            f"  registry_path: {self.registry_path}",
        ]
        lines.extend(f"  {name}: {getattr(self, name)}" for name in self._extra_value_types)
        lines.extend(
            f"  command.{name}: {getattr(self.command, name)}"
            for name in self.command._extra_value_types
        )
        lines.extend(
            [
                f"  state: {self.state}",
                f"  protected: {self.protected}",
            ]
        )
        return "\n".join(lines)


class ContextMenuSection:
    """Collection of context menu entries for one context."""

    def __init__(self, context: str, entries: list[ContextMenuEntry] | None = None):
        if context not in _SECTION_BASES:
            raise ValueError(f"Unsupported context: {context!r}")
        self.context = context
        self.entries = entries or []

    def add(
        self,
        text: str | ContextMenuEntry,
        command: str | ContextMenuCommand | None = None,
        *,
        icon: str | None = None,
        extended: bool = False,
        registry_path: str | None = None,
        submenu: list[dict[str, Any]] | None = None,
        registry_values: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> ContextMenuEntry:
        if isinstance(text, ContextMenuEntry):
            item = text
        else:
            item = ContextMenuEntry(
                {
                    "text": text,
                    "command": command,
                    "icon": icon,
                    "extended": extended,
                    "registry_path": registry_path,
                    "submenu": submenu or [],
                    "registry_values": registry_values or {},
                    **kwargs,
                },
                context=self.context,
                state="new",
            )
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
                if any(needle in entry._search_text(field) for field in _SEARCH_FIELDS)
            ]

        for field, expected in filters.items():
            needle = str(expected).lower()
            results = [
                entry
                for entry in results
                if needle in entry._search_text(field)
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
                registry_values = ContextMenu._read_extra_values(h, known_names=_KNOWN_VALUE_NAMES)
                try:
                    with winreg.OpenKeyEx(h, "command", 0, winreg.KEY_READ) as hc:
                        command_values = {"value": _expand_env(str(winreg.QueryValueEx(hc, "")[0]))}
                        command_values.update(ContextMenu._read_extra_values(hc, known_names=set()))
                        command = command_values
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
                        "registry_values": registry_values,
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
    def _read_extra_values(key, *, known_names: set[str]) -> dict[str, dict[str, Any]]:
        values = {}
        index = 0
        while True:
            try:
                name, value, registry_type = winreg.EnumValue(key, index)
                index += 1
            except OSError:
                break
            if name == "" or name in known_names:
                continue
            values[name] = {"value": value, "type": registry_type}
        return values

    @staticmethod
    def _write_extra_values(key, values: dict[str, Any]) -> None:
        for name, data in values.items():
            if isinstance(data, dict) and "value" in data and "type" in data:
                winreg.SetValueEx(key, name, 0, data["type"], data["value"])
            else:
                winreg.SetValueEx(key, name, 0, winreg.REG_SZ, str(data))

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

            if entry.command.value:
                with winreg.CreateKeyEx(h, "command", 0, winreg.KEY_ALL_ACCESS) as hc:
                    winreg.SetValueEx(hc, "", 0, winreg.REG_SZ, entry.command.value)
                    ContextMenu._write_extra_values(hc, entry.command._registry_extra_values())

            ContextMenu._write_extra_values(h, entry._entry_extra_registry_values())

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
