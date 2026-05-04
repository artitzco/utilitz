from __future__ import annotations

import ast
import re
from collections.abc import Iterable
from typing import Any, Callable

import pandas as pd


def _excel_col_to_index(value: str) -> int:
    text = value.strip().replace("$", "")
    if not re.fullmatch(r"[A-Za-z]+", text):
        raise ValueError(f"Invalid Excel column: {value!r}")

    n = 0
    for ch in text.upper():
        n = n * 26 + (ord(ch) - ord("A") + 1)
    return n - 1


def _is_list_like_selection(value: Any) -> bool:
    return (
        isinstance(value, Iterable)
        and not isinstance(value, (str, bytes))
        and not (isinstance(value, tuple) and len(value) == 2)
    )


def _require_non_negative(n: int, kind: str, original: Any) -> int:
    if n < 0:
        raise ValueError(f"{kind} cannot be negative: {original!r}")
    return n


def _parse_row_atom(value: Any) -> int:
    if isinstance(value, bool):
        raise TypeError("Booleans are not valid row identifiers.")

    if isinstance(value, int):
        return _require_non_negative(value, "Row", value)

    if isinstance(value, str):
        text = value.strip()
        if not re.fullmatch(r"\d+", text):
            raise ValueError(f"Invalid row: {value!r}")
        n = int(text) - 1
        if n < 0:
            raise ValueError(f"Excel-style rows start at 1: {value!r}")
        return n

    raise TypeError(f"Unsupported row identifier: {value!r}")


def _parse_col_atom(value: Any) -> int:
    if isinstance(value, bool):
        raise TypeError("Booleans are not valid column identifiers.")

    if isinstance(value, int):
        return _require_non_negative(value, "Column", value)

    if isinstance(value, str):
        return _excel_col_to_index(value)

    raise TypeError(f"Unsupported column identifier: {value!r}")


def _inclusive_range(
    start: int | None,
    end: int | None,
    *,
    max_len: int,
    open_start: int,
) -> list[int]:
    if max_len < 0:
        raise ValueError("max_len cannot be negative.")

    last = max_len - 1
    if start is None:
        start = open_start
    if end is None:
        end = last
    if start < 0 or end < 0:
        raise ValueError("Ranges cannot produce negative indices.")
    if max_len == 0 or start > last:
        return []

    end = min(end, last)
    if end < start:
        return []

    return list(range(start, end + 1))


def _parse_row_range_string(value: str, *, max_len: int, open_start: int) -> list[int]:
    text = value.strip()

    if text.startswith("[") or text.endswith("]"):
        if not (text.startswith("[") and text.endswith("]")):
            raise ValueError(f"Invalid row index range: {value!r}")
        inner = text[1:-1].strip()
        if inner.count(":") != 1:
            raise ValueError(f"Invalid row index range: {value!r}")
        left, right = [part.strip() for part in inner.split(":")]
        if left and not re.fullmatch(r"\d+", left):
            raise ValueError(
                f"Row index range requires 0-indexed integers: {value!r}")
        if right and not re.fullmatch(r"\d+", right):
            raise ValueError(
                f"Row index range requires 0-indexed integers: {value!r}")
        start = None if left == "" else int(left)
        end = None if right == "" else int(right)
        return _inclusive_range(start, end, max_len=max_len, open_start=open_start)

    if ":" in text:
        if text.count(":") != 1:
            raise ValueError(f"Invalid row range: {value!r}")
        left, right = [part.strip() for part in text.split(":")]
        start = None if left == "" else _parse_row_atom(left)
        end = None if right == "" else _parse_row_atom(right)
        return _inclusive_range(start, end, max_len=max_len, open_start=open_start)

    return [_parse_row_atom(text)]


