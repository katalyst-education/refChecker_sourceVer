#!/usr/bin/env python3
"""Run the exact Semantic Scholar request flow used by RefChecker for one reference."""

import argparse
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add src/ for direct script execution from repository root.
sys.path.insert(0, str((Path(__file__).resolve().parent.parent / "src")))

from refchecker.checkers.semantic_scholar import (  # noqa: E402
    SIMILARITY_THRESHOLD,
    S2_PAPER_FIELDS,
    NonArxivReferenceChecker,
)
from refchecker.utils.text_utils import (  # noqa: E402
    calculate_title_similarity,
    clean_title_for_search,
    find_best_match,
    normalize_text,
)

AUTHOR_FALLBACK_SCORE_THRESHOLD = 0.5


def _title_similarity(cited_title: str, candidate_title: str) -> float:
    cited = normalize_text(cited_title or "").lower().strip()
    found = normalize_text(candidate_title or "").lower().strip()
    if not cited or not found:
        return 0.0
    return calculate_title_similarity(cited, found)


def _print_candidate_table(stage: str, cited_title: str, results: List[Dict[str, Any]]) -> None:
    print(f"\n[{stage}] result_count={len(results)}")
    if not results:
        print("  none")
        return
    for i, result in enumerate(results, start=1):
        external_ids = result.get("externalIds") or {}
        title = result.get("title") or ""
        score = _title_similarity(cited_title, title)
        print(
            f"  {i:>2}. score={score:.3f} year={result.get('year')} "
            f"paperId={result.get('paperId')} doi={external_ids.get('DOI')} title={title}"
        )


def _print_endpoint_status(
    checker: NonArxivReferenceChecker,
    cleaned_title: str,
    body_chars: int,
) -> None:
    match_url = f"{checker.base_url}/paper/search/match"
    search_url = f"{checker.base_url}/paper/search"

    endpoint_calls = [
        (
            "search/match",
            match_url,
            {"query": cleaned_title, "fields": S2_PAPER_FIELDS},
        ),
        (
            "search",
            search_url,
            {"query": cleaned_title, "limit": 10, "fields": S2_PAPER_FIELDS, "sort": "relevance"},
        ),
    ]

    print("\n[endpoint_status]")
    for name, url, params in endpoint_calls:
        response = checker._session.get(url, params=params, timeout=30)
        body = (response.text or "").replace("\n", " ")
        print(f"  {name}: status={response.status_code}")
        print(f"  {name}: params={params}")
        print(f"  {name}: body={body[:body_chars]}")


def _author_fallback_query(authors: List[str], cleaned_title: str) -> Optional[str]:
    if not authors:
        return None
    first_author = (authors[0] or "").strip()
    if len(first_author) <= 3 or first_author.lower() in ("et al", "et al.", "others"):
        return None
    title_words = [word for word in cleaned_title.split() if len(word) > 3][:4]
    return f"{first_author} {' '.join(title_words)}".strip()


def _print_relevance_decision(
    stage: str,
    results: List[Dict[str, Any]],
    cleaned_title: str,
    year: int,
    authors: List[str],
) -> None:
    if not results:
        print(f"[{stage}] best_match=none accepted=False")
        return
    best_match, best_score = find_best_match(results, cleaned_title, year, authors)
    best_title = (best_match or {}).get("title", "")
    accepted = bool(best_match and best_score >= SIMILARITY_THRESHOLD)
    print(
        f"[{stage}] best_score={best_score:.3f} threshold={SIMILARITY_THRESHOLD:.3f} "
        f"accepted={accepted} best_title={best_title!r}"
    )


