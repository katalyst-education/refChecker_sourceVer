import re
import unicodedata


def fix_misordered_diacritics(text: str) -> str:
    """
    Fix PDF extraction cases where accents/umlauts appear before the letter.

    Examples:
        ¨Ubung               -> Übung
        ¨ Aquivalenzrelation -> Äquivalenzrelation
        ¨ uber               -> über
    """
    if not text:
        return ""

    text = re.sub(r"([¨\u0308])\s+([AEOUaeou])", r"\1\2", text)

    replacements = {
        "¨A": "Ä",
        "¨O": "Ö",
        "¨U": "Ü",
        "¨a": "ä",
        "¨o": "ö",
        "¨u": "ü",
        "\u0308A": "Ä",
        "\u0308O": "Ö",
        "\u0308U": "Ü",
        "\u0308a": "ä",
        "\u0308o": "ö",
        "\u0308u": "ü",
    }

    for broken, fixed in replacements.items():
        text = text.replace(broken, fixed)

    return unicodedata.normalize("NFC", text)


def normalize_unicode_basic(text: str) -> str:
    if not text:
        return ""

    text = fix_misordered_diacritics(text)
    text = unicodedata.normalize("NFKC", text)
    text = unicodedata.normalize("NFC", text)

    return (
        text.replace("’", "'")
            .replace("‘", "'")
            .replace("“", '"')
            .replace("”", '"')
            .replace("„", '"')
            .replace("–", "-")
            .replace("—", "-")
            .replace("−", "-")
            .replace("\u00a0", " ")
            .replace("\xad", "")
    )


def normalize_for_repetition(text: str, cleaner) -> str:
    """
    Generic repeated-text normalization.
    Pass the extractor-specific cleaner as `cleaner`.
    """
    text = cleaner(text).lower()

    text = re.sub(r"\b\d+\b", "<num>", text)
    text = re.sub(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b", "<date>", text)
    text = re.sub(r"\b\d{4}-\d{2}-\d{2}\b", "<date>", text)

    text = re.sub(r"[^a-z0-9<> ]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    return text

def join_spans_with_position_spacing(spans: list[dict], cleaner) -> str:
    """
    Join PyMuPDF spans using x-coordinates.

    This prevents artifacts where separate visual words are returned
    without a normal space.

    Pass an extractor-specific cleaner, for example:
        join_spans_with_position_spacing(spans, paper_clean_text)
    """
    parts = []
    previous_x1 = None
    previous_font_size = None

    for span in spans:
        raw_text = span.get("text", "")
        text = cleaner(raw_text)

        if not text:
            continue

        x0, _, x1, _ = span.get("bbox", [0, 0, 0, 0])
        font_size = float(span.get("size", 0)) or previous_font_size or 10

        if parts and previous_x1 is not None:
            gap = float(x0) - float(previous_x1)
            space_threshold = font_size * 0.20

            if gap > space_threshold:
                parts.append(" ")

        parts.append(text)

        previous_x1 = float(x1)
        previous_font_size = font_size

    return cleaner("".join(parts))