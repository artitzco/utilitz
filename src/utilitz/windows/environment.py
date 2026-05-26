from __future__ import annotations

import ctypes
import json
import winreg
from ctypes import wintypes
from typing import Any


_ENVIRONMENT_KEY = r"Environment"
_VARIABLE_FIELDS = ("name", "value", "kind")
_SEARCH_FIELDS = ("name", "value", "kind")
_REGISTRY_KINDS = {
    winreg.REG_SZ: "string",
    winreg.REG_EXPAND_SZ: "expand",
}
_WINREG_TYPES = {
    "string": winreg.REG_SZ,
    "expand": winreg.REG_EXPAND_SZ,
}

HWND_BROADCAST = 0xFFFF
WM_SETTINGCHANGE = 0x001A
SMTO_ABORTIFHUNG = 0x0002

_SendMessageTimeoutW = ctypes.windll.user32.SendMessageTimeoutW
_SendMessageTimeoutW.argtypes = [
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPCWSTR,
    wintypes.UINT,
    wintypes.UINT,
    ctypes.POINTER(wintypes.DWORD),
]
_SendMessageTimeoutW.restype = wintypes.LPARAM

_OpenClipboard = ctypes.windll.user32.OpenClipboard
_OpenClipboard.argtypes = [wintypes.HWND]
_OpenClipboard.restype = wintypes.BOOL

_EmptyClipboard = ctypes.windll.user32.EmptyClipboard
_EmptyClipboard.argtypes = []
_EmptyClipboard.restype = wintypes.BOOL

_SetClipboardData = ctypes.windll.user32.SetClipboardData
_SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
_SetClipboardData.restype = wintypes.HANDLE

_CloseClipboard = ctypes.windll.user32.CloseClipboard
_CloseClipboard.argtypes = []
_CloseClipboard.restype = wintypes.BOOL

_GlobalAlloc = ctypes.windll.kernel32.GlobalAlloc
_GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
_GlobalAlloc.restype = wintypes.HGLOBAL

_GlobalLock = ctypes.windll.kernel32.GlobalLock
_GlobalLock.argtypes = [wintypes.HGLOBAL]
_GlobalLock.restype = wintypes.LPVOID

_GlobalUnlock = ctypes.windll.kernel32.GlobalUnlock
_GlobalUnlock.argtypes = [wintypes.HGLOBAL]
_GlobalUnlock.restype = wintypes.BOOL

GMEM_MOVEABLE = 0x0002
CF_UNICODETEXT = 13


def _masked_value(value: str) -> str:
    return "*" * min(max(len(value), 1), 12)


def _copy_to_clipboard(text: str) -> None:
    data = (text + "\0").encode("utf-16-le")
    handle = _GlobalAlloc(GMEM_MOVEABLE, len(data))
    if not handle:
        raise OSError("Could not allocate clipboard memory.")

    locked = _GlobalLock(handle)
    if not locked:
        raise OSError("Could not lock clipboard memory.")

    ctypes.memmove(locked, data, len(data))
    _GlobalUnlock(handle)

    if not _OpenClipboard(None):
        raise OSError("Could not open clipboard.")

    try:
        _EmptyClipboard()
        if not _SetClipboardData(CF_UNICODETEXT, handle):
            raise OSError("Could not set clipboard data.")
    finally:
        _CloseClipboard()


class UserEnvironmentVariable:
    """Single user environment variable stored in HKCU\\Environment."""

    def __init__(
        self,
        data: dict[str, Any],
        *,
        state: str = "clean",
    ):
        self._state = state
        self._initializing = True

        self.name = data["name"]
        self.value = data.get("value", "")
        self.kind = data.get("kind", "string")

        if self.kind not in _WINREG_TYPES:
            raise ValueError(f"Unsupported environment variable kind: {self.kind!r}")

        self._original = self.to_dict()
        self._initializing = False

    def __setattr__(self, name: str, value: Any) -> None:
        object.__setattr__(self, name, value)
        if name in _VARIABLE_FIELDS and not getattr(self, "_initializing", True):
            if self._state == "clean":
                object.__setattr__(self, "_state", "modified")

    @property
    def state(self) -> str:
        return self._state

    def delete(self) -> None:
        self._state = "deleted"

    def to_dict(self) -> dict[str, str]:
        return {field: getattr(self, field) for field in _VARIABLE_FIELDS}

    def to_clipboard(self) -> None:
        _copy_to_clipboard(str(self.value))

    def _mark_clean(self) -> None:
        self._state = "clean"
        self._original = self.to_dict()

    def __repr__(self) -> str:
        return f"UserEnvironmentVariable(name={self.name!r}, kind={self.kind!r}, state={self.state!r})"

    def __str__(self) -> str:
        return (
            "UserEnvironmentVariable\n"
            f"  name: {self.name}\n"
            f"  value: {_masked_value(str(self.value))}\n"
            f"  kind: {self.kind}\n"
            f"  state: {self.state}"
        )