def _print_author_fallback_decision(
    results: List[Dict[str, Any]],
    cleaned_title: str,
    year: int,
    authors: List[str],
) -> None:
    if not results:
        print("[author_fallback_best] best_match=none accepted=False")
        return

    best_match, best_score = find_best_match(results, cleaned_title, year, authors)
    best_title = (best_match or {}).get("title", "")
    title_similarity = _title_similarity(cleaned_title, best_title)
    matched_year = (best_match or {}).get("year")
    year_match_ok = True
    if best_match and year and matched_year:
        try:
            year_match_ok = abs(int(matched_year) - int(year)) <= 1
        except (TypeError, ValueError):
            year_match_ok = True

    accepted = bool(best_match and best_score >= AUTHOR_FALLBACK_SCORE_THRESHOLD)
    print(
        "[author_fallback_best] "
        f"best_score={best_score:.3f} score_threshold={AUTHOR_FALLBACK_SCORE_THRESHOLD:.3f} "
        f"title_similarity={title_similarity:.3f} "
        f"cited_year={year} matched_year={matched_year} year_match_ok={year_match_ok} "
        f"accepted={accepted} best_title={best_title!r}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Debug Semantic Scholar request/selection for one reference."
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("SEMANTIC_SCHOLAR_API_KEY", ""),
        help="Semantic Scholar API key (defaults to SEMANTIC_SCHOLAR_API_KEY).",
    )
    parser.add_argument(
        "--title",
        default="Guidelines for performing Systematic Literature Reviews in software engineering",
        help="Reference title.",
    )
    parser.add_argument(
        "--author",
        action="append",
        default=None,
        help="Author name (repeat --author for more).",
    )
    parser.add_argument("--year", type=int, default=2007, help="Reference year.")
    parser.add_argument(
        "--raw-text",
        default=(
            "Kitchenham, B.: Guidelines for performing Systematic Literature Reviews in software engineering. "
            "EBSE Technical Report EBSE-2007-01, 2007"
        ),
        help="Raw citation text used by the raw-text fallback search.",
    )
    parser.add_argument(
        "--body-chars",
        type=int,
        default=220,
        help="How many response body characters to print for endpoint status checks.",
    )
    parser.add_argument(
        "--skip-endpoint-status",
        action="store_true",
        help="Skip direct HTTP status/body printing and only use checker methods.",
    )
    args = parser.parse_args()

    checker = NonArxivReferenceChecker(api_key=args.api_key or None)
    checker.cache_dir = None

    title = args.title.strip()
    parsed_authors = args.author if args.author is not None else ["Barbara Kitchenham"]
    authors = [a.strip() for a in parsed_authors if (a or "").strip()]
    cleaned_title = clean_title_for_search(title)
    stripped_title = checker._strip_leading_author_like_prefix(cleaned_title)
    author_query = _author_fallback_query(authors, stripped_title)

    print("=== semantic scholar debug request ===")
    print(f"api_key_set={bool(args.api_key)}")
    print(f"title={title!r}")
    print(f"authors={authors}")
    print(f"year={args.year}")
    print(f"cleaned_title={cleaned_title!r}")
    print(f"stripped_title={stripped_title!r}")
    print(f"author_query={author_query!r}")
    print(f"similarity_threshold={SIMILARITY_THRESHOLD:.3f}")
    print(f"author_fallback_score_threshold={AUTHOR_FALLBACK_SCORE_THRESHOLD:.3f}")
    print(f"s2_fields={S2_PAPER_FIELDS}")

    if not args.skip_endpoint_status:
        _print_endpoint_status(checker, stripped_title, args.body_chars)

    match_result = checker.match_paper_by_title(stripped_title)
    match_results = [match_result] if match_result else []
    _print_candidate_table("title_match_endpoint", stripped_title, match_results)
    if match_result:
        match_title = match_result.get("title", "")
        match_score = _title_similarity(stripped_title, match_title)
        accepted = match_score >= SIMILARITY_THRESHOLD
        print(
            "[title_match_score] "
            f"score={match_score:.3f} threshold={SIMILARITY_THRESHOLD:.3f} "
            f"accepted={accepted} matched_title={match_title!r}"
        )

    title_results = checker.search_paper(stripped_title, args.year)
    _print_candidate_table("title_relevance_search", stripped_title, title_results)
    _print_relevance_decision("title_relevance_best", title_results, stripped_title, args.year, authors)

    if author_query:
        author_results = checker.search_paper(author_query, args.year)
        _print_candidate_table("author_fallback_search", stripped_title, author_results)
        _print_author_fallback_decision(author_results, stripped_title, args.year, authors)
    else:
        print("\n[author_fallback_search] skipped (no valid first author)")

    raw_query = (args.raw_text or "").replace("\n", " ").strip()
    if raw_query:
        raw_query = normalize_text(raw_query[:300]).lower().strip()
    raw_results = checker.search_paper(raw_query, args.year) if raw_query else []
    _print_candidate_table("raw_text_search", stripped_title, raw_results)
    _print_relevance_decision("raw_text_best", raw_results, stripped_title, args.year, authors)

    reference = {
        "title": title,
        "authors": authors,
        "year": args.year,
        "url": "",
        "raw_text": args.raw_text,
    }
    verified_data, errors, verified_url = checker.verify_reference(reference)
    print("\n[verify_reference]")
    print(f"verified_data_found={bool(verified_data)}")
    if verified_data:
        print(f"verified_title={verified_data.get('title')!r}")
        print(f"verified_year={verified_data.get('year')!r}")
        print(f"verified_paperId={verified_data.get('paperId')!r}")
    print(f"errors={errors}")
    print(f"url={verified_url!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