def _parse_col_range_string(value: str, *, max_len: int, open_start: int = 0) -> list[int]:
    text = value.strip()

    if text.startswith("[") or text.endswith("]"):
        if not (text.startswith("[") and text.endswith("]")):
            raise ValueError(f"Invalid column index range: {value!r}")
        inner = text[1:-1].strip()
        if inner.count(":") != 1:
            raise ValueError(f"Invalid column index range: {value!r}")
        left, right = [part.strip() for part in inner.split(":")]
        if left and not re.fullmatch(r"\d+", left):
            raise ValueError(
                f"Column index range requires 0-indexed integers; use 'A:D' for letters: {value!r}"
            )
        if right and not re.fullmatch(r"\d+", right):
            raise ValueError(
                f"Column index range requires 0-indexed integers; use 'A:D' for letters: {value!r}"
            )
        start = None if left == "" else int(left)
        end = None if right == "" else int(right)
        return _inclusive_range(start, end, max_len=max_len, open_start=open_start)

    if ":" in text:
        if text.count(":") != 1:
            raise ValueError(f"Invalid column range: {value!r}")
        left, right = [part.strip() for part in text.split(":")]
        start = None if left == "" else _parse_col_atom(left)
        end = None if right == "" else _parse_col_atom(right)
        return _inclusive_range(start, end, max_len=max_len, open_start=open_start)

    return [_parse_col_atom(text)]


def _dedupe_sorted(values: Iterable[int]) -> list[int]:
    return sorted(set(values))


def _maybe_seek_start(io: Any) -> None:
    seek = getattr(io, "seek", None)
    if callable(seek):
        try:
            seek(0)
        except (OSError, ValueError):
            pass


def _resolve_sheet_name(xls: pd.ExcelFile, sheet_name: str | int) -> str:
    if isinstance(sheet_name, int):
        try:
            return xls.sheet_names[sheet_name]
        except IndexError as exc:
            raise ValueError(f"Worksheet index {sheet_name} is invalid.") from exc
    return sheet_name


def _get_sheet_dimensions(
    io: Any,
    *,
    sheet_name: str | int,
    engine: str | None,
    keep_default_na: bool,
) -> tuple[int, int]:
    try:
        xls = pd.ExcelFile(io, engine=engine)
        resolved_sheet = _resolve_sheet_name(xls, sheet_name)
        book = xls.book

        if hasattr(book, "__getitem__"):
            worksheet = book[resolved_sheet]
            if hasattr(worksheet, "max_row") and hasattr(worksheet, "max_column"):
                return int(worksheet.max_row), int(worksheet.max_column)

        if hasattr(book, "sheet_by_name"):
            worksheet = book.sheet_by_name(resolved_sheet)
            if hasattr(worksheet, "nrows") and hasattr(worksheet, "ncols"):
                return int(worksheet.nrows), int(worksheet.ncols)
    except Exception:
        pass
    finally:
        try:
            xls.close()  # type: ignore[name-defined]
        except Exception:
            pass
        _maybe_seek_start(io)

    # Fallback for engines that do not expose dimensions through ExcelFile.
    raw = pd.read_excel(
        io,
        sheet_name=sheet_name,
        header=None,
        dtype=object,
        engine=engine,
        keep_default_na=keep_default_na,
    )
    _maybe_seek_start(io)
    return raw.shape


def _parse_rows(selection: Any, *, max_len: int, open_start: int) -> list[int] | None:
    if selection is None:
        return None

    if _is_list_like_selection(selection):
        out: list[int] = []
        for item in selection:
            parsed = _parse_rows(item, max_len=max_len, open_start=open_start)
            if parsed is not None:
                out.extend(parsed)
        return _dedupe_sorted(out)

    if isinstance(selection, tuple):
        if len(selection) != 2:
            raise ValueError(
                f"Tuple ranges require two elements: {selection!r}")
        left, right = selection
        start = None if left is None else _parse_row_atom(left)
        end = None if right is None else _parse_row_atom(right)
        return _inclusive_range(start, end, max_len=max_len, open_start=open_start)

    if isinstance(selection, str) and (
        ":" in selection or selection.strip().startswith("[") or selection.strip().endswith("]")
    ):
        return _dedupe_sorted(_parse_row_range_string(selection, max_len=max_len, open_start=open_start))

    return [_parse_row_atom(selection)]