class UserEnvironment:
    """Safe, incremental manager for current-user environment variables."""

    def __init__(self):
        self.variables = self._read_variables()

    @classmethod
    def from_json(cls, path: str) -> UserEnvironment:
        raise RuntimeError(
            "UserEnvironment.from_json() was removed. Use UserEnvironment() to read the system, "
            "then use add/get/remove/find and to_system()."
        )

    @classmethod
    def from_dict(cls, source: dict[str, list[dict]]) -> UserEnvironment:
        raise RuntimeError(
            "UserEnvironment.from_dict() was removed. Use UserEnvironment() to read the system, "
            "then use add/get/remove/find and to_system()."
        )

    def add(
        self,
        name: str | UserEnvironmentVariable,
        value: str | None = None,
        *,
        kind: str = "string",
    ) -> UserEnvironmentVariable:
        if isinstance(name, UserEnvironmentVariable):
            item = name
        else:
            item = UserEnvironmentVariable(
                {
                    "name": name,
                    "value": value or "",
                    "kind": kind,
                },
                state="new",
            )
        if self.get(item.name) is not None:
            raise ValueError(f"User environment variable already exists: {item.name}")
        self.variables.append(item)
        return item

    def get(self, name: str) -> UserEnvironmentVariable | None:
        wanted = name.lower()
        for variable in self.variables:
            if variable.name.lower() == wanted and variable.state != "deleted":
                return variable
        return None

    def remove(self, name: str) -> UserEnvironmentVariable | None:
        variable = self.get(name)
        if variable is not None:
            variable.delete()
        return variable

    def find(self, value: str | None = None, **filters: str) -> list[UserEnvironmentVariable]:
        results = [variable for variable in self.variables if variable.state != "deleted"]
        if value is not None:
            needle = value.lower()
            results = [
                variable
                for variable in results
                if any(needle in str(getattr(variable, field, "") or "").lower() for field in _SEARCH_FIELDS)
            ]

        for field, expected in filters.items():
            needle = str(expected).lower()
            results = [
                variable
                for variable in results
                if needle in str(getattr(variable, field, "") or "").lower()
            ]

        return results

    def changed(self) -> list[UserEnvironmentVariable]:
        return [variable for variable in self.variables if variable.state != "clean"]

    def to_dict(self) -> dict[str, list[dict[str, str]]]:
        return {"variables": [variable.to_dict() for variable in self.variables if variable.state != "deleted"]}

    def to_json(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=4, ensure_ascii=False)

    def to_system(self, *, verbose: bool = True) -> list[dict[str, str]] | None:
        applied = []
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, _ENVIRONMENT_KEY, 0, winreg.KEY_ALL_ACCESS) as key:
            for variable in self.changed():
                action = variable.state
                if variable.state == "deleted":
                    self._delete_variable(key, variable)
                elif variable.state in {"new", "modified"}:
                    self._write_variable(key, variable)
                applied.append({"action": action, "name": variable.name})
                variable._mark_clean()

        if applied:
            self._broadcast_environment_change()
        if verbose:
            self._print_summary(applied)
            return None
        return applied

    @staticmethod
    def _read_variables() -> list[UserEnvironmentVariable]:
        variables = []
        try:
            with winreg.OpenKeyEx(winreg.HKEY_CURRENT_USER, _ENVIRONMENT_KEY, 0, winreg.KEY_READ) as key:
                index = 0
                while True:
                    try:
                        name, value, registry_type = winreg.EnumValue(key, index)
                        kind = _REGISTRY_KINDS.get(registry_type)
                        if kind is not None:
                            variables.append(
                                UserEnvironmentVariable(
                                    {"name": name, "value": str(value), "kind": kind},
                                )
                            )
                        index += 1
                    except OSError:
                        break
        except OSError:
            pass
        return variables

    @staticmethod
    def _write_variable(key, variable: UserEnvironmentVariable) -> None:
        winreg.SetValueEx(key, variable.name, 0, _WINREG_TYPES[variable.kind], variable.value)

    @staticmethod
    def _delete_variable(key, variable: UserEnvironmentVariable) -> None:
        try:
            winreg.DeleteValue(key, variable.name)
        except FileNotFoundError:
            pass

    @staticmethod
    def _broadcast_environment_change() -> None:
        result = wintypes.DWORD()
        _SendMessageTimeoutW(
            HWND_BROADCAST,
            WM_SETTINGCHANGE,
            0,
            "Environment",
            SMTO_ABORTIFHUNG,
            5000,
            ctypes.byref(result),
        )

    @staticmethod
    def _print_summary(applied: list[dict[str, str]]) -> None:
        if not applied:
            print("UserEnvironment: no changes to apply.")
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
        print(f"UserEnvironment: applied {len(applied)} {total_label}: {', '.join(parts)}.")

    def __repr__(self) -> str:
        return f"UserEnvironment(variables={len(self.find())}, changed={len(self.changed())})"

    def __str__(self) -> str:
        changed = self.changed()
        changed_names = ", ".join(variable.name for variable in changed[:10])
        if len(changed) > 10:
            changed_names += f", ... +{len(changed) - 10} more"
        return (
            "UserEnvironment\n"
            f"  variables: {len(self.find())}\n"
            f"  changed: {len(changed)}\n"
            f"  changed names: {changed_names}"
        )
