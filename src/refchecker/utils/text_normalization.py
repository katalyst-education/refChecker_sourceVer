"""Shared normalization of common text-layer typography."""

import re
import unicodedata


_LIGATURES = str.maketrans({
    '\ufb00': 'ff', '\ufb01': 'fi', '\ufb02': 'fl', '\ufb03': 'ffi',
    '\ufb04': 'ffl', '\ufb05': 'st', '\ufb06': 'st',
})
_SOFT_HYPHEN_BREAK = re.compile(r'(?<=\w)\u00ad\s*(?=\w)')
_LETTER = r'[^\W\d_]'
_WRAPPED_WORD = re.compile(
    rf'(?<!\w)(?P<left>{_LETTER}+)(?P<hyphen>[-\u2010])[^\S\r\n]*\r?\n[^\S\r\n]*'
    rf'(?=(?P<right>{_LETTER}+)(?!\w))'
)
_FLATTENED_WRAP = re.compile(rf'(?<!\w)({_LETTER}+)[-\u2010]\s*(?=({_LETTER}+)(?!\w))')
_UNBROKEN_WORD = re.compile(rf'{_LETTER}+(?:[-\u2010\u2011]{_LETTER}+)*')
_HYPHEN_FORMS = str.maketrans({'\u2010': '-', '\u2011': '-'})
_INITIAL_PERIOD = re.compile(rf'(?<!\w)({_LETTER})\s*\.')
_INITIAL_HYPHEN = re.compile(rf'(?<!\w)({_LETTER}\.)\s*([-\u2010\u2011])\s*(?=({_LETTER})\.)')
_INITIAL_GAP = re.compile(rf'(?<!\w)({_LETTER}\.)\s*(?={_LETTER})')


def normalize_pdf_typography(text: str) -> str:
    """Expand presentation ligatures and remove discretionary soft hyphens."""
    text = _SOFT_HYPHEN_BREAK.sub('', text).replace('\u00ad', '')
    return unicodedata.normalize('NFC', text.translate(_LIGATURES))


def wrapped_word_parts(text: str):
    """Return letter fragments on either side of marked line breaks."""
    for match in _WRAPPED_WORD.finditer(normalize_pdf_typography(text)):
        yield match['left'], match['right']


def normalize_wrapped_hyphens(text: str, join=None) -> str:
    """Unwrap word boundaries, keeping hard hyphens unless the join is supported."""
    def replace(match):
        if join and join(match['left'], match['right']):
            return match['left']
        return match['left'] + match['hyphen']

    return _WRAPPED_WORD.sub(replace, normalize_pdf_typography(text))


def unbroken_words(text: str) -> set[str]:
    """Collect spellings that occur intact in a source document."""
    normalized = normalize_pdf_typography(text).casefold().translate(_HYPHEN_FORMS)
    return set(_UNBROKEN_WORD.findall(normalized))


def align_supported_wraps(
    text: str, unhyphenated: set[tuple[str, str]], hyphenated: set[tuple[str, str]],
) -> str:
    """Apply the intact spelling at an observed wrap boundary."""
    def replace(match):
        pair = match[1].casefold(), match[2].casefold()
        return match[1] if pair in unhyphenated else match[0]

    text = _FLATTENED_WRAP.sub(replace, text)
    for left, right in sorted(hyphenated):
        text = re.sub(
            rf'(?<![\w-])({re.escape(left)})({re.escape(right)})(?![\w-])',
            r'\1-\2', text, flags=re.IGNORECASE,
        )
    return text


def normalize_initial_spacing(name: str) -> str:
    """Restore gaps around punctuated initials without splitting hyphenated initials."""
    name = _INITIAL_PERIOD.sub(lambda match: match[1] + '.' if match[1].isupper() else match[0], name)
    name = _INITIAL_HYPHEN.sub(
        lambda match: match[1] + match[2] if match[1][0].isupper() and match[3].isupper() else match[0],
        name,
    )
    return _INITIAL_GAP.sub(lambda match: match[1] + ' ' if match[1][0].isupper() else match[0], name)