def _parse_cols(selection: Any, *, max_len: int, open_start: int = 0) -> list[int] | None:
    if selection is None:
        return None

    if _is_list_like_selection(selection):
        out: list[int] = []
        for item in selection:
            parsed = _parse_cols(item, max_len=max_len, open_start=open_start)
            if parsed is not None:
                out.extend(parsed)
        return _dedupe_sorted(out)

    if isinstance(selection, tuple):
        if len(selection) != 2:
            raise ValueError(
                f"Tuple ranges require two elements: {selection!r}")
        left, right = selection
        start = None if left is None else _parse_col_atom(left)
        end = None if right is None else _parse_col_atom(right)
        return _inclusive_range(start, end, max_len=max_len, open_start=open_start)

    if isinstance(selection, str) and (
        ":" in selection or selection.strip().startswith("[") or selection.strip().endswith("]")
    ):
        return _dedupe_sorted(_parse_col_range_string(selection, max_len=max_len, open_start=open_start))

    return [_parse_col_atom(selection)]


def _is_effectively_null(value: Any) -> bool:
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        pass
    return isinstance(value, str) and value.strip() == ""


def _normalise_check_regex(check_regex: Any, n_check_cols: int) -> list[str | None]:
    if n_check_cols == 0:
        return []

    if check_regex is None:
        return [None] * n_check_cols

    if isinstance(check_regex, str):
        return [check_regex] * n_check_cols

    if isinstance(check_regex, list):
        if len(check_regex) != n_check_cols:
            raise ValueError(
                f"check_regex must have {n_check_cols} elements; received {len(check_regex)}.")
        if not all(item is None or isinstance(item, str) for item in check_regex):
            raise TypeError("Each element of check_regex must be None or str.")
        return check_regex

    raise TypeError("check_regex must be None, str or list[None | str].")


def _eval_check_logic(valids: list[bool], check_logic: str) -> bool:
    logic = check_logic.strip()

    if logic.upper() == "AND":
        return all(valids)
    if logic.upper() == "OR":
        return any(valids)

    def replace_placeholder(match: re.Match[str]) -> str:
        idx = int(match.group(1))
        if idx >= len(valids):
            raise ValueError(
                f"check_logic references [{idx}], but there are only {len(valids)} check_cols.")
        return f"vals[{idx}]"

    expr = re.sub(r"\[(\d+)\]", replace_placeholder, logic)
    expr = re.sub(r"\bAND\b", "and", expr, flags=re.IGNORECASE)
    expr = re.sub(r"\bOR\b", "or", expr, flags=re.IGNORECASE)
    expr = re.sub(r"\bNOT\b", "not", expr, flags=re.IGNORECASE)

    tree = ast.parse(expr, mode="eval")
    allowed_nodes = (
        ast.Expression,
        ast.BoolOp,
        ast.UnaryOp,
        ast.And,
        ast.Or,
        ast.Not,
        ast.Name,
        ast.Load,
        ast.Subscript,
        ast.Constant,
    )

    for node in ast.walk(tree):
        if not isinstance(node, allowed_nodes):
            raise ValueError(
                f"Disallowed check_logic expression: {check_logic!r}")
        if isinstance(node, ast.Name) and node.id != "vals":
            raise ValueError(f"Disallowed name in check_logic: {node.id!r}")
        if isinstance(node, ast.Constant) and not isinstance(node.value, int):
            raise ValueError(
                f"Disallowed constant in check_logic: {node.value!r}")

    return bool(eval(compile(tree, "<check_logic>", "eval"), {"__builtins__": {}}, {"vals": valids}))


