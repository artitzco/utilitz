import re
import uuid


# Global registry of all visible patterns.
# Used to discover which patterns participate in a regex and to decode matches.
_PATTERNS = {}


def new_id(length=8):
    while True:
        _id = 'pattern' + uuid.uuid4().hex[:length]
        if _id not in _PATTERNS:
            return _id


def get_pattern(pattern_id):
    return _PATTERNS.get(pattern_id, None)


def find_patterns(regex=None, drop_hidden=True, names=False):
    if regex is None:
        pattern_list = [pattern
                        for pattern in _PATTERNS.values()
                        if not drop_hidden or not pattern.hidden]
    else:
        pattern_list = [pattern
                        for pattern_id in dict.fromkeys(re.findall(r'\?P<(pattern.{8})', regex))
                        if (pattern := get_pattern(pattern_id)) and (not drop_hidden or not pattern.hidden)]
    if not names:
        return pattern_list

    return list(dict.fromkeys([name for subnames in [[pattern.name] if isinstance(pattern.name, str)
                                                     else pattern.name for pattern in pattern_list] for name in subnames]))


def decode(regex, text, split=False, kind=None):
    from .patterns import Pattern

    regex_list = regex if isinstance(regex, list) else [regex]
    regex_list = [str(patt)
                  if isinstance(patt, Pattern) else patt for patt in regex_list]
    result = [{name: []
               for name in find_patterns(regex_str, names=True)}
              for regex_str in regex_list]
    if not split:
        result = [{k: v for d in result for k, v in d.items()}]

    for regex_index, regex_str in enumerate(regex_list):
        for match in re.finditer(regex_str, text):
            for pattern in find_patterns(regex_str):
                for name, value in pattern.decode(match, to_dict=True).items():
                    index = regex_index if split else 0
                    if isinstance(value, list):
                        result[index][name] += value
                    else:
                        result[index][name].append(value)

    def apply_kind(x):
        if not x:
            return None
        if kind == 'first':
            return x[0]
        if kind == 'last':
            return x[-1]
        return x

    result = [{name: apply_kind(lst)
               for name, lst in dic.items()}
              for dic in result]

    return result if split else result[0]
