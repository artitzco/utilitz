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
                     usecols=None,  # En el futuro detectar rangos de columnas
                     header=0,  # En el futuro utilizar multiheaders
                     nrows=None,
                     checkcol=None,  # En el futuro puede ser numérica
                     patterncol=None,
                     findheaders=False,
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
    findheaders : bool, default=False
        If True, detects multiple tables in the sheet by looking for
        non-empty cells in `checkcol`. Returns a list of DataFrames.
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
    if raw_df is not None:
        raise ValueError('"raw_df" is not implemented yet')

    if nrows is None:
        max_nrows = float('inf')

    if findheaders:
        raw_df = pd.read_excel(io,
                               header=None,
                               sheet_name=sheet_name,
                               dtype=str)
        # En el futuro se puede utilizar la primera columna de usecols
        checkcol = 'A' if checkcol is None else checkcol
        column = raw_df[raw_df.columns[decode_column(
            checkcol)]].reset_index(drop=True)
        condition = ~column.isna()
        if patterncol:
            condition &= column.apply(lambda x:
                                      bool(re.match(patterncol, x))
                                      if isinstance(x, str) else False)

        headers = (column[condition.astype(int).diff() == 1].index-1).tolist()
        if condition.iloc[0]:
            headers = [None] + headers

        return [read_excel_table(io,
                                 sheet_name=sheet_name,
                                 usecols=usecols,
                                 header=header,
                                 nrows=nrows,
                                 checkcol=checkcol,
                                 patterncol=patterncol,
                                 findheaders=False,
                                 raw_df=None,
                                 **kwargs) for header in headers]
    raw_df = pd.read_excel(io,
                           sheet_name=sheet_name,
                           dtype=str)

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