def _validate_check_row(
    values: list[Any],
    patterns: list[str | None],
    check_logic: str,
    check_func: Callable[..., bool] | None,
) -> bool:
    if check_func is not None:
        return bool(check_func(*values))

    valids: list[bool] = []
    for value, pattern in zip(values, patterns):
        if pattern is None:
            valids.append(not _is_effectively_null(value))
        else:
            valids.append(False if _is_effectively_null(value)
                          else re.search(pattern, str(value)) is not None)

    return _eval_check_logic(valids, check_logic)


def _absolute_to_relative_index(index_cols: list[int] | None, final_cols: list[int]) -> int | list[int] | None:
    if not index_cols:
        return None

    position = {col: pos for pos, col in enumerate(final_cols)}
    rel = [position[col] for col in index_cols if col in position]
    if not rel:
        return None
    return rel[0] if len(rel) == 1 else rel


def _set_index_from_positions(
    df: pd.DataFrame, index_positions: int | list[int] | None
) -> pd.DataFrame:
    if index_positions is None:
        return df

    positions = [index_positions] if isinstance(index_positions, int) else list(index_positions)
    if not positions:
        return df

    for pos in positions:
        if pos < 0 or pos >= df.shape[1]:
            raise ValueError(f"Index position out of bounds after column filtering: {pos}")

    names = [df.columns[pos] for pos in positions]
    arrays = [df.iloc[:, pos] for pos in positions]

    if len(positions) == 1:
        new_index = pd.Index(arrays[0], name=names[0])
    else:
        new_index = pd.MultiIndex.from_arrays(arrays, names=names)

    to_drop = set(positions)
    keep_positions = [pos for pos in range(df.shape[1]) if pos not in to_drop]
    out = df.iloc[:, keep_positions].copy()
    out.index = new_index
    return out


def _positions_for_columns(columns: list[int], source_cols: list[int]) -> list[int]:
    position = {col: pos for pos, col in enumerate(source_cols)}
    return [position[col] for col in columns if col in position]


def _apply_post_read_check(
    df: pd.DataFrame,
    *,
    source_cols: list[int],
    sensor_cols: list[int],
    check_regex: Any,
    check_logic: str,
    check_func: Callable[..., bool] | None,
) -> pd.DataFrame:
    sensor_positions = _positions_for_columns(sensor_cols, source_cols)
    if len(sensor_positions) != len(sensor_cols):
        missing = sorted(set(sensor_cols) - set(source_cols))
        raise ValueError(f"check_cols were not read: {missing!r}")

    patterns = _normalise_check_regex(check_regex, len(sensor_cols))
    regex_values = None
    if check_func is None:
        regex_values = df.iloc[:, sensor_positions].astype("string")

    keep_count = 0
    for row_pos in range(len(df)):
        if check_func is None:
            values = list(regex_values.iloc[row_pos])  # type: ignore[union-attr]
        else:
            values = list(df.iloc[row_pos, sensor_positions])

        if not _validate_check_row(values, patterns, check_logic, check_func):
            break
        keep_count += 1

    return df.iloc[:keep_count]


def _read_sensor_columns(
    io: Any,
    *,
    sheet_name: str | int,
    sensor_cols: list[int],
    engine: str | None,
    keep_default_na: bool,
) -> pd.DataFrame:
    raw = pd.read_excel(
        io,
        sheet_name=sheet_name,
        header=None,
        usecols=sensor_cols,
        dtype=str,
        engine=engine,
        keep_default_na=keep_default_na,
    )
    _maybe_seek_start(io)
    return raw


def _sensor_values_at(raw: pd.DataFrame, row: int, n_sensor_cols: int) -> list[Any]:
    return [
        raw.iat[row, pos] if row < len(raw) else None
        for pos in range(n_sensor_cols)
    ]


