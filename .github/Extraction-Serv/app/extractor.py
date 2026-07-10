import asyncio
import io
import logging
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional, Tuple

import arxiv


from service_core.core.refchecker import ArxivReferenceChecker
from service_core.llm.base import ReferenceExtractor, create_llm_provider
from service_core.utils.arxiv_utils import get_bibtex_content
from service_core.utils.cache_utils import (
    cache_bibliography,
    cached_bibliography,
    get_cached_artifact_path,
    llm_cache_identity_from_extractor,
)
from service_core.utils.grobid import extract_pdf_references_with_grobid_fallback
from service_core.utils.text_utils import extract_latex_references, validate_parsed_references
from service_core.utils.url_utils import download_pdf_bytes, extract_arxiv_id_from_url

logger = logging.getLogger(__name__)


def download_pdf(url: str, dest_path: str) -> None:
    """Download a PDF atomically to avoid partially-written files."""
    data = download_pdf_bytes(url)
    dir_name = os.path.dirname(dest_path)
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".pdf.tmp")
    try:
        os.write(fd, data)
        os.close(fd)
        os.replace(tmp_path, dest_path)
    except Exception:
        os.close(fd)
        os.unlink(tmp_path)
        raise


def _make_cli_checker(llm_provider):
    cli_checker = ArxivReferenceChecker.__new__(ArxivReferenceChecker)
    cli_checker.llm_extractor = ReferenceExtractor(llm_provider) if llm_provider else None
    cli_checker.llm_enabled = bool(llm_provider)
    cli_checker.used_regex_extraction = False
    cli_checker.used_unreliable_extraction = False
    cli_checker.fatal_error = False
    return cli_checker


def _extract_pdf_text_cli_style(pdf_path: str, llm_provider) -> str:
    cli_checker = _make_cli_checker(llm_provider)
    with open(pdf_path, "rb") as pdf_file:
        return cli_checker.extract_text_from_pdf(io.BytesIO(pdf_file.read()))


def _normalize_reference_fields(ref: Dict[str, Any]) -> Dict[str, Any]:
    if ref.get("journal") and not ref.get("venue"):
        ref["venue"] = ref["journal"]
    return ref


