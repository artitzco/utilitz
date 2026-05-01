import re
import string
import warnings
import pandas as pd


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


def _check_pandas():
    if pd is None:
        raise ImportError(
            "The 'pandas' library is required for excel utilities. "
            "Install it with: pip install utilitz[office]"
        )


def read_excel_table(io,
                     sheet_name=0,
                     usecols=None,
                     header=0,
                     nrows=None,
                     checkcol=None,
                     patterncol=None,
                     findheaders=False,
                     raw_df=None,
                     **kwargs):
    """
    [DEPRECATED] Use read_excel instead.
    
    Reads a table from an Excel sheet with optional row filtering
    based on a control column and a regex pattern.
    """
    warnings.warn(
        "read_excel_table is deprecated and will be removed in a future version. "
        "Please use read_excel from utilitz.excel instead.",
        DeprecationWarning,
        stacklevel=2
    )
    _check_pandas()
    if raw_df is not None:
        raise ValueError('"raw_df" is not implemented yet')

    max_nrows = nrows if nrows is not None else float('inf')

    if findheaders:
        raw_df = pd.read_excel(io,
                               header=None,
                               sheet_name=sheet_name,
                               dtype=str)
        # In the future, the first column of usecols can be used
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
                if not patterncol or re.match(patterncol, x):
                    nrows += 1
            else:
                break

    return pd.read_excel(io,
                         sheet_name=sheet_name,
                         usecols=usecols,
                         header=header,
                         nrows=nrows,
                         **kwargs)
