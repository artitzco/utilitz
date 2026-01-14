from pathlib import Path
import os

import sys


def locate_project(level=None, forced=False, source=None):
    """
    Change the current working directory to a project root based on a search pattern or parent level.

    Args:
        level (str or int, optional): If str, searches upwards for a directory containing a file/folder matching the pattern.
                                      If int, moves up 'level' parent directories.
        forced (bool, optional): If True, forces restoration of the previous working directory.

    Behavior:
        - If called with a 'level', changes the working directory accordingly and stores the previous directory.
        - If called without 'level', restores the previous working directory if available.
        - Prints info messages on directory changes.
        - Raises ValueError for invalid 'level' types.
        - Raises FileNotFoundError if the search fails.
    """
    global_vars = globals()
    varname = 'utilitz__locate__project__'
    cwd = Path.cwd()
    if varname in global_vars:
        if level is None or forced:
            cwd = global_vars[varname]
            os.chdir(cwd)
            del global_vars[varname]
            print(f'[INFO] Working directory restored: {cwd}')
        if not forced:
            set_soruce(source)
            return

    if level is not None:
        new_cwd = cwd
        if isinstance(level, str):
            while ((not_ok := (list(new_cwd.glob(level)) == [])) and
                   new_cwd != (new_cwd := new_cwd.parent)):
                pass
        elif isinstance(level, int) and level >= 0:
            count = 0
            while ((not_ok := count < level) and
                   new_cwd != (new_cwd := new_cwd.parent)):
                count += 1
        else:
            raise ValueError('level must be a str or a non-negative int')
        if cwd != new_cwd:
            if not not_ok:
                os.chdir(new_cwd)
                global_vars[varname] = cwd
                print(f"[INFO] Working directory changed to: {new_cwd}")
            else:
                raise FileNotFoundError(
                    f"Could not find a directory matching level '{level}' from {cwd}"
                )
    set_soruce(source)


def set_soruce(source):
    if source is None:
        source = []
    if isinstance(source, str):
        source = [source]

    varname = 'utilitz__set_source__'
    path_list = globals().get(varname, [])
    new_path_list = [str(Path().resolve() / x) for x in source]

    # agregar nuevos paths
    for x in new_path_list:
        if x not in path_list:
            sys.path.append(x)
            print(f"[INFO] Path added to sys.path: {x}")

    # quitar paths que ya no están
    for x in path_list:
        if x not in new_path_list:
            if x in sys.path:
                sys.path.remove(x)
                print(f"[INFO] Path removed from sys.path: {x}")

    # actualizar globals si hubo cambios
    if new_path_list != path_list:
        globals()[varname] = new_path_list