from . import excel
from . import path
from . import sys
from . import io
from . import crypto
import pickle
import json


def save_text(lst, file_path):
    """
    Saves a list of text strings to a plain text file,
    writing each element of the list as a separate line.

    Parameters:
    ----------
    lst : list of str
        List of text strings to be saved.
    file_path : str
        Path to the file where the content will be written.
    """
    with open(file_path, 'w', encoding='utf-8') as file_obj:
        for line in lst:
            file_obj.write(line + "\n")


def load_text(file_path):
    """
    Loads the content of a text file as a list of lines,
    stripping newline characters at the end of each line.

    Parameters:
    ----------
    file_path : str
        Path to the file to be read.

    Returns:
    -------
    list of str
        List of lines from the file without newline characters.
    """
    with open(file_path, 'r', encoding='utf-8') as file_obj:
        text_list = [line.strip() for line in file_obj]
    return text_list


def save_json(data, file_path):
    """
    Saves a Python object (such as a dict or list) to a JSON file.

    Parameters:
    ----------
    data : dict or list
        JSON-serializable Python object to be saved.
    file_path : str
        Path to the file where the JSON will be written.
    """
    with open(file_path, 'w', encoding='utf-8') as file_obj:
        json.dump(data, file_obj, ensure_ascii=False, indent=4)


def load_json(file_path):
    """
    Loads a Python object from a JSON file.

    Parameters:
    ----------
    file_path : str
        Path to the JSON file.

    Returns:
    -------
    dict or list
        Python object loaded from the JSON file.
    """
    with open(file_path, 'r', encoding='utf-8') as file_obj:
        obj = json.load(file_obj)
    return obj


def save_object(obj, file_path):
    """
    Serializes and saves a Python object to a binary file using pickle.

    Parameters:
    ----------
    obj : any
        Python object to be serialized.
    file_path : str
        Path to the file where the object will be saved.
    """
    with open(file_path, "wb") as file_obj:
        pickle.dump(obj, file_obj)


def load_object(file_path):
    """
    Loads a previously pickled Python object from a binary file.

    Parameters:
    ----------
    file_path : str
        Path to the pickle (.pkl) file to be read.

    Returns:
    -------
    any
        Deserialized Python object from the file.
    """
    with open(file_path, "rb") as file_obj:
        obj = pickle.load(file_obj)
    return obj
