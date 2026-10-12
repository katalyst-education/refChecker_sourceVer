from pathlib import Path
from statistics import mean, median

from pdfminer.high_level import extract_pages
from pdfminer.layout import LTTextLineHorizontal


TEST_FOLDER = Path("test_pdf")
OUTPUT_FILE = Path("pdf_classification_results.txt")


ACADEMIC_MARKERS = [
    "abstract",
    "keywords",
    "introduction",
    "method",
    "methodology",
    "results",
    "discussion",
    "conclusion",
    "references",
    "bibliography",
    "doi",
]


def iter_text_lines(layout_obj):
    """ Recursively walk through pdfminer layout objects and yield only text lines. 

    pdfminer returns a flat list a page contains nested objects 
    such as text boxes, text lines, characters, images, figures, etc.

    This function searches through that nested structure and returns only LTTextLineHorizontal 
    objects, which represent horizontal text lines. """
    if isinstance(layout_obj, LTTextLineHorizontal):
        yield layout_obj

    if hasattr(layout_obj, "__iter__"):
        for child in layout_obj:
            yield from iter_text_lines(child)


def get_pdfminer_pages(pdf_path, max_pages=10):
    """ Extract page-level layout information from a PDF. For each page, this function collects: 
    - page width 
    - page height 
    - page orientation 
    - useful text lines 
    - each text line's word count 
    - each text line's relative width 
    - each text line's horizontal center position 
    Only the first max_pages pages are checked to keep processing fast. """
    pages = []

    for page_index, page_layout in enumerate(extract_pages(str(pdf_path))):
        if page_index >= max_pages:
            break

        page_width = float(page_layout.width)
        page_height = float(page_layout.height)

        lines = []

        for line in iter_text_lines(page_layout):
            text = line.get_text().strip()

            if not text:
                continue

            word_count = len(text.split())

            if word_count < 3:
                continue

            # Get the bounding box of the text line. 
            # 
            # x0 = left edge 
            # y0 = bottom edge 
            # x1 = right edge 
            # y1 = top edge
            x0 = float(line.x0)
            y0 = float(line.y0)
            x1 = float(line.x1)
            y1 = float(line.y1)

            # Ignore headers and footers.
            if y1 > page_height * 0.94:
                continue
            if y0 < page_height * 0.06:
                continue

            # How wide is the line compared with the full page width?
            width_ratio = (x1 - x0) / page_width
            # Where is the center of the line horizontally?
            center_ratio = ((x0 + x1) / 2) / page_width

            lines.append({
                "text": text,
                "word_count": word_count,
                "width_ratio": width_ratio,
                "center_ratio": center_ratio,
            })

        pages.append({
            "page_number": page_index + 1,
            "width": page_width,
            "height": page_height,
            "orientation": "landscape" if page_width > page_height else "portrait",
            "lines": lines,
        })

    return pages


def classify_page_columns(page):
    """ Decide whether a single page looks like one-column or two-column layout. 
    The function looks at text-line widths and horizontal positions. 
    
    A two-column page usually has: 
    - many medium-width lines 
    - some lines centered on the left side 
    - some lines centered on the right side 
    - not too many full-width lines """
    lines = page["lines"]

    body_lines = []

    for line in lines:
        width_ratio = line["width_ratio"]

        if line["word_count"] < 4:
            continue

        if width_ratio < 0.10:
            continue

        body_lines.append(line)

    # If there are too few usable lines, there is not enough evidence 
    # to safely detect two columns. Default to one-column.
    if len(body_lines) < 8:
        return {
            "columns": 1,
            "line_count": len(body_lines),
            "median_width": 1.0,
            "left_ratio": 0.0,
            "right_ratio": 0.0,
            "long_ratio": 1.0,
            "short_ratio": 0.0,
        }

    widths = [line["width_ratio"] for line in body_lines]
    # Median is used instead of average because it is less affected by 
    # occasional very long title lines or very short fragments.
    median_width = median(widths)

    long_lines = [
        line for line in body_lines
        if line["width_ratio"] >= 0.58
    ]

    short_lines = [
        line for line in body_lines
        if 0.16 <= line["width_ratio"] <= 0.56
    ]

    left_lines = [
        line for line in short_lines
        if 0.05 <= line["center_ratio"] <= 0.47
    ]

    right_lines = [
        line for line in short_lines
        if 0.53 <= line["center_ratio"] <= 0.95
    ]

    total = len(body_lines)

    long_ratio = len(long_lines) / total
    short_ratio = len(short_lines) / total
    left_ratio = len(left_lines) / total
    right_ratio = len(right_lines) / total

    # This is the actual rule for deciding whether the page looks two-column. 
    # 
    # It requires: 
    # - the median line should not be too wide 
    # - enough lines should be column-sized 
    # - there should be evidence of text on both the left and right sides 
    # - the page should not be dominated by full-width lines
    two_column_signal = (
        median_width <= 0.60
        and short_ratio >= 0.38
        and left_ratio >= 0.10
        and right_ratio >= 0.10
        and long_ratio <= 0.65
    )

    return {
        "columns": 2 if two_column_signal else 1,
        "line_count": total,
        "median_width": round(median_width, 3),
        "left_ratio": round(left_ratio, 3),
        "right_ratio": round(right_ratio, 3),
        "long_ratio": round(long_ratio, 3),
        "short_ratio": round(short_ratio, 3),
    }


