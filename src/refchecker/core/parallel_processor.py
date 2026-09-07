"""Parallel reference verification with ordered output."""

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from queue import Queue
from threading import Lock, Thread
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ReferenceWorkItem:
    index: int
    source_paper: Any
    reference: Dict[str, Any]
    timestamp: float


@dataclass
class ReferenceResult:
    index: int
    errors: Optional[List[Dict[str, Any]]]
    url: Optional[str]
    processing_time: float
    reference: Dict[str, Any]
    verified_data: Optional[Dict[str, Any]] = None


class ParallelReferenceProcessor:
    """Verify references concurrently while printing and reporting them in order."""

    def __init__(self, base_checker: Any, max_workers: int = 6, enable_progress: bool = True):
        self.base_checker = base_checker
        self.max_workers = max_workers
        self.enable_progress = enable_progress
        self.work_queue = Queue()
        self.result_queue = Queue()
        self.result_buffer = {}
        self.buffer_lock = Lock()
        self.next_print_index = 0
        self.total_references = 0
        self.completed_count = 0
        self.start_time = 0
        self.processing_stats = {
            "total_processed": 0,
            "total_errors": 0,
            "avg_processing_time": 0,
            "fastest_time": float("inf"),
            "slowest_time": 0,
        }

    def verify_references_parallel(
        self,
        source_paper: Any,
        bibliography: List[Dict[str, Any]],
        result_callback: Optional[Callable] = None,
    ) -> Dict[str, Any]:
        if not bibliography:
            logger.info("No references to verify")
            return self._get_stats()

        self.total_references = len(bibliography)
        self.start_time = time.time()
        self.next_print_index = 0
        self.completed_count = 0
        self.result_buffer.clear()
        for index, reference in enumerate(bibliography):
            self.work_queue.put(ReferenceWorkItem(index, source_paper, reference, time.time()))
        for _ in range(self.max_workers):
            self.work_queue.put(None)

        printer_thread = Thread(target=self._ordered_result_printer, args=(result_callback,), daemon=True)
        printer_thread.start()
        with ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix="RefWorker") as executor:
            futures = [executor.submit(self._worker_loop, worker_id) for worker_id in range(self.max_workers)]
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as exc:
                    logger.error("Worker thread failed: %s", exc)
        printer_thread.join()
        return self._get_stats()

    def _worker_loop(self, worker_id: int) -> None:
        while True:
            work_item = self.work_queue.get(block=True)
            try:
                if work_item is None:
                    return
                started = time.time()
                try:
                    errors, url, verified_data = self.base_checker.verify_reference(
                        work_item.source_paper, work_item.reference
                    )
                    result = ReferenceResult(
                        work_item.index,
                        errors,
                        url,
                        time.time() - started,
                        work_item.reference,
                        verified_data,
                    )
                except Exception as exc:
                    logger.error("Worker %s failed to verify reference %s: %s", worker_id, work_item.index, exc)
                    result = ReferenceResult(
                        work_item.index,
                        [{"error_type": "processing_failed", "error_details": f"Internal processing error: {exc}"}],
                        None,
                        time.time() - work_item.timestamp,
                        work_item.reference,
                    )
                self.result_queue.put(result)
            finally:
                self.work_queue.task_done()

    def _ordered_result_printer(self, result_callback: Optional[Callable] = None) -> None:
        while self.next_print_index < self.total_references:
            result = self.result_queue.get(block=True)
            with self.buffer_lock:
                self.result_buffer[result.index] = result
                self._update_stats(result)
                while self.next_print_index in self.result_buffer:
                    current = self.result_buffer[self.next_print_index]
                    self._print_reference_result(current)
                    if result_callback:
                        try:
                            result_callback(current)
                        except Exception as exc:
                            logger.error("Result callback failed for reference %s: %s", current.index, exc)
                    del self.result_buffer[self.next_print_index]
                    self.next_print_index += 1
                    self.completed_count += 1

    def _print_reference_result(self, result: ReferenceResult) -> None:
        reference = result.reference
        self.base_checker._print_reference_header(reference, result.index, self.total_references)
        self.base_checker._print_verified_urls(reference, result.verified_data, result.url, result.errors)
        if result.errors:
            has_unverified = any(
                issue.get("error_type") == "unverified"
                or issue.get("warning_type") == "unverified"
                or issue.get("info_type") == "unverified"
                for issue in result.errors
            )
            if has_unverified:
                self.base_checker._display_unverified_error_with_subreason(
                    reference, result.url, result.errors, debug_mode=False, print_output=True
                )
            self.base_checker._display_non_unverified_errors(
                result.errors, debug_mode=False, print_output=True
            )
        if result.processing_time > 5.0:
            logger.debug(
                "Reference %s took %.2fs to verify: %s",
                result.index + 1,
                result.processing_time,
                reference.get("title", "Untitled"),
            )

    def _update_stats(self, result: ReferenceResult) -> None:
        self.processing_stats["total_processed"] += 1
        if result.errors:
            self.processing_stats["total_errors"] += len(result.errors)
        elapsed = result.processing_time
        self.processing_stats["fastest_time"] = min(self.processing_stats["fastest_time"], elapsed)
        self.processing_stats["slowest_time"] = max(self.processing_stats["slowest_time"], elapsed)
        total = self.processing_stats["total_processed"]
        average = self.processing_stats["avg_processing_time"]
        self.processing_stats["avg_processing_time"] = ((average * (total - 1)) + elapsed) / total

    def _get_stats(self) -> Dict[str, Any]:
        total_time = time.time() - self.start_time if self.start_time > 0 else 0
        fastest = self.processing_stats["fastest_time"]
        return {
            "total_references": self.total_references,
            "total_time": total_time,
            "references_per_second": self.total_references / total_time if total_time > 0 else 0,
            "total_errors": self.processing_stats["total_errors"],
            "avg_processing_time": self.processing_stats["avg_processing_time"],
            "fastest_time": fastest if fastest != float("inf") else 0,
            "slowest_time": self.processing_stats["slowest_time"],
        }