def _first_valid_sensor_row(
    raw: pd.DataFrame,
    *,
    rows: Iterable[int],
    n_sensor_cols: int,
    check_regex: Any,
    check_logic: str,
    check_func: Callable[..., bool] | None,
) -> int | None:
    patterns = _normalise_check_regex(check_regex, n_sensor_cols)

    for row in rows:
        values = _sensor_values_at(raw, row, n_sensor_cols)
        if _validate_check_row(values, patterns, check_logic, check_func):
            return row

    return None


def _last_unskipped_row_before(row: int, skipped_rows: set[int]) -> int | None:
    for candidate in range(row - 1, -1, -1):
        if candidate not in skipped_rows:
            return candidate
    return None


def _empty_frame_from_header(
    io: Any,
    *,
    sheet_name: str | int,
    header_arg: int | list[int],
    read_cols: list[int],
    engine: str | None,
    keep_default_na: bool,
) -> pd.DataFrame:
    header_rows = [header_arg] if isinstance(header_arg, int) else header_arg
    raw = pd.read_excel(
        io,
        sheet_name=sheet_name,
        header=None,
        nrows=max(header_rows) + 1,
        dtype=object,
        engine=engine,
        keep_default_na=keep_default_na,
    )
    _maybe_seek_start(io)

    def label_at(row: int, col: int, level: int | None = None) -> Any:
        value = raw.iat[row, col] if row < len(raw) and col < raw.shape[1] else None
        if _is_effectively_null(value):
            if level is None:
                return f"Unnamed: {col}"
            return f"Unnamed: {col}_level_{level}"
        return value

    if isinstance(header_arg, int):
        columns = [label_at(header_arg, col) for col in read_cols]
        return pd.DataFrame(columns=columns)

    levels = [
        [label_at(row, col, level) for col in read_cols]
        for level, row in enumerate(header_arg)
    ]
    return pd.DataFrame(columns=pd.MultiIndex.from_arrays(levels))


def _read_all_then_select_columns(
    io: Any,
    *,
    sheet_name: str | int,
    header_arg: int | list[int] | None,
    read_cols: list[int],
    read_nrows: int,
    dtype: Any,
    parse_dates: Any,
    converters: Any,
    na_values: Any,
    keep_default_na: bool,
    engine: str | None,
    decimal: str,
    thousands: str | None,
    verbose: bool,
) -> pd.DataFrame:
    df = pd.read_excel(
        io,
        sheet_name=sheet_name,
        header=header_arg,
        index_col=None,
        usecols=None,
        nrows=read_nrows,
        dtype=dtype,
        parse_dates=parse_dates,
        converters=converters,
        na_values=na_values,
        keep_default_na=keep_default_na,
        engine=engine,
        decimal=decimal,
        thousands=thousands,
        verbose=verbose,
    )
    missing_cols = [col for col in read_cols if col >= df.shape[1]]
    for col in missing_cols:
        if isinstance(df.columns, pd.MultiIndex):
            df[(f"Unnamed: {col}", *("" for _ in range(df.columns.nlevels - 1)))] = pd.NA
        elif header_arg is None:
            df[col] = pd.NA
        else:
            df[f"Unnamed: {col}"] = pd.NA

    return df.iloc[:, read_cols]


