import string
import pandas as pd
import re


def encode_column(column):
    """
    Converts a zero-based column index into an Excel-style column name.

    Parameters:
    ----------
    column : int
        Zero-based column index (e.g., 0 for "A", 25 for "Z").

    Returns:
    -------
    str
        Excel-style column name.
    """
    words = list(string.ascii_uppercase)
    n = len(words)
    code = ''
    column += 1
    while column > 0:
        column, residual = divmod(column-1, n)
        code += words[residual]
    return code[::-1]


def decode_column(code):
    """
    Converts an Excel-style column name into a zero-based column index.

    Parameters:
    ----------
    code : str
        Excel-style column name (e.g., "A", "Z", "AA").

    Returns:
    -------
    int
        Zero-based column index.
    """
    words = list(string.ascii_uppercase)
    n = len(words)
    value = 0
    for i, word in enumerate(code[::-1]):
        value += (words.index(word) + 1) * n ** i
    return value - 1


def read_excel_table(io,
                     sheet_name=0,
                     usecols=None,
                     header=0,
                     nrows=None,
                     checkcol=None,
                     patterncol=None,
                     findtable=False,
                     raw_df=None,
                     **kwargs):
    """
    Reads a table from an Excel sheet with optional row filtering
    based on a control column and a regex pattern.

    Parameters:
    ----------
    io : str, path object, or file-like object
        Path, URL, or buffer pointing to the Excel file.
    sheet_name : int or str, default=0
        Name or index of the sheet to load.
    usecols : str, list, or None, optional
        Subset of columns to select (as in pandas.read_excel).
    header : int or None, default=0
        Row to use as column names. If None, no header is used.
    nrows : int or None, optional
        Number of rows to read. If None, determined dynamically when
        `checkcol` is provided.
    checkcol : str, optional
        Excel-style column name (e.g., "A") used to determine how many
        rows to include. Reading stops at the first blank or invalid row.
    patterncol : str, optional
        Regular expression. Only rows matching this pattern in `checkcol`
        are included.
    findtable : bool, default=False
        Placeholder for future implementation to auto-detect the table
        start when header is None. Currently not implemented.
    raw_df : pandas.DataFrame, optional
        Preloaded DataFrame to avoid re-reading the Excel file.
    **kwargs : dict
        Additional arguments passed to pandas.read_excel.

    Returns:
    -------
    pandas.DataFrame
        DataFrame containing the requested portion of the sheet.

    Examples:
    --------
    >>> # Read until the first empty cell in column "A"
    >>> df = read_excel_table("data.xlsx", checkcol="A")

    >>> # Read rows in column "B" that start with digits
    >>> df = read_excel_table("data.xlsx", checkcol="B", patterncol=r"^\\d+")
    """
    if raw_df is None:
        raw_df = pd.read_excel(io, sheet_name=sheet_name, dtype=str)
    if nrows is None:
        max_nrows = float('inf')

    if header is None and findtable:
        raise NotImplemented()

    if checkcol is not None:
        nrows = 0
        check_column = raw_df.iloc[header:, decode_column(checkcol)]

        for x in check_column:
            if not pd.isna(x) and nrows < max_nrows:
                if patterncol and re.match(patterncol, x) or not patterncol:
                    nrows += 1
            else:
                break

    return pd.read_excel(io,
                         sheet_name=sheet_name,
                         usecols=usecols,
                         header=header,
                         nrows=nrows,
                         **kwargs)
