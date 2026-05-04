import re

from .core import _PATTERNS, find_patterns, new_id


class Pattern:
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
            return {self.name: match.group(self.id)}
        return match.group(self.id)

    def __str__(self):
        return self.new_group(self.regex)

    def __repr__(self):
        return f"Pattern({self.__str__()})"

    def __add__(self, other):
        return self.__str__() + other

    def __radd__(self, other):
        return other + self.__str__()


class Integer(Pattern):
    def __init__(self,
                 name=None,
                 integer_sep=None,
                 integer_digits=None,
                 signum=True,
                 signum_space=False):
        super().__init__(regex=None,
                         name=name)
        self.separator = integer_sep and re.escape(integer_sep)
        self.integer_digits = integer_digits
        self.signum = signum
        self.signum_space = signum_space

    @property
    def regex(self):
        if not self.signum:
            signum_regex = r''
        else:
            if self.signum_space:
                signum_regex = r'(?:-\s*|\+\s*)?'
            else:
                signum_regex = r'(?:-|\+)?'
        prefix = self.new_group(signum_regex, 'prefix')
        digits_quantifier = '+' if self.integer_digits is None else '{' + str(self.integer_digits) + '}'
        if self.separator is None:
            integer_regex = r'\d' + digits_quantifier
        else:
            if self.integer_digits is None:
                integer_regex = r'\d{1,3}(?:' + self.separator + r'\d{3})*'
            else:
                lead_digits = self.integer_digits % 3 or 3
                grouped_chunks = (self.integer_digits - lead_digits) // 3
                integer_regex = r'\d{' + str(lead_digits) + r'}(?:' + self.separator + r'\d{3}){' + str(grouped_chunks) + r'}'
        integer = self.new_group(integer_regex, 'integer')
        return prefix + integer

    def decode(self, match, to_dict=False):
        if not self.visible:
            raise ValueError(
                "Cannot decode a match from a non-visible Pattern instance.")
        integer_match = match.group(self.get_id('integer'))
        if integer_match is None:
            return {self.name: None} if to_dict else None

        prefix_match = match.group(self.get_id('prefix')) or ''
        signum_symbol = prefix_match.strip()
        signum = 1 - 2 * bool(prefix_match and signum_symbol == '-')
        separator = self.separator or ''
        integer = int(re.sub(separator, '', integer_match))
        if to_dict:
            return {self.name: signum * integer}
        return signum * integer

    def __repr__(self):
        return f"Integer({self.__str__()})"


class Number(Integer):
    def __init__(self,
                 name=None,
                 integer_sep=None,
                 integer_digits=None,
                 decimal_sep='.',
                 decimal_digits=None,
                 signum=True,
                 signum_space=False):
        super().__init__(name=name,
                         integer_sep=integer_sep,
                         integer_digits=integer_digits,
                         signum=signum,
                         signum_space=signum_space)
        self.decimal_sep = re.escape(decimal_sep)
        self.decimal_digits = decimal_digits

    @property
    def regex(self):
        decimal_quantifier = '+' if self.decimal_digits is None else '{' + str(self.decimal_digits) + '}'
        return (super().regex
                + r'(?:'
                + self.new_group(self.decimal_sep + r'\d' + decimal_quantifier, 'decimal')
                + ')?')

    def decode(self, match, to_dict=False):
        integer = super().decode(match)
        if integer is None:
            return {self.name: None} if to_dict else None

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
    def __init__(self, *regexes):
        super().__init__(regex=None,
                         name=None,
                         hidden=False,
                         visible=True
                         )

        regexes = [str(rx) if isinstance(rx, Pattern)
                   else rx for rx in regexes]
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
        else:
            raise ValueError("No alternative matched in First pattern")

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