def _read_final_columns(
    io: Any,
    *,
    sheet_name: str | int,
    header_arg: int | list[int] | None,
    read_cols: list[int],
    read_nrows: int,
    dtype: Any,
    parse_dates: Any,
    converters: Any,
    na_values: Any,
    keep_default_na: bool,
    engine: str | None,
    decimal: str,
    thousands: str | None,
    verbose: bool,
    preserve_missing_cols: bool,
) -> pd.DataFrame:
    is_multi_header = isinstance(header_arg, list) and len(header_arg) > 1

    if read_nrows == 0 and header_arg is None and preserve_missing_cols:
        return pd.DataFrame(columns=read_cols)

    if read_nrows == 0 and preserve_missing_cols:
        return _empty_frame_from_header(
            io,
            sheet_name=sheet_name,
            header_arg=header_arg,
            read_cols=read_cols,
            engine=engine,
            keep_default_na=keep_default_na,
        )

    if is_multi_header:
        # pandas does not support usecols together with a multi-index header.
        return _read_all_then_select_columns(
            io,
            sheet_name=sheet_name,
            header_arg=header_arg,
            read_cols=read_cols,
            read_nrows=read_nrows,
            dtype=dtype,
            parse_dates=parse_dates,
            converters=converters,
            na_values=na_values,
            keep_default_na=keep_default_na,
            engine=engine,
            decimal=decimal,
            thousands=thousands,
            verbose=verbose,
        )

    pandas_usecols = read_cols if preserve_missing_cols else None
    try:
        return pd.read_excel(
            io,
            sheet_name=sheet_name,
            header=header_arg,
            index_col=None,
            usecols=pandas_usecols,
            nrows=read_nrows,
            dtype=dtype,
            parse_dates=parse_dates,
            converters=converters,
            na_values=na_values,
            keep_default_na=keep_default_na,
            engine=engine,
            decimal=decimal,
            thousands=thousands,
            verbose=verbose,
        )
    except pd.errors.ParserError as exc:
        if "out-of-bounds" not in str(exc) or not preserve_missing_cols:
            raise
        _maybe_seek_start(io)
        return _read_all_then_select_columns(
            io,
            sheet_name=sheet_name,
            header_arg=header_arg,
            read_cols=read_cols,
            read_nrows=read_nrows,
            dtype=dtype,
            parse_dates=parse_dates,
            converters=converters,
            na_values=na_values,
            keep_default_na=keep_default_na,
            engine=engine,
            decimal=decimal,
            thousands=thousands,
            verbose=verbose,
        )


