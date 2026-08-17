"""Regression tests for authoritative DOI lookup in the local checker."""

import json
import sqlite3

from refchecker.checkers.local_semantic_scholar import LocalNonArxivReferenceChecker


def _create_database(path):
    connection = sqlite3.connect(path)
    connection.execute(
        """
        CREATE TABLE papers (
            paperId TEXT PRIMARY KEY,
            title TEXT,
            normalized_paper_title TEXT,
            year INTEGER,
            authors TEXT,
            venue TEXT,
            externalIds_DOI TEXT,
            externalIds_ArXiv TEXT
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE metadata (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    connection.execute(
        "CREATE INDEX idx_papers_normalized_title ON papers(normalized_paper_title)"
    )
    connection.execute(
        "CREATE INDEX idx_papers_doi ON papers(externalIds_DOI)"
    )

    title = "A paper with both preprint and proceedings records"
    normalized_title = "apaperwithbothpreprintandproceedingsrecords"
    authors = json.dumps([{"name": "Ada Author"}])
    rows = [
        (
            "arxiv-record",
            title,
            normalized_title,
            2024,
            authors,
            "arXiv",
            "10.48550/arXiv.2410.13298",
            "2410.13298",
        ),
        (
            "proceedings-record",
            title,
            normalized_title,
            2024,
            authors,
            "EMNLP",
            "10.18653/v1/2024.emnlp-main.223",
            "2410.13298",
        ),
    ]
    connection.executemany(
        "INSERT INTO papers VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    connection.commit()
    connection.close()
    return title


def test_explicit_doi_is_looked_up_before_same_title_arxiv_record(tmp_path):
    db_path = tmp_path / "papers.db"
    title = _create_database(db_path)
    checker = LocalNonArxivReferenceChecker(db_path=str(db_path))

    try:
        verified_data, errors, _ = checker.verify_reference(
            {
                "title": title,
                "authors": ["Ada Author"],
                "year": 2024,
                "venue": "EMNLP",
                "doi": "10.18653/v1/2024.emnlp-main.223",
            }
        )
    finally:
        checker.close()

    assert verified_data["paperId"] == "proceedings-record"
    assert verified_data["externalIds"]["DOI"] == "10.18653/v1/2024.emnlp-main.223"
    assert not any(
        issue.get("error_type") == "doi" or issue.get("warning_type") == "doi"
        for issue in errors
    )