class ExtractionService:
    def __init__(
        self,
        llm_provider: Optional[str] = None,
        llm_model: Optional[str] = None,
        api_key: Optional[str] = None,
        endpoint: Optional[str] = None,
        use_llm: bool = True,
        progress_callback: Optional[Callable[[str, Dict[str, Any]], Any]] = None,
        cache_dir: Optional[str] = None,
    ):
        self.progress_callback = progress_callback
        self.cache_dir = cache_dir or str(Path(tempfile.gettempdir()) / "refchecker_extraction_cache")
        Path(self.cache_dir).mkdir(parents=True, exist_ok=True)

        self.llm = None
        if use_llm and llm_provider:
            llm_config: Dict[str, Any] = {}
            if llm_model:
                llm_config["model"] = llm_model
            if api_key:
                llm_config["api_key"] = api_key
            if endpoint:
                llm_config["endpoint"] = endpoint
            provider = create_llm_provider(provider_name=llm_provider, config=llm_config)
            if provider and provider.is_available():
                provider.cache_dir = self.cache_dir
                self.llm = provider


    def _bibliography_cache_identity(self) -> str:
        return llm_cache_identity_from_extractor(SimpleNamespace(llm_provider=self.llm) if self.llm else None)

    async def extract(self, paper_source: str, source_type: str) -> Dict[str, Any]:
        paper_title = "Unknown Paper"
        paper_text = ""
        pdf_path_for_fallback = None
        arxiv_source_references = None
        extraction_method = None
        bibliography_source_kind = None

        def set_extraction_method(method: Optional[str]) -> None:
            nonlocal extraction_method, bibliography_source_kind
            extraction_method = method
            if not method:
                return
            normalized = method.lower()
            if normalized == "cache":
                return
            bibliography_source_kind = "pdf" if normalized in {"file", "pdf"} else normalized

        async def maybe_extract_grobid_references(pdf_path: str, failure_message: str):
            refs, method = await asyncio.to_thread(
                extract_pdf_references_with_grobid_fallback,
                pdf_path=pdf_path,
                llm_available=bool(self.llm),
                failure_message=failure_message,
            )
            return refs, method

        bibliography_cache_identity = self._bibliography_cache_identity()

        if source_type == "url":
            is_direct_pdf_url = (
                (paper_source.lower().endswith(".pdf") or "openreview.net/pdf" in paper_source.lower())
                and "arxiv.org" not in paper_source.lower()
            )
            if is_direct_pdf_url:
                cached_bib = cached_bibliography(self.cache_dir, paper_source, bibliography_cache_identity)
                if cached_bib is not None:
                    set_extraction_method("cache")
                    bibliography_source_kind = "pdf"
                    references = cached_bib
                else:
                    pdf_path = get_cached_artifact_path(self.cache_dir, paper_source, "paper.pdf", create_dir=True)
                    if not os.path.exists(pdf_path) or os.path.getsize(pdf_path) == 0:
                        await asyncio.to_thread(download_pdf, paper_source, pdf_path)
                    pdf_path_for_fallback = pdf_path
                    set_extraction_method("pdf")
                    paper_text = await asyncio.to_thread(_extract_pdf_text_cli_style, pdf_path, self.llm)
                    references = None
            else:
                arxiv_id = extract_arxiv_id_from_url(paper_source) or paper_source

                def fetch_arxiv():
                    search = arxiv.Search(id_list=[arxiv_id])
                    return next(search.results())

                paper = await asyncio.to_thread(fetch_arxiv)
                paper_title = paper.title
                bibtex_content = await asyncio.to_thread(get_bibtex_content, paper)
                if bibtex_content:
                    arxiv_source_references, extracted_method = await self._extract_references_from_bibtex(bibtex_content)
                    set_extraction_method(extracted_method)
                if not arxiv_source_references:
                    pdf_path = get_cached_artifact_path(self.cache_dir, paper_source, "paper.pdf", create_dir=True)
                    if not os.path.exists(pdf_path) or os.path.getsize(pdf_path) == 0:
                        await asyncio.to_thread(paper.download_pdf, filename=pdf_path)
                    pdf_path_for_fallback = pdf_path
                    set_extraction_method("pdf")
                    paper_text = await asyncio.to_thread(_extract_pdf_text_cli_style, pdf_path, self.llm)
                references = arxiv_source_references
        elif source_type == "file":
            set_extraction_method("file")
            if paper_source.lower().endswith(".pdf"):
                pdf_path_for_fallback = paper_source
                paper_text = await asyncio.to_thread(_extract_pdf_text_cli_style, paper_source, self.llm)
                references = None
            elif paper_source.lower().endswith((".tex", ".txt", ".bib", ".bbl")):
                with open(paper_source, "r", encoding="utf-8") as f:
                    paper_text = f.read()
                if paper_source.lower().endswith(".bib"):
                    refs_result = await self._extract_references_from_bibtex(paper_text)
                    references = refs_result[0]
                    set_extraction_method("bib" if references else "file")
                elif paper_source.lower().endswith(".bbl"):
                    refs_result = await self._extract_references_from_bibtex(paper_text)
                    references = refs_result[0]
                    set_extraction_method("bbl" if references else "file")
                elif paper_source.lower().endswith(".txt"):
                    cli_checker = _make_cli_checker(self.llm)
                    refs = await asyncio.to_thread(cli_checker.parse_references, paper_text)
                    references = [_normalize_reference_fields(r) for r in refs] if refs else None
                    set_extraction_method("text" if references else "file")
                else:
                    references = None
            else:
                raise ValueError(f"Unsupported file type: {paper_source}")
        elif source_type == "text":
            set_extraction_method("text")
            paper_title = "Pasted Text"
            paper_text = paper_source
            references = None
            refs_result = await self._extract_references_from_bibtex(paper_text)
            if refs_result[0]:
                references = refs_result[0]
                set_extraction_method(refs_result[1] or "text")
        else:
            raise ValueError(f"Unsupported source type: {source_type}")

        if references is None:
            references = cached_bibliography(self.cache_dir, paper_source, bibliography_cache_identity)
            if references is not None:
                set_extraction_method("cache")

        if references is None:
            if arxiv_source_references:
                references = arxiv_source_references
            else:
                references = await self._extract_references(paper_text)
                if not references and pdf_path_for_fallback:
                    fallback_refs, fallback_method = await maybe_extract_grobid_references(
                        pdf_path_for_fallback,
                        "No LLM or GROBID available for PDF reference extraction.",
                    )
                    if fallback_refs:
                        references = fallback_refs
                        set_extraction_method(fallback_method)
                if self.llm and extraction_method in ("pdf", "file", "text"):
                    set_extraction_method("llm")

            if references:
                cache_bibliography(self.cache_dir, paper_source, references, bibliography_cache_identity)

        if not references:
            return {
                "paper_title": paper_title,
                "paper_source": paper_source,
                "extraction_method": extraction_method,
                "bibliography_source_kind": bibliography_source_kind,
                "references": [],
                "summary": {"total_refs": 0},
            }

        return {
            "paper_title": paper_title,
            "paper_source": paper_source,
            "extraction_method": extraction_method,
            "bibliography_source_kind": bibliography_source_kind,
            "references": references,
            "summary": {"total_refs": len(references)},
        }

    async def _extract_references(self, paper_text: str) -> List[Dict[str, Any]]:
        cli_checker = _make_cli_checker(self.llm)
        bib_section = await asyncio.to_thread(cli_checker.find_bibliography_section, paper_text)
        if not bib_section:
            return []
        refs = await asyncio.to_thread(cli_checker.parse_references, bib_section)
        if cli_checker.fatal_error:
            return []
        return [_normalize_reference_fields(ref) for ref in refs] if refs else []

    async def _extract_references_from_bibtex(self, bibtex_content: str) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        cli_checker = _make_cli_checker(self.llm)
        try:
            if "\\begin{thebibliography}" in bibtex_content and "\\bibitem" in bibtex_content:
                refs = await asyncio.to_thread(extract_latex_references, bibtex_content, None)
                if refs:
                    validation = await asyncio.to_thread(validate_parsed_references, refs)
                    if not validation["is_valid"] and self.llm:
                        llm_refs = await asyncio.to_thread(cli_checker.llm_extractor.extract_references, bibtex_content)
                        if llm_refs:
                            processed_refs = await asyncio.to_thread(
                                cli_checker._process_llm_extracted_references,
                                llm_refs,
                            )
                            llm_validation = await asyncio.to_thread(validate_parsed_references, processed_refs)
                            if llm_validation["quality_score"] > validation["quality_score"]:
                                return ([_normalize_reference_fields(ref) for ref in processed_refs], "llm")
                    return ([_normalize_reference_fields(ref) for ref in refs], "bbl")
            refs = await asyncio.to_thread(cli_checker.parse_references, bibtex_content)
            if cli_checker.fatal_error:
                return ([], None)
            return ([_normalize_reference_fields(ref) for ref in refs], "bib") if refs else ([], None)
        except Exception as e:
            logger.warning("BibTeX extraction failed: %s", e)
            return ([], None)