def _read_excel_single(
    io: Any,
    *,
    sheet_name: str | int = 0,
    header: Any = 0,
    autoheader: bool = False,
    index: Any = None,
    usecols: Any = None,
    userows: Any = None,
    nrows: int | None = None,
    ncols: int | None = None,
    skip_rows: Any = None,
    skip_cols: Any = None,
    check_cols: Any = None,
    check_regex: Any = None,
    check_logic: str = "OR",
    check_func: Callable[..., bool] | None = None,
    precheck: bool = True,
    dtype: Any = None,
    parse_dates: Any = False,
    converters: Any = None,
    na_values: Any = None,
    keep_default_na: bool = True,
    engine: str | None = None,
    decimal: str = ".",
    thousands: str | None = None,
    verbose: bool = False,
) -> pd.DataFrame:
    if nrows is not None and nrows < 0:
        raise ValueError("nrows cannot be negative.")
    if ncols is not None and ncols < 0:
        raise ValueError("ncols cannot be negative.")
    if check_func is not None and not callable(check_func):
        raise TypeError("check_func must be callable.")
    if not isinstance(precheck, bool):
        raise TypeError("precheck must be a boolean.")
    if not isinstance(autoheader, bool):
        raise TypeError("autoheader must be a boolean.")
    if autoheader and check_cols is None:
        raise ValueError("autoheader requires check_cols.")

    max_rows, max_cols = _get_sheet_dimensions(
        io,
        sheet_name=sheet_name,
        engine=engine,
        keep_default_na=keep_default_na,
    )

    sensor_cols: list[int] | None = None
    if check_cols is not None:
        sensor_cols = _parse_cols(
            check_cols, max_len=max_cols, open_start=0) or []
        if not sensor_cols:
            raise ValueError("check_cols did not select any columns.")

    force_empty = False
    if autoheader:
        assert sensor_cols is not None
        auto_skipped_rows = set(_parse_rows(
            skip_rows, max_len=max_rows, open_start=0) or [])
        raw_header = _read_sensor_columns(
            io,
            sheet_name=sheet_name,
            sensor_cols=sensor_cols,
            engine=engine,
            keep_default_na=False,
        )
        candidate_rows = [
            row for row in range(max_rows) if row not in auto_skipped_rows]
        first_data_row = _first_valid_sensor_row(
            raw_header,
            rows=candidate_rows,
            n_sensor_cols=len(sensor_cols),
            check_regex=check_regex,
            check_logic=check_logic,
            check_func=check_func,
        )
        if first_data_row is None:
            header = None
            force_empty = True
        else:
            header = _last_unskipped_row_before(
                first_data_row, auto_skipped_rows)

    header_rows = [] if header is None else (
        _parse_rows(header, max_len=max_rows, open_start=0) or [])
    header_rows = _dedupe_sorted(header_rows)
    data_start = (max(header_rows) + 1) if header_rows else 0

    selected_rows = _parse_rows(userows, max_len=max_rows, open_start=data_start)
    if selected_rows is None:
        selected_rows = list(range(data_start, max_rows))

    header_set = set(header_rows)
    selected_rows = [row for row in selected_rows if row >=
                     data_start and row not in header_set]

    skipped_rows = set(_parse_rows(
        skip_rows, max_len=max_rows, open_start=data_start) or [])
    selected_rows = [row for row in selected_rows if row not in skipped_rows]

    if force_empty:
        selected_rows = []

    if sensor_cols is not None and precheck:
        raw_stop = _read_sensor_columns(
            io,
            sheet_name=sheet_name,
            sensor_cols=sensor_cols,
            engine=engine,
            keep_default_na=False,
        )

        patterns = _normalise_check_regex(check_regex, len(sensor_cols))
        truncated_rows: list[int] = []

        for row in selected_rows:
            values = _sensor_values_at(raw_stop, row, len(sensor_cols))
            if not _validate_check_row(values, patterns, check_logic, check_func):
                break
            truncated_rows.append(row)

        selected_rows = truncated_rows

    if nrows is not None:
        selected_rows = selected_rows[:nrows]

    index_cols = _parse_cols(index, max_len=max_cols, open_start=0)
    base_cols = _parse_cols(usecols, max_len=max_cols, open_start=0)
    if base_cols is None:
        if index_cols:
            final_cols = list(range(max(index_cols) + 1, max_cols))
        else:
            final_cols = list(range(max_cols))
    else:
        final_cols = base_cols[:]

    if index_cols:
        final_cols = _dedupe_sorted([*final_cols, *index_cols])

    skipped_cols = set(_parse_cols(
        skip_cols, max_len=max_cols, open_start=0) or [])
    final_cols = [col for col in _dedupe_sorted(
        final_cols) if col not in skipped_cols]

    if not final_cols:
        raise ValueError(
            "No columns remain to be read after applying usecols/skip_cols/index.")

    if ncols is not None:
        index_set = set(index_cols or [])
        limited_data_cols = [col for col in final_cols if col not in index_set][:ncols]
        final_cols = _dedupe_sorted([*limited_data_cols, *(index_cols or [])])

    if not final_cols:
        raise ValueError(
            "No columns remain to be read after applying usecols/skip_cols/index/ncols.")

    read_cols = final_cols
    if sensor_cols is not None and not precheck:
        read_cols = _dedupe_sorted([*final_cols, *sensor_cols])
    preserve_missing_cols = (
        base_cols is not None
        or index_cols is not None
        or skipped_cols
        or ncols is not None
        or (sensor_cols is not None and not precheck)
    )

    header_arg: int | list[int] | None
    if header is None:
        header_arg = None
    elif len(header_rows) == 1:
        header_arg = header_rows[0]
    else:
        header_arg = header_rows

    if selected_rows:
        read_nrows = max(selected_rows) - data_start + 1
    else:
        read_nrows = 0

    df = _read_final_columns(
        io,
        sheet_name=sheet_name,
        header_arg=header_arg,
        read_cols=read_cols,
        read_nrows=read_nrows,
        dtype=dtype,
        parse_dates=parse_dates,
        converters=converters,
        na_values=na_values,
        keep_default_na=keep_default_na,
        engine=engine,
        decimal=decimal,
        thousands=thousands,
        verbose=verbose,
        preserve_missing_cols=bool(preserve_missing_cols),
    )
    if not preserve_missing_cols:
        read_cols = list(range(df.shape[1]))
        final_cols = read_cols

    if selected_rows:
        selected_set = set(selected_rows)
        absolute_rows = list(range(data_start, data_start + len(df)))
        positions = [pos for pos, abs_row in enumerate(
            absolute_rows) if abs_row in selected_set]
        df = df.iloc[positions]
    else:
        df = df.iloc[0:0]

    if sensor_cols is not None and not precheck:
        df = _apply_post_read_check(
            df,
            source_cols=read_cols,
            sensor_cols=sensor_cols,
            check_regex=check_regex,
            check_logic=check_logic,
            check_func=check_func,
        )

    final_positions = _positions_for_columns(final_cols, read_cols)
    df = df.iloc[:, final_positions]

    index_col = _absolute_to_relative_index(index_cols, final_cols)
    df = _set_index_from_positions(df, index_col)

    if index_col is None:
        df = df.reset_index(drop=True)

    return df


