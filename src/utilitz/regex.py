import uuid
import re


# Global registry of all visible patterns.
# Used to discover which patterns participate in a regex and to decode matches.
_PATTERNS = {}


def new_id(length=8):
    """
    Generate a unique pattern identifier.

    The identifier is guaranteed to be unique within the global
    pattern registry and is used as the base name for regex groups.
    """

    while True:
        _id = 'pattern' + uuid.uuid4().hex[:length]
        if _id not in _PATTERNS:
            return _id


def get_pattern(pattern_id):
    """
    Retrieve a Pattern instance from the global registry by its id.
    """
    return _PATTERNS.get(pattern_id, None)


def find_patterns(regex=None, drop_hidden=True, names=False):
    """
    Discover patterns involved in a regex.

    If regex is None, returns all registered patterns.
    If regex is provided, only patterns whose ids appear in the regex
    group names are returned.

    Parameters:
    - drop_hidden: ignore patterns marked as hidden
    - names: return semantic names instead of Pattern instances
    """
    if regex is None:
        pattern_list = [pattern
                        for pattern in _PATTERNS.values()
                        if not drop_hidden or not pattern.hidden]
    else:
        pattern_list = [pattern
                        for id in dict.fromkeys(re.findall(r'\?P<(pattern.{8})', regex))
                        if (pattern := get_pattern(id)) and (not drop_hidden or not pattern.hidden)]
    if not names:
        return pattern_list

    return list(dict.fromkeys([name for subnames in [[pattern.name] if isinstance(pattern.name, str)
                                                     else pattern.name for pattern in pattern_list] for name in subnames]))


def decode(regex, text, split=False, kind=None):
    """
    Apply one or more regex expressions to a text and decode the matches
    using the registered patterns.

    Parameters:
    - regex: a regex string, Pattern instance, or list of them
    - split: return one result per regex if True
    - kind: post-process result lists ('first', 'last', or None)

    Returns:
    A dictionary (or list of dictionaries) mapping pattern names to
    decoded semantic values.
    """
    regex_list = regex if isinstance(regex, list) else [regex]
    regex_list = [patt.regex
                  if isinstance(patt, Pattern) else patt for patt in regex_list]
    result = [{name: []
               for name in find_patterns(regex, names=True)}
              for regex in regex_list]
    if not split:
        result = [{k: v for d in result for k, v in d.items()}]

    for regex_index, regex in enumerate(regex_list):
        for match in re.finditer(regex, text):
            for pattern in find_patterns(regex):
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


class Pattern:
    """
    Base class for all regex patterns.

    A Pattern represents a reusable regex fragment that may:
    - create a named capturing group (visible)
    - participate in pattern discovery (not hidden)
    - decode its match into a semantic value

    Subclasses are expected to override `regex` and `decode`
    to implement complex or structured patterns.
    """

    def __init__(self, regex, name=None, hidden=None, visible=None):
        self._regex = regex
        self.name = name
        self.hidden = (hidden
                       if isinstance(hidden, bool) else (name is None))
        self.visible = (visible
                        if isinstance(visible, bool) else (name is not None))
        if self.visible:
            self.id = new_id()
            _PATTERNS[self.id] = self

    def get_id(self, varname=None):
        if not self.visible:
            raise ValueError(
                "Cannot get id from a non-visible Pattern instance.")

        if varname is not None:
            return f'{self.id}_{varname}'
        return self.id

    def new_group(self, regrex, varname=None):
        if self.visible:
            return r'(?P<' + self.get_id(varname) + r'>' + regrex + r')'
        return regrex

    @property
    def regex(self):
        return self._regex

    def decode(self, match, to_dict=False):
        if not self.visible:
            raise ValueError(
                "Cannot decode a match from a non-visible Pattern instance.")
        if to_dict:
            return {self.name: match.group()}
        return match.group()

    def __str__(self):
        return self.new_group(self.regex)

    def __repr__(self):
        return f"Pattern({self.__str__()})"

    def __add__(self, other):
        return self.__str__() + other

    def __radd__(self, other):
        return other + self.__str__()


