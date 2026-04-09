from __future__ import annotations

import ctypes
import json
import winreg
from ctypes import wintypes


# ── WinAPI bindings ───────────────────────────────────────────────────────────

HRESULT = getattr(wintypes, "HRESULT", ctypes.c_long)

_SHLoadIndirectString = ctypes.windll.shlwapi.SHLoadIndirectString
_SHLoadIndirectString.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.UINT, wintypes.LPVOID]
_SHLoadIndirectString.restype = HRESULT

_ExpandEnvironmentStringsW = ctypes.windll.kernel32.ExpandEnvironmentStringsW
_ExpandEnvironmentStringsW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
_ExpandEnvironmentStringsW.restype = wintypes.DWORD


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


# ── ContextMenu ───────────────────────────────────────────────────────────────

_REGISTRY_BASES: dict[str, list[str]] = {
    "background": [r"Directory\Background"],
    "folder": ["Directory", "Folder"],
}


class ContextMenu:
    """
    Manager for Windows context menu commands (folders and background).

    Commands are stored as plain dictionaries grouped by context:
    {"background": [dict, ...], "folder": [dict, ...]}

    Each command dict has the following keys:
        text, command, icon, extended, registry_path, submenu

    Initialization:
        ContextMenu()               — reads current entries from the registry.
        ContextMenu("path.json")    — loads from a JSON file.
        ContextMenu(dict)           — reconstructs from a plain dictionary.
    """

    def __init__(self, source: dict[str, list[dict]] | str | None = None):
        if source is None:
            self.commands = self._read_system()
        elif isinstance(source, str):
            with open(source, "r", encoding="utf-8") as f:
                self.commands = json.load(f)
        elif isinstance(source, dict):
            self.commands: dict[str, list[dict]] = {
                "background": source.get("background", []),
                "folder": source.get("folder", []),
            }
        else:
            raise TypeError(f"Expected dict, str (JSON path), or None; got {type(source).__name__}")

    def __str__(self) -> str:
        bg = len(self.commands.get("background", []))
        fl = len(self.commands.get("folder", []))
        return f"ContextMenu(background={bg}, folder={fl})"

    def __repr__(self) -> str:
        return self.__str__()

    # ── System reading ────────────────────────────────────────────────────────

    @staticmethod
    def _read_system() -> dict[str, list[dict]]:
        """Reads the current context menu commands from the Windows Registry."""
        hkcr = winreg.HKEY_CLASSES_ROOT
        commands: dict[str, list[dict]] = {"background": [], "folder": []}

        def read_item(key_path: str) -> dict | None:
            try:
                with winreg.OpenKeyEx(hkcr, key_path, 0, winreg.KEY_READ) as h:
                    for guard in ["LegacyDisable", "ProgrammaticAccessOnly"]:
                        try:
                            winreg.QueryValueEx(h, guard)
                            return None
                        except OSError:
                            pass

                    text_raw = None
                    try:
                        text_raw = winreg.QueryValueEx(h, "MUIVerb")[0]
                    except OSError:
                        try:
                            text_raw = winreg.QueryValue(h, "")
                        except OSError:
                            return None

                    if not text_raw:
                        return None
                    text = _clean_text(_resolve_indirect(str(text_raw)))

                    icon_raw = None
                    try:
                        icon_raw = winreg.QueryValueEx(h, "Icon")[0]
                    except OSError:
                        pass

                    extended = False
                    try:
                        winreg.QueryValueEx(h, "Extended")
                        extended = True
                    except OSError:
                        pass

                    cmd = None
                    try:
                        with winreg.OpenKeyEx(h, "command", 0, winreg.KEY_READ) as hc:
                            cmd_raw = winreg.QueryValueEx(hc, "")[0]
                            cmd = _expand_env(str(cmd_raw))
                    except OSError:
                        pass

                    return {
                        "text": text,
                        "command": cmd,
                        "icon": _resolve_indirect(str(icon_raw)) if icon_raw else None,
                        "registry_path": f"HKCR\\{key_path}",
                        "extended": extended,
                        "submenu": [],
                    }
            except OSError:
                return None

        for ctx, bases in _REGISTRY_BASES.items():
            seen: set[tuple] = set()
            for base in bases:
                shell_path = f"{base}\\shell"
                try:
                    with winreg.OpenKeyEx(hkcr, shell_path, 0, winreg.KEY_READ) as h_shell:
                        i = 0
                        while True:
                            try:
                                verb = winreg.EnumKey(h_shell, i)
                                item = read_item(f"{shell_path}\\{verb}")
                                if item:
                                    uid = (item["text"], item["command"])
                                    if uid not in seen:
                                        seen.add(uid)
                                        commands[ctx].append(item)
                                i += 1
                            except OSError:
                                break
                except OSError:
                    pass

        return commands

    # ── Serialization ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Returns the commands dictionary."""
        return self.commands

    def to_json(self, path: str):
        """Saves the commands to a JSON file (UTF-8, 4 spaces) with sorted keys."""
        order = ["text", "command", "icon", "extended", "registry_path", "submenu"]
        
        # Re-organizar los diccionarios para asegurar el orden estético de las llaves
        formatted_commands = {}
        for ctx, items in self.commands.items():
            formatted_commands[ctx] = []
            for item in items:
                # Solo incluimos las llaves que existen y en el orden definido
                new_item = {k: item[k] for k in order if k in item}
                # Añadir llaves extra que no estén en nuestra lista de orden (por si acaso)
                for k in item:
                    if k not in new_item:
                        new_item[k] = item[k]
                formatted_commands[ctx].append(new_item)

        with open(path, "w", encoding="utf-8") as f:
            json.dump(formatted_commands, f, indent=4, ensure_ascii=False)

    # ── Registry persistence ──────────────────────────────────────────────────

    def save(self, user_only: bool = True):
        """
        Writes the current commands to the Windows Registry.

        Note: Windows displays context menu items alphabetically based on the registry
        key name.

        This is a full overwrite: commands previously registered in the system
        that are no longer present in this manager will be removed.

        If 'user_only' is True (default), writes to HKEY_CURRENT_USER\\Software\\Classes,
        which does not require Administrator privileges.
        """
        root_key = winreg.HKEY_CURRENT_USER if user_only else winreg.HKEY_CLASSES_ROOT

        def _to_subpath(registry_path: str) -> str:
            parts = registry_path.split("\\", 1)
            subpath = parts[1] if len(parts) > 1 else registry_path
            if user_only:
                return f"Software\\Classes\\{subpath}"
            return subpath

        def _delete_recursive(root, path: str):
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

        def _write_command(cmd: dict, ctx: str):
            reg_path = cmd.get("registry_path")
            if not reg_path:
                base = r"Directory\Background" if ctx == "background" else "Directory"
                reg_path = rf"HKCR\{base}\shell\{cmd['text'].replace(' ', '')}"
                cmd["registry_path"] = reg_path

            subpath = _to_subpath(reg_path)

            with winreg.CreateKeyEx(root_key, subpath, 0, winreg.KEY_ALL_ACCESS) as h:
                winreg.SetValueEx(h, "MUIVerb", 0, winreg.REG_SZ, cmd["text"])
                winreg.SetValue(root_key, subpath, winreg.REG_SZ, cmd["text"])

                if cmd.get("icon"):
                    winreg.SetValueEx(h, "Icon", 0, winreg.REG_SZ, cmd["icon"])

                if cmd.get("extended"):
                    winreg.SetValueEx(h, "Extended", 0, winreg.REG_SZ, "")
                else:
                    try:
                        winreg.DeleteValue(h, "Extended")
                    except OSError:
                        pass

                if cmd.get("command"):
                    with winreg.CreateKeyEx(h, "command", 0, winreg.KEY_ALL_ACCESS) as hc:
                        winreg.SetValueEx(hc, "", 0, winreg.REG_SZ, cmd["command"])

        # Step 1: Wipe existing shell keys for each context.
        for ctx, bases in _REGISTRY_BASES.items():
            for base in bases:
                shell_path = f"{base}\\shell"
                actual_shell = f"Software\\Classes\\{shell_path}" if user_only else shell_path

                try:
                    with winreg.OpenKeyEx(root_key, actual_shell, 0, winreg.KEY_READ) as h_shell:
                        verbs_to_delete = []
                        i = 0
                        while True:
                            try:
                                verbs_to_delete.append(winreg.EnumKey(h_shell, i))
                                i += 1
                            except OSError:
                                break
                    for verb in verbs_to_delete:
                        _delete_recursive(root_key, f"{actual_shell}\\{verb}")
                except OSError:
                    pass

        # Step 2: Write commands back to the registry.
        for ctx, cmds in self.commands.items():
            for cmd in cmds:
                _write_command(cmd, ctx)