class Currency(Number):
    def __init__(self, name=None, integer_sep=',', integer_digits=None, decimal_sep='.', decimal_digits=None, currency_sym='$', signum_space=False):
        super().__init__(name=name,
                         integer_sep=integer_sep,
                         integer_digits=integer_digits,
                         decimal_sep=decimal_sep,
                         decimal_digits=decimal_digits,
                         signum=True,
                         signum_space=signum_space)
        self.currency_symbol = re.escape(currency_sym)

    @property
    def regex(self):
        currency_regex = self.currency_symbol + r'\s*' if self.currency_symbol else r''
        signum_regex = r'(?:-\s*|\+\s*)?' if self.signum_space else r'(?:-|\+)?'
        prefix = self.new_group(rf'(?:{signum_regex}{currency_regex}|{currency_regex}{signum_regex})',
                                'prefix')
        digits_quantifier = '+' if self.integer_digits is None else '{' + str(self.integer_digits) + '}'
        if self.separator is None:
            integer_regex = r'\d' + digits_quantifier
        else:
            if self.integer_digits is None:
                integer_regex = r'\d{1,3}(?:' + self.separator + r'\d{3})*'
            else:
                lead_digits = self.integer_digits % 3 or 3
                grouped_chunks = (self.integer_digits - lead_digits) // 3
                integer_regex = r'\d{' + str(lead_digits) + r'}(?:' + self.separator + r'\d{3}){' + str(grouped_chunks) + r'}'
        integer = self.new_group(integer_regex, 'integer')
        decimal_quantifier = '+' if self.decimal_digits is None else '{' + str(self.decimal_digits) + '}'
        decimal = r'(?:' + self.new_group(self.decimal_sep + r'\d' + decimal_quantifier, 'decimal') + ')?'
        return prefix + integer + decimal

    def decode(self, match, to_dict=False):
        integer_match = match.group(self.get_id('integer'))
        if integer_match is None:
            return {self.name: None} if to_dict else None

        prefix_match = match.group(self.get_id('prefix')) or ''
        signum_symbol = re.sub(self.currency_symbol or '', '', prefix_match).strip()
        signum = 1 - 2 * bool(prefix_match and signum_symbol == '-')
        separator = self.separator or ''
        integer = int(re.sub(separator, '', integer_match))

        decimal_match = match.group(self.get_id('decimal'))
        number = float(integer)
        if decimal_match:
            decimal = float(re.sub(self.decimal_sep, '.', decimal_match))
            number += decimal
        number *= signum
        return {self.name: number} if to_dict else number


class Date(Pattern):
    DEFAULT_MONTH_ABBR = {
        1:  ['jan', 'ene'],
        2:  ['feb'],
        3:  ['mar'],
        4:  ['apr', 'abr'],
        5:  ['may'],
        6:  ['jun'],
        7:  ['jul'],
        8:  ['aug', 'ago'],
        9:  ['sep', 'sept'],
        10: ['oct'],
        11: ['nov'],
        12: ['dec', 'dic'],
    }

    DEFAULT_MONTH_FULL = {
        1:  ['january', 'enero'],
        2:  ['february', 'febrero'],
        3:  ['march', 'marzo'],
        4:  ['april', 'abril'],
        5:  ['may', 'mayo'],
        6:  ['june', 'junio'],
        7:  ['july', 'julio'],
        8:  ['august', 'agosto'],
        9:  ['september', 'septiembre'],
        10: ['october', 'octubre'],
        11: ['november', 'noviembre'],
        12: ['december', 'diciembre'],
    }

    def __init__(self, name=None, format='%Y-%m-%d'):
        super().__init__(regex=None, name=name)
        self.format = format

        self._month_map = {}
        for source in (self.DEFAULT_MONTH_ABBR, self.DEFAULT_MONTH_FULL):
            for num, names in source.items():
                for n in names:
                    self._month_map[n.lower()] = num

        def build_regex(months):
            return '(?i:' + '|'.join(
                re.escape(n)
                for names in months.values()
                for n in names
            ) + ')'

        self._abbr_month_regex = build_regex(self.DEFAULT_MONTH_ABBR)
        self._full_month_regex = build_regex(self.DEFAULT_MONTH_FULL)

    @property
    def regex(self):
        regex = self.format
        regex = regex.replace('%Y', self.new_group(r'\d{4}', 'year'))
        regex = regex.replace('%m', self.new_group(r'\d{1,2}', 'month'))
        regex = regex.replace('%d', self.new_group(r'\d{1,2}', 'day'))
        regex = regex.replace('%b', self.new_group(
            self._abbr_month_regex, 'month'))
        regex = regex.replace('%B', self.new_group(
            self._full_month_regex, 'month'))
        return regex

    def decode(self, match, to_dict=False):
        year = int(match.group(self.get_id('year')))
        day = int(match.group(self.get_id('day')))
        month_raw = match.group(self.get_id('month'))

        month = int(month_raw) if month_raw.isdigit() \
            else self._month_map[month_raw.lower()]

        value = f'{year:04d}-{month:02d}-{day:02d}'
        return {self.name: value} if to_dict else value

    def __repr__(self):
        return f"Date({self.__str__()})"
