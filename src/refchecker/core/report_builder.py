"""Structured report building for reference-checker results."""

from __future__ import annotations

import csv
import datetime
import json
import logging
from typing import Any, Dict, IO, List, Optional

from refchecker.utils.text_utils import display_reference_value

logger = logging.getLogger(__name__)


class ReportBuilder:
    """Build and write structured reports from reference-checker issue entries."""

    def __init__(self, report_file: Optional[str] = None, report_format: str = "json"):
        self.report_file = report_file
        self.report_format = report_format

    def build_structured_report_records(self, errors: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [dict(error_entry) for error_entry in errors]

    def build_paper_rollups(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        rollups: Dict[str, Dict[str, Any]] = {}
        for record in records:
            key = record.get("source_paper_id") or record.get("source_url") or record.get("source_title")
            if not key:
                continue
            rollup = rollups.setdefault(key, {
                "source_paper_id": record.get("source_paper_id", ""),
                "source_title": record.get("source_title", ""),
                "source_authors": record.get("source_authors", ""),
                "source_year": record.get("source_year"),
                "source_url": record.get("source_url", ""),
                "total_records": 0,
                "error_type_counts": {},
            })
            rollup["total_records"] += 1
            error_type = record.get("error_type") or "unknown"
            counts = rollup["error_type_counts"]
            counts[error_type] = counts.get(error_type, 0) + 1

        result = list(rollups.values())
        for rollup in result:
            rollup["error_type_counts"] = dict(sorted(
                rollup["error_type_counts"].items(),
                key=lambda item: (-item[1], item[0]),
            ))
        result.sort(key=lambda item: (-item["total_records"], item["source_title"] or ""))
        return result

    def build_structured_report_payload(
        self,
        errors: List[Dict[str, Any]],
        stats: Dict[str, Any],
    ) -> Dict[str, Any]:
        records = self.build_structured_report_records(errors)
        paper_rollups = self.build_paper_rollups(records)
        summary = {
            "total_papers_processed": stats.get("total_papers_processed", 0),
            "total_references_processed": stats.get("total_references_processed", 0),
            "total_errors_found": stats.get("total_errors_found", 0),
            "total_warnings_found": stats.get("total_warnings_found", 0),
            "total_info_found": stats.get("total_info_found", 0),
            "total_unverified_refs": stats.get("total_unverified_refs", 0),
            "records_written": len(records),
            "papers_with_records": len(paper_rollups),
        }
        return {"summary": summary, "papers": paper_rollups, "records": records}

    def write_structured_report(self, payload: Dict[str, Any]) -> None:
        if not self.report_file:
            return
        try:
            with open(self.report_file, "w", encoding="utf-8", errors="replace") as handle:
                self._write_to_handle(
                    handle,
                    payload["records"],
                    payload["papers"],
                    payload["summary"],
                )
        except Exception as exc:
            logger.error("Failed to write structured report: %s", exc)

    def _write_to_handle(
        self,
        handle: IO,
        records: List[Dict[str, Any]],
        paper_rollups: List[Dict[str, Any]],
        summary: Dict[str, Any],
    ) -> None:
        if self.report_format == "csv":
            self._write_csv(handle, records)
        elif self.report_format == "jsonl":
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        elif self.report_format == "json":
            json.dump({
                "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "summary": summary,
                "papers": paper_rollups,
                "records": records,
            }, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        else:
            self._write_text(handle, records, summary)

    @staticmethod
    def _write_csv(handle: IO, records: List[Dict[str, Any]]) -> None:
        fieldnames = [
            "source_paper_id", "source_title", "source_authors", "source_year", "source_url",
            "ref_paper_id", "ref_title", "ref_authors_cited", "ref_year_cited", "ref_url_cited",
            "error_type", "error_details", "ref_verified_url", "ref_title_correct",
            "ref_authors_correct", "ref_year_correct", "ref_url_correct", "ref_venue_correct",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)

    @staticmethod
    def _write_text(handle: IO, records: List[Dict[str, Any]], summary: Dict[str, Any]) -> None:
        handle.write("REFERENCE CHECK REPORT\n")
        handle.write("=" * 70 + "\n")
        handle.write(f'References processed: {summary.get("total_references_processed", 0)}\n')
        for label, key in (
            ("Errors", "total_errors_found"),
            ("Warnings", "total_warnings_found"),
            ("Unverified", "total_unverified_refs"),
        ):
            value = summary.get(key, 0)
            if value:
                handle.write(f"{label + ':':<22}{value}\n")
        handle.write("=" * 70 + "\n\n")
        if not records:
            handle.write("No issues found.\n")
            return

        for index, record in enumerate(records, 1):
            handle.write(f'[{index}] {record.get("ref_title", "?")}\n')
            authors = record.get("ref_authors_cited", "")
            year = display_reference_value(record.get("ref_year_cited", ""))
            if authors:
                handle.write(f"    Authors: {authors}\n")
            if year:
                handle.write(f"    Year:    {year}\n")
            handle.write(f'    Type:    {record.get("error_type", "unknown")}\n')
            details = record.get("error_details", "")
            if details:
                handle.write(f"    Details: {details}\n")
            handle.write("\n")
