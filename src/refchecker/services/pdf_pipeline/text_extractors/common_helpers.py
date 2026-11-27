import re
import unicodedata


def identifier_line_continues(text: str, previous_continues: bool = False) -> bool:
    text = text.strip()
    return bool(
        re.search(r"(?:https?://|10\.\d{4,9}/)\S*[/+_=.\-]$", text, re.IGNORECASE)
        or (previous_continues and re.fullmatch(r"\S+[/+_=.\-]", text))
    )


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


def merge_drawn_identifier_fragments(lines: list[dict], page) -> list[dict]:
    """Rejoin same-baseline URL fragments separated by drawn underscores."""
    def text(line):
        return "".join(
            span.get("text", "".join(char.get("c", "") for char in span.get("chars", [])))
            for span in line.get("spans", [])
        )

    merged = []
    drawings = None
    for line in lines:
        if len(merged) < 2:
            merged.append(line)
            continue
        previous, left = merged[-2:]
        left_spans, right_spans = left.get("spans", []), line.get("spans", [])
        preceding = text(previous)
        if (
            not left_spans or not right_spans
            or not re.search(r"(?:https?://|10\.\d{4,9}/)\S*[/+_=.\-]\s*$", preceding, re.I)
            or not re.search(r"\w$", text(left))
            or not re.match(r"\w", text(line))
        ):
            merged.append(line)
            continue
        a, b = left_spans[-1], right_spans[0]
        size = float(a.get("size", 0))
        origin_a, origin_b = a.get("origin"), b.get("origin")
        x0, x1 = a["bbox"][2], b["bbox"][0]
        if (
            not size or not origin_a or not origin_b
            or abs(origin_a[1] - origin_b[1]) > size * 0.02
            or not size * 0.25 <= x1 - x0 <= size * 3.2
        ):
            merged.append(line)
            continue
        if drawings is None:
            drawings = page.get_drawings()
        strokes = []
        for drawing in drawings:
            items = drawing.get("items", [])
            if drawing.get("type") != "s" or len(items) != 1 or items[0][0] != "l":
                continue
            _, start, end = items[0]
            if (
                x0 - size * 0.03 <= start.x < end.x <= x1 + size * 0.03
                and size * 0.25 <= end.x - start.x <= size * 0.8
                and abs(start.y - end.y) <= size * 0.02
                and 0 <= start.y - origin_a[1] <= size * 0.2
                and float(drawing.get("width", 0)) <= size * 0.15
            ):
                strokes.append((start.x, end.x))
        strokes.sort()
        cursor = x0
        contiguous = True
        for start, end in strokes:
            if abs(start - cursor) > size * 0.03:
                contiguous = False
                break
            cursor = end
        if not strokes or not contiguous or abs(cursor - x1) > size * 0.03:
            merged.append(line)
            continue
        inserted = []
        for start, end in strokes:
            bbox = (start, a["bbox"][1], end, a["bbox"][3])
            span = dict(a, bbox=bbox, origin=(start, origin_a[1]))
            if "text" in span:
                span["text"] = "_"
            else:
                span["chars"] = [{"c": "_", "bbox": bbox}]
            inserted.append(span)
        joined = dict(left)
        joined["spans"] = left_spans + inserted + right_spans
        joined["bbox"] = (
            min(left["bbox"][0], line["bbox"][0]),
            min(left["bbox"][1], line["bbox"][1]),
            max(left["bbox"][2], line["bbox"][2]),
            max(left["bbox"][3], line["bbox"][3]),
        )
        joined["_source_text"] = left.get("_source_text", text(left)) + "\n" + text(line)
        merged[-1] = joined
    return merged


def restore_drawn_identifier_underscores(
    spans: list[dict], drawings: list[dict], *, continuation: bool = False,
) -> list[dict]:
    """Recover underscore strokes occupying a text-extractor space in a URL or DOI."""
    def span_text(span):
        if "text" in span:
            return span["text"]
        return "".join(char.get("c", "") for char in span.get("chars", []))

    text = "".join(span_text(span) for span in spans)
    if not continuation and not re.search(r"https?://|10\.\d{4,9}/", text, re.IGNORECASE):
        return spans

    result = list(spans)
    for index in range(1, len(spans) - 1):
        span = spans[index]
        if span_text(span) != " ":
            continue
        left, right = span_text(spans[index - 1]), span_text(spans[index + 1])
        if not left or not right or not re.match(r"[\w/.\-]", left[-1]) or not re.match(r"[\w/.\-]", right[0]):
            continue
        x0, _, x1, _ = span["bbox"]
        size = float(span.get("size", 0))
        origin = span.get("origin")
        if not origin or not size or not 0.25 * size <= x1 - x0 <= 0.8 * size:
            continue
        baseline = origin[1]
        for drawing in drawings:
            items = drawing.get("items", [])
            if drawing.get("type") != "s" or len(items) != 1 or items[0][0] != "l":
                continue
            _, start, end = items[0]
            if (
                abs(start.x - x0) <= size * 0.03
                and abs(end.x - x1) <= size * 0.03
                and abs(start.y - end.y) <= size * 0.02
                and 0 <= start.y - baseline <= size * 0.2
                and float(drawing.get("width", 0)) <= size * 0.15
            ):
                fixed = dict(span)
                if "text" in fixed:
                    fixed["text"] = "_"
                else:
                    chars = fixed.get("chars", [])
                    if len(chars) != 1 or chars[0].get("c") != " ":
                        break
                    fixed["chars"] = [dict(chars[0], c="_")]
                result[index] = fixed
                break
    return result


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
    previous_raw_text = ""
    whitespace_span = False

    for span in spans:
        raw_text = span.get("text", "")
        text = cleaner(raw_text)

        if not text:
            if raw_text and raw_text.isspace():
                whitespace_span = True
            continue

        x0, _, x1, _ = span.get("bbox", [0, 0, 0, 0])
        font_size = float(span.get("size", 0)) or previous_font_size or 10

        if parts and previous_x1 is not None:
            gap = float(x0) - float(previous_x1)
            space_threshold = font_size * 0.08
            boundary_has_space = (
                whitespace_span or previous_raw_text[-1:].isspace() or raw_text[:1].isspace()
            )
            left_text = "".join(parts)
            inside_url = re.search(r"(?:https?://|10\.\d{4,9}/)\S*$", left_text, re.I)
            word_boundary = (
                parts[-1][-1:].isalnum() and text[:1].isalnum()
            )

            if boundary_has_space or (
                gap > space_threshold and word_boundary and not inside_url
            ):
                parts.append(" ")

        parts.append(text)

        previous_x1 = float(x1)
        previous_font_size = font_size
        previous_raw_text = raw_text
        whitespace_span = False

    return cleaner("".join(parts))