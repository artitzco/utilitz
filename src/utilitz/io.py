import re
import os
from pathlib import Path
from itertools import islice

def scan_files(regex, path='**/*', ignore_case=False, encoding='utf-8'):
    """
    Search for a regular expression in files selected via a glob pattern.
    
    Args:
        regex (str): The regular expression string to search for.
        path (str): Glob pattern relative to the CWD (e.g., 'src/**/*.py' or '**/*').
        ignore_case (bool): If True, performs case-insensitive search.
        encoding (str): Expected file encoding.
        
    Yields:
        dict: A dictionary with keys 'path', 'line', and 'content'.
    """
    flags = re.IGNORECASE if ignore_case else 0
    pattern_compiled = re.compile(regex, flags)
    
    base_path = Path.cwd()
    
    for file_path in base_path.glob(path):
        # 1. Directories: glob finds folders, we ignore them.
        # 2. Permissions: os.access checks for read permission at the OS level.
        if not file_path.is_file() or not os.access(file_path, os.R_OK):
            continue
            
        try:
            # We don't use errors='ignore' so binary files raise UnicodeDecodeError
            with open(file_path, 'r', encoding=encoding) as f:
                for i, line in enumerate(f, 1):
                    if pattern_compiled.search(line):
                        yield {
                            'path': str(file_path.relative_to(base_path)),
                            'line': i,
                            'content': line.rstrip('\n') # remove trailing newline
                        }
        except (UnicodeDecodeError, PermissionError):
            # 3. Binary Files / Runtime Permission Issues:
            # If the file is binary (e.g., .png or .pyc), it will fail to decode to text.
            # If there's a permission issue during opening, it will raise PermissionError.
            # In both cases, we simply ignore the file and continue.
            pass

def scan_n_files(regex, n, offset=0, path='**/*', ignore_case=False, encoding='utf-8'):
    """
    Search for a regular expression and return a limited list of results.
    
    Args:
        regex (str): The regular expression string to search for.
        n (int): Maximum number of results to return.
        offset (int): Number of initial results to skip (useful for pagination).
        path (str): Glob pattern relative to the CWD (e.g., 'src/**/*.py' or '**/*').
        ignore_case (bool): If True, performs case-insensitive search.
        encoding (str): Expected file encoding.
        
    Returns:
        list[dict]: A list of matches.
    """
    generator = scan_files(regex, path=path, ignore_case=ignore_case, encoding=encoding)
    return list(islice(generator, offset, offset + n))