def classify_pdf(pdf_path, max_pages=10):
    """ Classify a single PDF as one of: 
    - presentation_slide 
    - two_column_paper 
    - one_column_paper 
    - unknown 
    
    The decision is based on: 
    - page orientation 
    - average words per page 
    - academic marker words 
    - how many pages look like two-column layout 
    - average line-width and column-position features """
    pages = get_pdfminer_pages(pdf_path, max_pages=max_pages)

    if not pages:
        return {
            "type": "unknown",
            "confidence": "low",
            "reason": "No readable pages",
        }

    pages_to_check = len(pages)

    all_text_parts = []
    orientations = []
    word_counts = []
    page_debug = []
    page_column_details = []

    for page in pages:
        lines = page["lines"]
        text = "\n".join(line["text"] for line in lines)

        all_text_parts.append(text)
        orientations.append(page["orientation"])
        word_counts.append(len(text.split()))

        page_result = classify_page_columns(page)
        page_result["page"] = page["page_number"]

        page_debug.append(page_result)
        page_column_details.append(page_result["columns"])

    classifier_probe_text = "\n".join(all_text_parts).lower()
    # High values suggest presentation slides
    landscape_ratio = orientations.count("landscape") / pages_to_check
    avg_words = sum(word_counts) / pages_to_check

    academic_markers = sum(
        1 for marker in ACADEMIC_MARKERS
        if marker in classifier_probe_text
    )

    two_col_pages = page_column_details.count(2)
    two_col_ratio = two_col_pages / pages_to_check

    avg_median_width = mean(item["median_width"] for item in page_debug)
    avg_left_ratio = mean(item["left_ratio"] for item in page_debug)
    avg_right_ratio = mean(item["right_ratio"] for item in page_debug)
    avg_long_ratio = mean(item["long_ratio"] for item in page_debug)
    avg_short_ratio = mean(item["short_ratio"] for item in page_debug)

    features = {
        "pages_checked": pages_to_check,
        "landscape_ratio": round(landscape_ratio, 2),
        "avg_words": round(avg_words, 1),
        "academic_markers": academic_markers,
        "two_col_ratio": round(two_col_ratio, 2),
        "two_col_pages": two_col_pages,
        "avg_median_line_width": round(avg_median_width, 3),
        "avg_left_ratio": round(avg_left_ratio, 3),
        "avg_right_ratio": round(avg_right_ratio, 3),
        "avg_long_ratio": round(avg_long_ratio, 3),
        "avg_short_ratio": round(avg_short_ratio, 3),
        "page_column_details": page_column_details,
        "page_debug": page_debug,
    }
    # First classification rule: 
    # If most checked pages are landscape, classify as presentation slides.
    if landscape_ratio >= 0.6:
        return {
            "type": "presentation_slide",
            "confidence": "high",
            "features": features,
        }
    # Second classification rule: 
    # Classify as a two-column paper if either: 
    # 
    # 1. At least 30% of checked pages individually look two-column.
    # OR # 
    # 2. The document as a whole has academic and two-column-like signals: 
    # - enough words per page 
    # - enough academic marker words 
    # - many short column-sized lines 
    # - evidence of text on both left and right sides 
    # - not too many full-width lines
    if (
        two_col_ratio >= 0.30
        or (
            avg_words >= 350
            and academic_markers >= 3
            and avg_short_ratio >= 0.38
            and avg_left_ratio >= 0.10
            and avg_right_ratio >= 0.10
            and avg_long_ratio <= 0.65
        )
    ):
        return {
            "type": "two_column_paper",
            "confidence": "high" if two_col_ratio >= 0.50 else "medium",
            "features": features,
        }
    # Final fallback: 
    # If it is not slides and not two-column, assume one-column paper.
    return {
        "type": "one_column_paper",
        "confidence": "medium",
        "features": features,
    }