def read_excel(
    io: Any,
    sheet_name: str | int = 0,
    header: Any = 0,
    autoheader: bool = False,
    index: Any = None,
    usecols: Any = None,
    userows: Any = None,
    nrows: int | None = None,
    ncols: int | None = None,
    skip_rows: Any = None,
    skip_cols: Any = None,
    check_cols: Any = None,
    check_regex: Any = None,
    check_logic: str = "OR",
    check_func: Callable[..., bool] | None = None,
    precheck: bool = True,
    dtype: Any = None,
    parse_dates: Any = False,
    converters: Any = None,
    na_values: Any = None,
    keep_default_na: bool = True,
    engine: str | None = None,
    decimal: str = ".",
    thousands: str | None = None,
    verbose: bool = False,
) -> pd.DataFrame:
    """
    Reads an Excel file using absolute and intuitive coordinates for rows and columns.

    Supported conventions:
    - Individual rows: 0-indexed int or 1-indexed numeric str.
    - Row ranges: tuple, "a:b" (1-indexed), "[a:b]" (0-indexed).
    - Individual columns: 0-indexed int or Excel letters.
    - Column ranges: tuple, "A:D" (letters), "[a:b]" (0-indexed).
    - Open ranges: ":b", "a:", "[:b]", "[a:]".

    Key rules:
    - userows=None reads from the row immediately following the last header row.
    - Open-start userows range starts immediately after the last header row.
    - usecols=None reads all columns, or columns after the last index column when index is set.
    - skip_rows is applied before nrows, thus not counting towards the limit.
    - skip_cols is applied before ncols, thus not counting towards the limit.
    - skip_cols removes columns even if they were included by usecols or index.
    - check_cols uses a raw string sensor read when precheck=True.
    - autoheader=True uses check_cols to place the header on the last
      non-skipped row before the first valid data row.
    """
    if sheet_name is None or isinstance(sheet_name, list):
        raise TypeError(
            "read_excel reads a single sheet; pass a sheet name or index.")

    return _read_excel_single(
        io,
        sheet_name=sheet_name,
        header=header,
        autoheader=autoheader,
        index=index,
        usecols=usecols,
        userows=userows,
        nrows=nrows,
        ncols=ncols,
        skip_rows=skip_rows,
        skip_cols=skip_cols,
        check_cols=check_cols,
        check_regex=check_regex,
        check_logic=check_logic,
        check_func=check_func,
        precheck=precheck,
        dtype=dtype,
        parse_dates=parse_dates,
        converters=converters,
        na_values=na_values,
        keep_default_na=keep_default_na,
        engine=engine,
        decimal=decimal,
        thousands=thousands,
        verbose=verbose,
    )