class Integer(Pattern):
    """
    Pattern that matches and decodes integer numbers.

    Supports:
    - optional sign
    - optional currency symbol
    - optional thousands separator

    The decoded value is returned as an int.
    """

    def __init__(self,
                 name=None,
                 integer_sep=None,
                 currency_sym=None,
                 signum=True):
        super().__init__(regex=None,
                         name=name)
        self.separator = integer_sep and re.escape(integer_sep)
        self.currency_symbol = currency_sym and re.escape(currency_sym)
        self.signum = signum

    @property
    def regex(self):
        signum_regex = r'(?:-\s*|\+\s*)?' if self.signum else r''
        currency_regex = self.currency_symbol + r'\s*' if self.currency_symbol else r''
        prefix = self.new_group(rf'(?:{signum_regex}{currency_regex}|{currency_regex}{signum_regex})',
                                'prefix')
        if self.separator is None:
            integer = self.new_group(r'\d+', 'integer')
        else:
            integer = self.new_group(r'\d{1,3}(?:'
                                     + self.separator
                                     + r'\d{3})*', 'integer')
        return prefix + integer

    def decode(self, match, to_dict=False):
        if not self.visible:
            raise ValueError(
                "Cannot decode a match from a non-visible Pattern instance.")
        prefix_match = match.group(self.get_id('prefix'))
        currency_symbol = self.currency_symbol or ''
        signum_symbol = re.sub(currency_symbol, '', prefix_match).strip()
        signum = 1 - 2 * bool(prefix_match and signum_symbol == '-')
        integer_match = match.group(self.get_id('integer'))
        separator = self.separator or ''
        integer = int(re.sub(separator, '', integer_match))
        if to_dict:
            return {self.name: signum * integer}
        return signum * integer

    def __repr__(self):
        return f"Integer({self.__str__()})"


class Number(Integer):
    """
    Extension of Integer that supports decimal numbers.

    The decoded value is returned as a float.
    """

    def __init__(self,
                 name=None,
                 integer_sep=None,
                 decimal_sep='.',
                 currency_sym=None,
                 signum=True):
        super().__init__(name=name,
                         integer_sep=integer_sep,
                         currency_sym=currency_sym,
                         signum=signum)
        self.decimal_sep = re.escape(decimal_sep)

    @property
    def regex(self):
        return (super().regex
                + r'(?:'
                + self.new_group(self.decimal_sep + r'\d+', 'decimal')
                + ')?')

    def decode(self, match, to_dict=False):
        integer = super().decode(match)
        signum = -1 if integer < 0 else 1
        integer = abs(integer)
        decimal_match = match.group(self.get_id('decimal'))
        if decimal_match:
            decimal = float(re.sub(self.decimal_sep, '.', decimal_match))
            number = integer + decimal
        else:
            number = integer
        if to_dict:
            return {self.name: signum * number}
        return signum * number

    def __repr__(self):
        return f"Number({self.__str__()})"


class First(Pattern):
    """
    Control pattern that matches multiple regex alternatives
    and decodes only the first successful match.

    This pattern does not introduce its own semantic value.
    Instead, it delegates decoding to the matched sub-patterns.
    """

    def __init__(self, *regexes):
        super().__init__(regex=None,
                         name=None,
                         hidden=False,
                         visible=True
                         )
        self.name = list(dict.fromkeys([elem
                                        for sublist in [find_patterns(rx, names=True)
                                                        for rx in regexes] for elem in sublist]))
        self.regexes = regexes
        self.patterns = [find_patterns(rx) for rx in regexes]
        for pattern_list in self.patterns:
            for pattern in pattern_list:
                pattern.hidden = True

    @property
    def regex(self):
        return r'(?:'+r'|'.join([self.new_group(rx, i)
                                 for i, rx in enumerate(self.regexes)]) + r')'

    def decode(self, match, to_dict=False):
        for i, pattern_list in enumerate(self.patterns):
            if match.group(self.get_id(i)):
                break

        if not to_dict:
            result = []
            for pattern in pattern_list:
                if match.group(pattern.id):
                    if isinstance(value := pattern.decode(match), list):
                        result += value
                    else:
                        result.append(value)
            return result

        result = {name: [] for name in self.name}
        for pattern in pattern_list:
            if match.group(pattern.id):
                for name, value in pattern.decode(match, to_dict=True).items():
                    if isinstance(value, list):
                        result[name] += value
                    else:
                        result[name].append(value)
        return result

    def __repr__(self):
        return f"First({self.__str__()})"
