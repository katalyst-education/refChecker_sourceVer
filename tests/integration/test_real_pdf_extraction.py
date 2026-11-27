"""Real-document regression tests using the repository's academic paper."""

import asyncio
import logging
import re
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.refchecker_wrapper import ProgressRefChecker
from refchecker.core.bulk_pipeline import (
    BulkLLMExtractionBatcher,
    extract_bibliography_bulk,
    parse_references_bulk,
)
from refchecker.core.refchecker import (
    ArxivReferenceChecker,
    _AUTHOR_YEAR_ENTRY_START_RE,
)
from refchecker.services.pdf_processor import PDFProcessor

logger = logging.getLogger(__name__)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ACADEMIC_PDF = REPOSITORY_ROOT / "paper" / "paper.pdf"
ACADEMIC_BIB = REPOSITORY_ROOT / "paper" / "paper.bib"


def test_academic_pdf_selects_references_not_architecture_heading(monkeypatch):
    monkeypatch.setattr(
        "refchecker.services.pdf_pipeline.text_extractors."
        "one_column_text_extractor.extract_grobid_metadata",
        lambda _pdf_path: {},
    )
    document = PDFProcessor().extract_document(
        str(ACADEMIC_PDF),
        include_bibliography=True,
    )
    checker = ArxivReferenceChecker(
        llm_config={"disabled": True},
        extraction_mode="cascade",
    )

    _, body_text, selected_bibliography = (
        checker._select_pdf_document_content(document)
    )
    expected_reference_count = len(
        re.findall(r"(?m)^\s*@", ACADEMIC_BIB.read_text(encoding="utf-8"))
    )
    detected_entries = _AUTHOR_YEAR_ENTRY_START_RE.findall(
        selected_bibliography
    )

    assert document.doc_type == "one_column_paper"
    assert len(document.pages) == 4
    assert selected_bibliography.startswith("Allen Institute for AI.")
    assert "localisation - heuristics detect section boundaries" not in (
        selected_bibliography
    )
    assert "localisation - heuristics detect section boundaries" in body_text
    assert len(detected_entries) == expected_reference_count == 6
    assert "Allen Institute for AI. 2024." not in body_text


def test_real_pdf_extraction_and_bibliography_selection_match_across_paths(
    monkeypatch, tmp_path, caplog
):
    monkeypatch.setattr(
        "refchecker.services.pdf_pipeline.text_extractors."
        "one_column_text_extractor.extract_grobid_metadata",
        lambda _pdf_path: {},
    )
    monkeypatch.setattr(
        "refchecker.utils.arxiv_utils.get_bibtex_content",
        lambda _paper: None,
    )
    monkeypatch.setattr(
        "refchecker.utils.grobid.extract_pdf_references_with_grobid_fallback",
        _raise_grobid_unavailable,
    )
    parser_inputs = []
    parse_references = ArxivReferenceChecker.parse_references

    def capture_parser_input(checker, bibliography_text, *args, **kwargs):
        parser_inputs.append(bibliography_text)
        return parse_references(checker, bibliography_text, *args, **kwargs)

    monkeypatch.setattr(
        ArxivReferenceChecker,
        "parse_references",
        capture_parser_input,
    )

    cache_dir = tmp_path / "cache"
    cli_checker = ArxivReferenceChecker(
        llm_config={"disabled": True},
        extraction_mode="cascade",
        cache_dir=str(cache_dir),
    )
    cli_paper = cli_checker._create_local_file_paper(str(ACADEMIC_PDF))
    assert not cli_paper.is_bibtex
    assert not cli_paper.is_latex
    assert not cli_paper.is_text_refs
    cli_references = cli_checker.extract_bibliography(cli_paper, debug_mode=False)
    cli_document = cli_checker.last_extracted_document
    _, cli_body, cli_bibliography = (
        cli_checker._select_pdf_document_content(cli_document)
    )

    webui = ProgressRefChecker.__new__(ProgressRefChecker)
    webui.check_id = None
    webui.llm = None
    webui.extraction_mode = "cascade"
    webui.emit_progress = AsyncMock()
    (
        webui_document,
        webui_full_text,
        webui_body,
        webui_bibliography,
    ) = webui._extract_pdf_document_scoped(str(ACADEMIC_PDF))
    webui_references, webui_method = asyncio.run(
        webui._extract_references_from_pdf(
            str(ACADEMIC_PDF),
            webui_body,
            bibliography_text=webui_bibliography,
            full_text=webui_full_text,
        )
    )

    bulk_checker = ArxivReferenceChecker(
        llm_config={"disabled": True},
        extraction_mode="cascade",
        cache_dir=str(cache_dir / "bulk"),
    )
    bulk_checker.download_pdf = lambda _paper: BytesIO(ACADEMIC_PDF.read_bytes())
    bulk_paper = SimpleNamespace(
        title="Academic RefChecker",
        file_path=str(ACADEMIC_PDF),
        get_short_id=lambda: "academic-refchecker",
        is_latex=False,
        is_bibtex=False,
        is_text_refs=False,
    )
    bulk_references = extract_bibliography_bulk(
        bulk_checker,
        bulk_paper,
        debug_mode=False,
        extraction_batcher=BulkLLMExtractionBatcher(enabled=False),
    )
    _, bulk_body, bulk_bibliography = (
        bulk_checker._select_pdf_document_content(
            bulk_checker.last_extracted_document
        )
    )

    assert cli_document.doc_type == webui_document.doc_type == (
        bulk_checker.last_extracted_document.doc_type
    )
    assert cli_document.extractor == webui_document.extractor == (
        bulk_checker.last_extracted_document.extractor
    )
    assert cli_body == webui_body == bulk_body
    assert cli_bibliography == webui_bibliography == bulk_bibliography
    assert cli_document.full_text == webui_full_text == (
        bulk_checker.last_extracted_document.full_text
    )
    assert cli_bibliography in cli_document.full_text
    assert cli_references == bulk_references == webui_references
    assert len(cli_references) == 6
    assert webui_method == "regex"
    assert cli_checker.last_reference_parser_method == "regex"
    assert bulk_checker.last_reference_parser_method == "regex"
    assert len(parser_inputs) == 3
    assert parser_inputs == [
        cli_bibliography,
        webui_bibliography,
        bulk_bibliography,
    ]
    assert cli_checker.fatal_error is False
    assert cli_checker.fatal_error_message is None
    assert bulk_checker.fatal_error is False
    assert bulk_checker.fatal_error_message is None
    assert webui._last_reference_parse_error is None
    assert cli_checker.llm_extractor is None
    assert bulk_checker.llm_extractor is None
    assert all(
        checker._split_numbered_reference_entries(bibliography) == []
        for checker, bibliography in (
            (cli_checker, cli_bibliography),
            (bulk_checker, bulk_bibliography),
        )
    )
    for document in (
        cli_document,
        webui_document,
        bulk_checker.last_extracted_document,
    ):
        diagnostics = document.metadata.get("extraction_diagnostics", {})
        assert diagnostics["document_status"] == "complete"
        assert diagnostics["bibliography_status"] == "extracted"
        assert len(document.pages) == 4

    candidate_count = len(
        _AUTHOR_YEAR_ENTRY_START_RE.findall(cli_bibliography)
    )
    assert candidate_count == 6
    normalized_bibliography = re.sub(
        r"[^a-z0-9]", "", cli_bibliography.casefold()
    )
    source_references = cli_checker._parse_bibtex_references(
        ACADEMIC_BIB.read_text(encoding="utf-8")
    )
    assert len(source_references) == 6
    assert all(
        re.sub(r"[^a-z0-9]", "", reference["title"].casefold())
        in normalized_bibliography
        for reference in source_references
    )
    expected_titles = (
        "Semantic Scholar Academic Graph Api",
        "Crossref Rest Api",
        "RefChecker Reference Based Fine Grained Hallucination Checker and Benchmark for Large Language Models",
        "OpenAlex A Fully Open Index of Scholarly Works Authors Venues Institutions and Concepts",
        "Recite Reference Checker",
        "Scite Reference Check",
    )
    title_positions = [
        normalized_bibliography.index(
            re.sub(r"[^a-z0-9]", "", title.casefold())
        )
        for title in expected_titles
    ]
    assert title_positions == sorted(title_positions)
    assert "GROBID unavailable for offline validation" in caplog.text
    logger.info(
        "Real-PDF path diagnostics: layout=%s pages=%d extractor=%s "
        "body_chars=%d bibliography_chars=%d detected_entries=%d parsed_counts=%s "
        "grobid=unavailable",
        cli_document.doc_type,
        len(cli_document.pages),
        cli_document.extractor,
        len(cli_body),
        len(cli_bibliography),
        candidate_count,
        (len(cli_references), len(webui_references), len(bulk_references)),
    )


def _raise_grobid_unavailable(**_kwargs):
    raise ValueError("GROBID unavailable for offline validation")


def test_webui_uses_local_text_when_grobid_is_unavailable(monkeypatch):
    monkeypatch.setattr(
        "backend.refchecker_wrapper.extract_pdf_references_with_grobid_fallback",
        _raise_grobid_unavailable,
    )
    webui = ProgressRefChecker.__new__(ProgressRefChecker)
    webui.check_id = None
    webui.llm = None
    webui.extraction_mode = "cascade"
    webui.emit_progress = AsyncMock()
    bibliography = (
        '[1] A. Smith, "First work," Journal of Tests, vol. 1, 2020.\n'
        '[2] B. Jones, "Second work," Journal of Tests, vol. 2, 2021.'
    )

    references, method = asyncio.run(
        webui._extract_references_from_pdf(
            "unused.pdf", bibliography, bibliography_text=bibliography
        )
    )

    assert [ref["title"] for ref in references] == ["First work", "Second work"]
    assert method == "regex"


def test_offline_mixed_reference_recovery_matches_across_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "backend.refchecker_wrapper.extract_pdf_references_with_grobid_fallback",
        _raise_grobid_unavailable,
    )
    bibliography = (
        '[1] Smith, A. (2022). An informative title. Journal of Testing.\n'
        '[2] A. Jones, Conference on Testing, 2021.'
    )
    cli = ArxivReferenceChecker(
        llm_config={"disabled": True}, cache_dir=str(tmp_path / "cli")
    )
    bulk = ArxivReferenceChecker(
        llm_config={"disabled": True}, cache_dir=str(tmp_path / "bulk")
    )
    webui = ProgressRefChecker.__new__(ProgressRefChecker)
    webui.check_id = None
    webui.llm = None
    webui.extraction_mode = "cascade"
    webui.emit_progress = AsyncMock()

    cli_refs = cli.parse_references(bibliography)
    bulk_refs = parse_references_bulk(
        bulk, bibliography, BulkLLMExtractionBatcher(enabled=False)
    )
    web_refs, _ = asyncio.run(
        webui._extract_references_from_pdf(
            "unused.pdf", bibliography, bibliography_text=bibliography
        )
    )

    assert cli_refs == bulk_refs == web_refs
    assert web_refs[0]["title"] == "An informative title"
    assert web_refs[1]["raw_text"].startswith("[2]")
    assert web_refs[1]["extraction_warnings"]


@pytest.mark.parametrize(("citation", "url"), [
    (
        '[1] A. Smith, "Study," Journal of Testing, 2020. [Online]. Available: '
        'https://www.tandfonline.com/doi/full/10.1080/030\n43797.2016.1232372',
        'https://www.tandfonline.com/doi/full/10.1080/03043797.2016.1232372',
    ),
    (
        '[1] H. Beetham, S. MacNeill, and L. McGill, "Beyond blended: rethinking '
        'curriculum and learning design," Apr 2024. [Online]. Available: '
        'https://www.jisc.ac.uk/guides/beyond-blended-rethinking-curriculum-a\n'
        'nd-learning-design',
        'https://www.jisc.ac.uk/guides/beyond-blended-rethinking-curriculum-and-learning-design',
    ),
])
def test_wrapped_source_url_matches_across_paths(monkeypatch, tmp_path, citation, url):
    monkeypatch.setattr(
        "backend.refchecker_wrapper.extract_pdf_references_with_grobid_fallback",
        _raise_grobid_unavailable,
    )
    bibliography = citation + '\n[2] B. Jones, "Another paper," Journal of Tests, 2021.'
    cli = ArxivReferenceChecker(
        llm_config={"disabled": True}, cache_dir=str(tmp_path / "cli")
    )
    bulk = ArxivReferenceChecker(
        llm_config={"disabled": True}, cache_dir=str(tmp_path / "bulk")
    )
    webui = ProgressRefChecker.__new__(ProgressRefChecker)
    webui.check_id = None
    webui.llm = None
    webui.extraction_mode = "cascade"
    webui.emit_progress = AsyncMock()

    cli_refs = cli.parse_references(bibliography)
    bulk_refs = parse_references_bulk(
        bulk, bibliography, BulkLLMExtractionBatcher(enabled=False)
    )
    web_refs, _ = asyncio.run(
        webui._extract_references_from_pdf(
            "unused.pdf", bibliography, bibliography_text=bibliography
        )
    )

    assert cli_refs == bulk_refs == web_refs
    assert cli_refs[0]["url"] == url


def test_frontiers_article_route_is_not_part_of_recovered_doi(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "backend.refchecker_wrapper.extract_pdf_references_with_grobid_fallback",
        _raise_grobid_unavailable,
    )
    bibliography = (
        '[1] M. O. Johansen et al., "The bright and dark side of autonomy," '
        'Frontiers in Education, 2023. [Online]. Available: '
        'https://www.frontiersin.org/journals/education/articles/10.3389/feduc.20\n'
        '23.1153647/full\n'
        '[2] B. Jones, "Another paper," Journal of Tests, 2021.'
    )
    cli = ArxivReferenceChecker(
        llm_config={"disabled": True}, cache_dir=str(tmp_path / "cli")
    )
    bulk = ArxivReferenceChecker(
        llm_config={"disabled": True}, cache_dir=str(tmp_path / "bulk")
    )
    webui = ProgressRefChecker.__new__(ProgressRefChecker)
    webui.check_id = None
    webui.llm = None
    webui.extraction_mode = "cascade"
    webui.emit_progress = AsyncMock()

    cli_refs = cli.parse_references(bibliography)
    bulk_refs = parse_references_bulk(
        bulk, bibliography, BulkLLMExtractionBatcher(enabled=False)
    )
    web_refs, _ = asyncio.run(
        webui._extract_references_from_pdf(
            "unused.pdf", bibliography, bibliography_text=bibliography
        )
    )

    assert cli_refs == bulk_refs == web_refs
    assert cli_refs[0]["url"].endswith("/10.3389/feduc.2023.1153647/full")
    assert cli_refs[0]["doi"] == "10.3389/feduc.2023.1153647"


def test_reviewed_citation_formats_match_across_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "backend.refchecker_wrapper.extract_pdf_references_with_grobid_fallback",
        _raise_grobid_unavailable,
    )
    bibliography = (
        "[1] Walters, K.; Rodriguez, J. The Importance of Training and "
        "Development in Employee Performance and Evaluation. World Wide "
        "J.Multidiscip. Res. Dev. 2017, 3, 206-212\n"
        "[2] Doost Mohammadian, H. Rezaie, F. Global SMEs; Volume 2 SMEs "
        "4.0 to Gain Sustainable Development Globally, Fachhochschule des "
        "Mittelstands (FHM) - University of Applied Sciences - Bielefeld - 2020\n"
        '[3] H. Smith, "A study," 2020 IEEE Learning With MOOCS (LWMOOCS), '
        'Antigua Guatemala, Guatemala, 2020, pp. 118-123, doi: 10.1109/123.\n'
        '[4] C. C. Beatty and K. L. Guthrie, "Developing culturally relevant '
        'leadership educators," New Directions for Student Leadership, '
        'no. 182, pp. 11-22, 2024.\n'
        '[5] D. H. Jonassen, Computers in the classroom: Mindtools for critical '
        'thinking. Prentice-Hall, Inc., 1996.\n'
        '[6] de Vaus, D., 2013. Surveys in Social Research, 6th ed. Routledge, London.\n'
        '[7] UNESCO, Guidance for Generative AI in Education and Research, Paris, 2023.\n'
        '[8] Xilinx, Debug Bridge v3.0 IP Product Guide (PG245), 2018.'
    )
    cli = ArxivReferenceChecker(
        llm_config={"disabled": True}, cache_dir=str(tmp_path / "cli")
    )
    bulk = ArxivReferenceChecker(
        llm_config={"disabled": True}, cache_dir=str(tmp_path / "bulk")
    )
    webui = ProgressRefChecker.__new__(ProgressRefChecker)
    webui.check_id = None
    webui.llm = None
    webui.extraction_mode = "cascade"
    webui.emit_progress = AsyncMock()

    cli_refs = cli.parse_references(bibliography)
    bulk_refs = parse_references_bulk(
        bulk, bibliography, BulkLLMExtractionBatcher(enabled=False)
    )
    web_refs, _ = asyncio.run(
        webui._extract_references_from_pdf(
            "unused.pdf", bibliography, bibliography_text=bibliography
        )
    )

    assert cli_refs == bulk_refs == web_refs
    assert web_refs[0]["authors"] == ["Walters, K.", "Rodriguez, J."]
    assert web_refs[1]["title"] == "Global SMEs; Volume 2 SMEs 4.0 to Gain Sustainable Development Globally"
    assert web_refs[2]["venue"] == "2020 IEEE Learning With MOOCS (LWMOOCS)"
    assert web_refs[3]["venue"] == "New Directions for Student Leadership"
    assert web_refs[4]["authors"] == ["D. H. Jonassen"]
    assert web_refs[4]["title"] == "Computers in the classroom: Mindtools for critical thinking"
    assert web_refs[4]["venue"] == "Prentice-Hall, Inc"
    assert web_refs[5]["authors"] == ["de Vaus, D."]
    assert web_refs[5]["title"] == "Surveys in Social Research"
    assert web_refs[5]["venue"] == "Routledge"
    assert web_refs[6]["authors"] == ["UNESCO"]
    assert web_refs[6]["title"] == "Guidance for Generative AI in Education and Research"
    assert not web_refs[6].get("venue")
    assert web_refs[7]["authors"] == ["Xilinx"]
    assert web_refs[7]["title"] == "Debug Bridge v3.0 IP Product Guide (PG245)"
    assert not web_refs[7].get("venue")


@pytest.mark.parametrize(("citation", "venue"), [
    ('[1] OpenAI, "Introducing study mode," OpenAI, Jul. 29, 2025. '
     'Accessed: Nov. 10, 2025. [Online]. Available: https://openai.com/index/study-mode.',
     'OpenAI'),
    ('[1] Mohammadian, H. D. Internet of Energy: A Solution for Improving the '
     'Efficiency of Reversible Energy. In the Proceeding of IEEE Global Engineering '
     'Education Conference (EDUCON). 17-20 April. Tenerife, Spain. 2018',
     'In the Proceeding of IEEE Global Engineering Education Conference (EDUCON)'),
    ('[1] R. Annapureddy, A. Fornaroli, and D. Gatica-Perez, "Generative AI '
     'literacy: Twelve defining competencies". Digital Government: Research '
     'and Practice, 6(1), pp.1-21. 2025.',
     'Digital Government: Research and Practice'),
    ('[1] R. E. Boyatzis, The Competent Manager: A Model for Effective '
     'Performance, New York: John Wiley & Sons, 1982.',
     'John Wiley & Sons'),
    ('[1] L.-O. Johansson et al., "Digital Design and Learning Students '
     'Reflections on Learning-by-Doing," Proc. EDULEARN18 Conf., '
     'Palma de Mallorca, Spain, 2018.',
     'Proc. EDULEARN18 Conf.'),
    ('[1] D. A. Dever et al. "Identifying the effects of scaffolding". In: '
     'Frontiers in Psychology 14 (Nov. 2023), p. 1280566. DOI: 10.3389/example.',
     'Frontiers in Psychology'),
    ('[1] Borchers, C., & Pardos, Z. A. Course load analytics interventions '
     'on higher education course selection: Experimental evidence. Journal of '
     'Learning Analytics, 12(2), 293-311, 2025. doi: 10.18608/jla.2025.8473.',
     'Journal of Learning Analytics'),
    ("[1] Mohammadian, H. D., ''Mapping the future sustainable, through the "
     "5th wave theory'', in the 2022 IEEE conference, Global Engineering "
     "Education Conference (EDUCON), in Tunis, Tunisia, from 28-31 March 2022",
     'Global Engineering Education Conference (EDUCON)'),
    ('[1] Chen, E., et al. VTutor: An animated pedagogical agent SDK that '
     'provides real-time multimodal feedback. arXiv preprint, arXiv:2505.06676, 2025.',
     'arXiv preprint'),
    ('[1] D. Maxwell et al., "Generative AI in higher education: Demographic '
     'differences in student perceived readiness, benefits, and challenges," '
     'TechTrends, pp. 1-12, 2025.', 'TechTrends'),
    ('[1] H. Goyel and K. S. Swarup, "Data Integrity Attack Detection Using '
     'Ensemble-Based Learning for Cyber-Physical Power Systems," IEEE Transactions '
     'on Smart Grid, pp. 1198-1209, 2023.', 'IEEE Transactions on Smart Grid'),
    ('[1] K. M. Kim and R. Md-Ali, "GeoGebra: Towards realizing 21st century '
     'learning in mathematics education," Malaysian Journal of Learning and '
     'Instruction, pp. 93-115, 2017. [Online]. Available: '
     'https://doi.org/10.32890/mjli.2017.7799', 'Malaysian Journal of Learning and Instruction'),
    ('[1] H. Vartiainen and M. Tedre, "Towards transformative AI education '
     'through cross-boundary co-design," in Proceedings of the International '
     'Conference on Smart Learning Environments, Joensuu, Finland, October '
     '16-17 2025.', 'Proceedings of the International Conference on Smart Learning Environments'),
    ('[1] A. Friesel et al., "Preparing skills for STEM graduates," in '
     'Proceedings of the 2022 31st Annual Conference of the European Association '
     'for Education in Electrical and Information Engineering, EAEEIE 2022, '
     'Coimbra, Portugal: IEEE, 2022. doi: 10.1109/EAEEIE54893.2022.9820223.',
     'Proceedings of the 2022 31st Annual Conference of the European Association '
     'for Education in Electrical and Information Engineering, EAEEIE 2022'),
    ('[1] A. Moreira et al., "A Road Less Travelled and Beyond: Towards a Roadmap '
     'for Integrating Sustainability into Computing Education," 2024, arXiv. '
     'doi: 10.48550/ARXIV.2406.18945.', 'arXiv'),
    ('[1] H. Leite, "Artificial intelligence in higher education: Research notes '
     'from a longitudinal study", Technological Forecasting & Social Change, 215, 2025',
     'Technological Forecasting & Social Change'),
    ('[1] Hilton, J. Open educational resources and college textbook choices: a '
     'review of research on efficacy and perceptions. Education Tech Research Dev '
     '64, 573-590 (2016).', 'Education Tech Research Dev'),
    ('[1] A. Almusaed, M. R. Cortez, and A. Almssad, '
     '"Redefining Engineering Education: The Transformative Role of Generative AI '
     'Technologies", International Society for Technology, Education, and Science, '
     '2024.', 'International Society for Technology, Education, and Science'),
    ('[1] C. T. Cripe, "Real-time cognitive tools for space," Intelligent Human '
     'Systems Integration (IHSI 2025): Integrating People and Intelligent Systems, '
     'p. 87, 2025.', 'Intelligent Human Systems Integration (IHSI 2025): Integrating '
     'People and Intelligent Systems'),
    ('[1] B. Qureshi, "Chatgpt in computer science curriculum assessment: An analysis '
     'of its successes and shortcomings," in 2023 9th International Conference on '
     'e-Society e-Learning and e-Technologies, ICSLT 2023, p. 7-13, ACM, June 2023.',
     '2023 9th International Conference on e-Society e-Learning and e-Technologies, ICSLT 2023'),
    ('[1] Francois Lopitaux, "Spotter: Your ai analyst," ThoughtSpot, Tech. Rep., '
     '2025, [Online]. Available: https://www.thoughtspot.com/blog/everyone-gets-an-ai-analyst.',
     'ThoughtSpot'),
    ('[1] F. Gottschalk and H. Borhan, "Child participation in decision making: '
     'Implications for education and beyond," tech. rep., OECD, Paris, Nov. 2023.',
     'OECD'),
    ('[1] National Academy of Engineering, Engineering as a Social Enterprise. '
     'Washington, D.C.: National Academies Press, 1991. doi: 10.17226/1829.',
     'National Academies Press'),
    ('[5] Coyle, D., Hood, P., and D. Marsh, CLIL: Content and Language Integrated '
     'Learning, Cambridge University Press, 2010.', 'Cambridge University Press'),
    ('[6] Hyland, K., English for Academic Purposes: An Advanced Resource Book, '
     'Routledge, 2006.', 'Routledge'),
    ('[1] Ministry of Education of China, Outstanding Engineer Education and '
     'Training Plan 2.0, 2018.', ''),
    ('[2] Ministry of Education, Ministry of Industry and Information Technology, '
     'and Chinese Academy of Engineering, Opinions on Accelerating the Development '
     'of Emerging Engineering Disciplines and Implementing the Outstanding Engineer '
     'Education and Training Programme 2.0, 2018.', ''),
    ('[16] Organización de las Naciones Unidas para la Educación, la Ciencia y la '
     'Cultura (UNESCO), Guidance for Generative AI in Education and Research. '
     'Paris: UNESCO, 2023, doi: 10.54675/unesco.2023.iaedu.', 'UNESCO'),
    ('[17] OECD, OECD Framework for the Classification of AI Systems. Paris: '
     'OECD Publishing, 2022, doi: 10.1787/cb6aeca5-en.', 'OECD Publishing'),
    ('[1] Xu L. Innovative interdisciplinary models in engineering education: '
     'Transforming practices across global universities. Engineering Education '
     'Review 2025;2(3):129-144.', 'Engineering Education Review'),
])
def test_dated_source_venue_matches_across_paths(monkeypatch, tmp_path, citation, venue):
    monkeypatch.setattr(
        "backend.refchecker_wrapper.extract_pdf_references_with_grobid_fallback",
        _raise_grobid_unavailable,
    )
    citation = re.sub(r'^\[\d+\]', '[1]', citation, count=1)
    bibliography = citation + '\n[2] A. Other, "Another paper," Journal of Tests, 2020.'
    cli = ArxivReferenceChecker(
        llm_config={"disabled": True}, cache_dir=str(tmp_path / "cli")
    )
    bulk = ArxivReferenceChecker(
        llm_config={"disabled": True}, cache_dir=str(tmp_path / "bulk")
    )
    webui = ProgressRefChecker.__new__(ProgressRefChecker)
    webui.check_id = None
    webui.llm = None
    webui.extraction_mode = "cascade"
    webui.emit_progress = AsyncMock()

    cli_refs = cli.parse_references(bibliography)
    bulk_refs = parse_references_bulk(
        bulk, bibliography, BulkLLMExtractionBatcher(enabled=False)
    )
    web_refs, _ = asyncio.run(
        webui._extract_references_from_pdf(
            "unused.pdf", bibliography, bibliography_text=bibliography
        )
    )

    assert cli_refs == bulk_refs == web_refs
    if venue:
        assert cli_refs[0]["venue"] == venue
    else:
        assert not (cli_refs[0].get("venue") or cli_refs[0].get("journal"))
    if venue == "Education Tech Research Dev":
        assert cli_refs[0]["title"] == (
            "Open educational resources and college textbook choices: a review of research on efficacy and perceptions"
        )
    if venue == "Engineering Education Review":
        assert cli_refs[0]["title"] == (
            "Innovative interdisciplinary models in engineering education: "
            "Transforming practices across global universities"
        )
    if venue == "National Academies Press":
        assert cli_refs[0]["authors"] == ["National Academy of Engineering"]
        assert cli_refs[0]["title"] == "Engineering as a Social Enterprise"
    if venue == "Cambridge University Press":
        assert cli_refs[0]["authors"] == ["Coyle, D.", "Hood, P.", "D. Marsh"]
        assert cli_refs[0]["title"] == "CLIL: Content and Language Integrated Learning"
    if venue == "Routledge":
        assert cli_refs[0]["authors"] == ["Hyland, K."]
        assert cli_refs[0]["title"] == "English for Academic Purposes: An Advanced Resource Book"
    if venue == "UNESCO":
        assert cli_refs[0]["authors"] == [
            "Organización de las Naciones Unidas para la Educación, la Ciencia y la Cultura (UNESCO)"
        ]
        assert cli_refs[0]["title"] == "Guidance for Generative AI in Education and Research"
    if venue == "OECD Publishing":
        assert cli_refs[0]["authors"] == ["OECD"]
        assert cli_refs[0]["title"] == "OECD Framework for the Classification of AI Systems"
    if venue == "John Wiley & Sons":
        assert cli_refs[0]["authors"] == ["R. E. Boyatzis"]
        assert cli_refs[0]["title"] == "The Competent Manager: A Model for Effective Performance"


def test_title_first_website_fields_match_across_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "backend.refchecker_wrapper.extract_pdf_references_with_grobid_fallback",
        _raise_grobid_unavailable,
    )
    bibliography = (
        "[1] Types of HVAC systems. (2018, November 5). IntechOpen - Open Science "
        "Open Minds | IntechOpen. https://www.intechopen.com/chapters/62059\n"
        "[2] Work Breakdown Structure (WBS): The Ultimate Guide (with Examples). "
        "(n.d.). https://www.projectmanager.com/guides/work-breakdown-structure."
    )
    cli = ArxivReferenceChecker(llm_config={"disabled": True}, cache_dir=str(tmp_path / "cli"))
    bulk = ArxivReferenceChecker(llm_config={"disabled": True}, cache_dir=str(tmp_path / "bulk"))
    webui = ProgressRefChecker.__new__(ProgressRefChecker)
    webui.check_id = None
    webui.llm = None
    webui.extraction_mode = "cascade"
    webui.emit_progress = AsyncMock()

    cli_refs = cli.parse_references(bibliography)
    bulk_refs = parse_references_bulk(bulk, bibliography, BulkLLMExtractionBatcher(enabled=False))
    web_refs, _ = asyncio.run(
        webui._extract_references_from_pdf(
            "unused.pdf", bibliography, bibliography_text=bibliography
        )
    )

    assert cli_refs == bulk_refs == web_refs
    assert cli_refs[0]["title"] == "Types of HVAC systems"
    assert cli_refs[0]["venue"] == "IntechOpen - Open Science Open Minds | IntechOpen"
    assert cli_refs[0]["field_extraction_status"]["authors"] == "absent"
    assert cli_refs[1]["title"] == "Work Breakdown Structure (WBS): The Ultimate Guide (with Examples)"
    assert cli_refs[1]["field_extraction_status"] == {"authors": "absent", "venue": "absent"}


def test_annual_title_first_web_fields_match_across_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "backend.refchecker_wrapper.extract_pdf_references_with_grobid_fallback",
        _raise_grobid_unavailable,
    )
    bibliography = (
        "[1] Official websites of universities in the World University Rankings "
        "Top- 100, Times Higher Education, 2025. [Online]. Available: "
        "https://www.timeshighereducation.com/world-ranking. "
        "(Accessed: 17 November 2025).\n"
        '[2] A. Other, "Another paper," Journal of Tests, 2020.'
    )
    cli = ArxivReferenceChecker(llm_config={"disabled": True}, cache_dir=str(tmp_path / "cli"))
    bulk = ArxivReferenceChecker(llm_config={"disabled": True}, cache_dir=str(tmp_path / "bulk"))
    webui = ProgressRefChecker.__new__(ProgressRefChecker)
    webui.check_id = None
    webui.llm = None
    webui.extraction_mode = "cascade"
    webui.emit_progress = AsyncMock()

    cli_refs = cli.parse_references(bibliography)
    bulk_refs = parse_references_bulk(bulk, bibliography, BulkLLMExtractionBatcher(enabled=False))
    web_refs, _ = asyncio.run(
        webui._extract_references_from_pdf(
            "unused.pdf", bibliography, bibliography_text=bibliography
        )
    )

    assert cli_refs == bulk_refs == web_refs
    assert cli_refs[0]["title"] == (
        "Official websites of universities in the World University Rankings Top- 100"
    )
    assert cli_refs[0]["venue"] == "Times Higher Education"
    assert cli_refs[0]["year"] == 2025
    assert cli_refs[0]["field_extraction_status"]["authors"] == "absent"


def test_author_year_web_journal_fields_match_across_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "backend.refchecker_wrapper.extract_pdf_references_with_grobid_fallback",
        _raise_grobid_unavailable,
    )
    bibliography = (
        "[1] T. Yu. Krotenko, Engineering economics and technological "
        "education: A transdisciplinary approach to the training of modern "
        "engineers, Vestn. PNIPU. Sotsial'no-ekon. Nauki, no. 4, 2022. "
        "[Online]. Available: https://example.com/article. "
        "(Accessed: 3 November 2025).\n"
        '[2] A. Other, "Another paper," Journal of Tests, 2020.'
    )
    cli = ArxivReferenceChecker(llm_config={"disabled": True}, cache_dir=str(tmp_path / "cli"))
    bulk = ArxivReferenceChecker(llm_config={"disabled": True}, cache_dir=str(tmp_path / "bulk"))
    webui = ProgressRefChecker.__new__(ProgressRefChecker)
    webui.check_id = None
    webui.llm = None
    webui.extraction_mode = "cascade"
    webui.emit_progress = AsyncMock()

    cli_refs = cli.parse_references(bibliography)
    bulk_refs = parse_references_bulk(bulk, bibliography, BulkLLMExtractionBatcher(enabled=False))
    web_refs, _ = asyncio.run(
        webui._extract_references_from_pdf(
            "unused.pdf", bibliography, bibliography_text=bibliography
        )
    )

    assert cli_refs == bulk_refs == web_refs
    assert cli_refs[0]["authors"] == ["T. Yu. Krotenko"]
    assert cli_refs[0]["title"] == (
        "Engineering economics and technological education: A "
        "transdisciplinary approach to the training of modern engineers"
    )
    assert cli_refs[0]["venue"] == "Vestn. PNIPU. Sotsial'no-ekon. Nauki"


def test_spaced_protocol_url_matches_across_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "backend.refchecker_wrapper.extract_pdf_references_with_grobid_fallback",
        _raise_grobid_unavailable,
    )
    bibliography = (
        '[1] Ministry of Education, "Base National Curriculum," 2017. '
        "[Online]. Available: http:// basenacionalcomum.mec.gov.br/\n"
        '[2] A. Other, "Another paper," Journal of Tests, 2020.'
    )
    cli = ArxivReferenceChecker(
        llm_config={"disabled": True}, cache_dir=str(tmp_path / "cli")
    )
    bulk = ArxivReferenceChecker(
        llm_config={"disabled": True}, cache_dir=str(tmp_path / "bulk")
    )
    webui = ProgressRefChecker.__new__(ProgressRefChecker)
    webui.check_id = None
    webui.llm = None
    webui.extraction_mode = "cascade"
    webui.emit_progress = AsyncMock()

    cli_refs = cli.parse_references(bibliography)
    bulk_refs = parse_references_bulk(
        bulk, bibliography, BulkLLMExtractionBatcher(enabled=False)
    )
    web_refs, _ = asyncio.run(
        webui._extract_references_from_pdf(
            "unused.pdf", bibliography, bibliography_text=bibliography
        )
    )

    assert cli_refs == bulk_refs == web_refs
    assert cli_refs[0]["url"] == "http://basenacionalcomum.mec.gov.br/"


def test_missing_quoted_venue_is_recovered_across_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "backend.refchecker_wrapper.extract_pdf_references_with_grobid_fallback",
        _raise_grobid_unavailable,
    )
    bibliography = (
        '[1] J. Southworth, K. Migliaccio, J. Glover, J.N. Glover, D. Reed, '
        'C. McCarty, J. Brendemuhl and A. Thomas, "Developing a model for AI '
        'Across the curriculum: Transforming the higher education landscape '
        'via innovation in AI literacy," Computers and Education: Artificial '
        'Intelligence, no. 4, p. 100127, 2023.\n'
        '[2] B. Other, "Another paper," Journal of Testing, 2020.'
    )
    cli = ArxivReferenceChecker(
        llm_config={"disabled": True}, cache_dir=str(tmp_path / "cli")
    )
    bulk = ArxivReferenceChecker(
        llm_config={"disabled": True}, cache_dir=str(tmp_path / "bulk")
    )
    webui = ProgressRefChecker.__new__(ProgressRefChecker)
    webui.check_id = None
    webui.llm = None
    webui.extraction_mode = "cascade"
    webui.emit_progress = AsyncMock()

    cli_refs = cli.parse_references(bibliography)
    bulk_refs = parse_references_bulk(
        bulk, bibliography, BulkLLMExtractionBatcher(enabled=False)
    )
    web_refs, _ = asyncio.run(
        webui._extract_references_from_pdf(
            "unused.pdf", bibliography, bibliography_text=bibliography
        )
    )

    assert cli_refs == bulk_refs == web_refs
    assert cli_refs[0]["venue"] == "Computers and Education: Artificial Intelligence"


def test_quoted_venue_without_standard_cue_matches_across_paths(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(
        "backend.refchecker_wrapper.extract_pdf_references_with_grobid_fallback",
        _raise_grobid_unavailable,
    )
    bibliography = (
        '[1] M. J. Page et al., "The PRISMA 2020 statement: an updated '
        'guideline for reporting systematic reviews," BMJ, p. n71, Mar. 2021.\n'
        '[2] B. Other, "Another paper," Journal of Testing, 2020.'
    )
    cli = ArxivReferenceChecker(
        llm_config={"disabled": True}, cache_dir=str(tmp_path / "cli")
    )
    bulk = ArxivReferenceChecker(
        llm_config={"disabled": True}, cache_dir=str(tmp_path / "bulk")
    )
    webui = ProgressRefChecker.__new__(ProgressRefChecker)
    webui.check_id = None
    webui.llm = None
    webui.extraction_mode = "cascade"
    webui.emit_progress = AsyncMock()

    cli_refs = cli.parse_references(bibliography)
    bulk_refs = parse_references_bulk(
        bulk, bibliography, BulkLLMExtractionBatcher(enabled=False)
    )
    web_refs, _ = asyncio.run(
        webui._extract_references_from_pdf(
            "unused.pdf", bibliography, bibliography_text=bibliography
        )
    )

    assert cli_refs == bulk_refs == web_refs
    assert cli_refs[0]["venue"] == "BMJ"


def test_unquoted_publisher_book_fields_match_across_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "backend.refchecker_wrapper.extract_pdf_references_with_grobid_fallback",
        _raise_grobid_unavailable,
    )
    bibliography = (
        "[1] E. L. Deci and R. M. Ryan, Intrinsic Motivation and "
        "Self-Determination in Human Behavior. Springer Science & Business "
        "Media, June 2013. Google-Books-ID: M3CpBgAAQBAJ.\n"
        "[2] A. Field, Discovering Statistics Using IBM SPSS Statistics "
        "(4th Edition), vol. 4. 2013.\n"
        "[3] Arm Cortex-A Series (Armv7-A) Programmer's Guide.\n"
        "[4] STM32CubeIDE - Software - STMicroelectronics."
    )
    cli = ArxivReferenceChecker(
        llm_config={"disabled": True}, cache_dir=str(tmp_path / "cli")
    )
    bulk = ArxivReferenceChecker(
        llm_config={"disabled": True}, cache_dir=str(tmp_path / "bulk")
    )
    webui = ProgressRefChecker.__new__(ProgressRefChecker)
    webui.check_id = None
    webui.llm = None
    webui.extraction_mode = "cascade"
    webui.emit_progress = AsyncMock()

    cli_refs = cli.parse_references(bibliography)
    bulk_refs = parse_references_bulk(
        bulk, bibliography, BulkLLMExtractionBatcher(enabled=False)
    )
    web_refs, _ = asyncio.run(
        webui._extract_references_from_pdf(
            "unused.pdf", bibliography, bibliography_text=bibliography
        )
    )

    assert cli_refs == bulk_refs == web_refs
    assert cli_refs[0]["authors"] == ["E. L. Deci", "R. M. Ryan"]
    assert cli_refs[0]["title"] == (
        "Intrinsic Motivation and Self-Determination in Human Behavior"
    )
    assert cli_refs[0]["venue"] == "Springer Science & Business Media"
    assert cli_refs[1]["authors"] == ["A. Field"]
    assert cli_refs[1]["title"] == (
        "Discovering Statistics Using IBM SPSS Statistics (4th Edition)"
    )
    assert not cli_refs[1].get("venue")
    assert cli_refs[2]["title"] == (
        "Arm Cortex-A Series (Armv7-A) Programmer's Guide"
    )
    assert cli_refs[3]["title"] == "STM32CubeIDE - Software"
    assert cli_refs[3]["venue"] == "STMicroelectronics"


def test_source_field_recovery_matches_across_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "backend.refchecker_wrapper.extract_pdf_references_with_grobid_fallback",
        _raise_grobid_unavailable,
    )
    bibliography = (
        "[1] Wenqing Wu, Zhenfang Zhu, Jiangtao Qi, Wenling Wang, Guangyuan "
        "Zhang, Peiyu Liu, A dynamic graph expansion network for multi-hop "
        "knowledge base question answering, Neurocomputing, Volume 515, "
        "2023, Pages 37-47, ISSN 0925-2312.\n"
        "[2] Ziyan Li, Haofen Wang, Wenqiang Zhang, Translational relation "
        "embeddings for multi-hop knowledge base question answering, Journal "
        "of Web Semantics, Volume 74, 2022, 100723, ISSN 1570-8268.\n"
        "[3] Government of India, The Rights of Persons with Disabilities "
        "(RPwD) Act, 2016, Ministry of Social Justice and Empowerment, "
        "New Delhi, 2016.\n"
        "[4] Paraskevi Topali et al. Designing human-centered learning "
        "analytics and artificial intelligence in education solutions: a "
        "systematic literature review. Behaviour & Information Technology, "
        "44(5):1071-1098, 2025.\n"
        "[5] ENAEE, 2022. EUR-ACE Framework Standards and Guidelines (EAFS). "
        "Tech. rep., European Network for Accreditation of Engineering "
        "Education.\n"
        '[6] P.R. Nair "Increasing Employability of Indian Engineering '
        'Graduates through Experiential Learning Programs" Procedia Computer Science.\n'
        "[7] OpenAI, ChatGPT (GPT-5) [Large language model]. [Online]. "
        "Available: https://chat.openai.com/\n"
        '[8] "Spatial Skills and their Relationship to Creativity and Innovation '
        'in Undergraduate Engineering Design" by Sheryl A. Sorby.\n'
        "[9] J. C. Nunnally y I. H. Bernstein, Psychometric theory, "
        "3. ed., 1994.\n"
        "[10] Superintendencia Nacional de Educación, SUNEDU. "
        "https://enlinea.sunedu.gob.pe/"
    )
    cli = ArxivReferenceChecker(
        llm_config={"disabled": True}, cache_dir=str(tmp_path / "cli")
    )
    bulk = ArxivReferenceChecker(
        llm_config={"disabled": True}, cache_dir=str(tmp_path / "bulk")
    )
    webui = ProgressRefChecker.__new__(ProgressRefChecker)
    webui.check_id = None
    webui.llm = None
    webui.extraction_mode = "cascade"
    webui.emit_progress = AsyncMock()

    cli_refs = cli.parse_references(bibliography)
    bulk_refs = parse_references_bulk(
        bulk, bibliography, BulkLLMExtractionBatcher(enabled=False)
    )
    web_refs, _ = asyncio.run(
        webui._extract_references_from_pdf(
            "unused.pdf", bibliography, bibliography_text=bibliography
        )
    )

    assert cli_refs == bulk_refs == web_refs
    assert cli_refs[0]["authors"] == [
        "Wenqing Wu", "Zhenfang Zhu", "Jiangtao Qi", "Wenling Wang",
        "Guangyuan Zhang", "Peiyu Liu",
    ]
    assert cli_refs[0]["title"] == (
        "A dynamic graph expansion network for multi-hop knowledge base "
        "question answering"
    )
    assert cli_refs[0]["venue"] == "Neurocomputing"
    assert cli_refs[1]["title"] == (
        "Translational relation embeddings for multi-hop knowledge base "
        "question answering"
    )
    assert cli_refs[1]["venue"] == "Journal of Web Semantics"
    assert cli_refs[2]["authors"] == ["Government of India"]
    assert cli_refs[2]["title"] == (
        "The Rights of Persons with Disabilities (RPwD) Act, 2016"
    )
    assert cli_refs[2]["venue"] == "Ministry of Social Justice and Empowerment"
    assert cli_refs[3]["venue"] == "Behaviour & Information Technology"
    assert cli_refs[4]["authors"] == ["ENAEE"]
    assert cli_refs[4]["title"] == "EUR-ACE Framework Standards and Guidelines (EAFS)"
    assert cli_refs[4]["venue"] == "European Network for Accreditation of Engineering Education"
    assert cli_refs[5]["authors"] == ["P.R. Nair"]
    assert cli_refs[5]["title"] == (
        "Increasing Employability of Indian Engineering Graduates through "
        "Experiential Learning Programs"
    )
    assert cli_refs[6]["authors"] == ["OpenAI"]
    assert cli_refs[7]["authors"] == ["Sheryl A. Sorby"]
    assert cli_refs[8]["authors"] == ["J. C. Nunnally", "I. H. Bernstein"]
    assert cli_refs[9]["authors"] == [
        "Superintendencia Nacional de Educación, SUNEDU",
    ]


def test_doi_joined_unlabelled_citation_is_recovered_across_paths(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(
        "backend.refchecker_wrapper.extract_pdf_references_with_grobid_fallback",
        _raise_grobid_unavailable,
    )
    bibliography = (
        "[1] Javidi, G., & Sheybani, E. (2019). Design and development of a "
        "modular K12 cybersecurity curriculum. ASEE Annual Conference and "
        "Exposition, Conference Proceedings. "
        "https://doi.org/10.18260/1-2--\n32591Gkioulos, V., & Chowdhury, N. "
        "(2021). Cyber security training for critical infrastructure protection: "
        "A literature review. In Computer Science Review (Vol. 40). "
        "https://doi.org/10.1016/j.cosrev.2021.100361\n"
        "[2] Workman, M. D., Anthony Luevanos, J., & Mai, B. (2022). A Study "
        "of Cybersecurity Education Using a Present-Test-Practice-Assess Model. "
        "IEEE Transactions on Education, 65(1). "
        "https://doi.org/10.1109/TE.2021.3086025"
    )
    cli = ArxivReferenceChecker(
        llm_config={"disabled": True}, cache_dir=str(tmp_path / "cli")
    )
    bulk = ArxivReferenceChecker(
        llm_config={"disabled": True}, cache_dir=str(tmp_path / "bulk")
    )
    webui = ProgressRefChecker.__new__(ProgressRefChecker)
    webui.check_id = None
    webui.llm = None
    webui.extraction_mode = "cascade"
    webui.emit_progress = AsyncMock()

    cli_refs = cli.parse_references(bibliography)
    bulk_refs = parse_references_bulk(
        bulk, bibliography, BulkLLMExtractionBatcher(enabled=False)
    )
    web_refs, _ = asyncio.run(
        webui._extract_references_from_pdf(
            "unused.pdf", bibliography, bibliography_text=bibliography
        )
    )

    assert cli_refs == bulk_refs == web_refs
    assert len(cli_refs) == 3
    assert cli_refs[1]["authors"] == ["Gkioulos, V.", "Chowdhury, N."]
    assert cli_refs[1]["title"] == (
        "Cyber security training for critical infrastructure protection: "
        "A literature review"
    )
    assert cli_refs[1]["venue"] == "Computer Science Review"
    assert cli_refs[1]["doi"] == "10.1016/j.cosrev.2021.100361"


def test_numbered_author_year_fields_match_across_paths(monkeypatch, tmp_path, capsys):
    from backend.reference_result import project_verification_result
    from refchecker.checkers.enhanced_hybrid_checker import EnhancedHybridReferenceChecker
    from refchecker.core.bulk_pipeline import _print_bulk_reference_block

    monkeypatch.setattr(
        "backend.refchecker_wrapper.extract_pdf_references_with_grobid_fallback",
        _raise_grobid_unavailable,
    )
    bibliography = (
        "[1] von Delft, S.,Yang Zhao, Y., (2021). Business models in process "
        "industries: Emerging trends and future research, Technovation, Vol 105, "
        "https://doi.org/10.1016/j.technovation.2020.102195\n"
        '[2] A. Other, "Another paper," Journal of Tests, 2020.'
    )
    cli = ArxivReferenceChecker(llm_config={"disabled": True}, cache_dir=str(tmp_path / "cli"))
    bulk = ArxivReferenceChecker(llm_config={"disabled": True}, cache_dir=str(tmp_path / "bulk"))
    webui = ProgressRefChecker.__new__(ProgressRefChecker)
    webui.check_id = None
    webui.llm = None
    webui.extraction_mode = "cascade"
    webui.emit_progress = AsyncMock()

    cli_refs = cli.parse_references(bibliography)
    bulk_refs = parse_references_bulk(bulk, bibliography, BulkLLMExtractionBatcher(enabled=False))
    web_refs, _ = asyncio.run(
        webui._extract_references_from_pdf(
            "unused.pdf", bibliography, bibliography_text=bibliography
        )
    )

    assert cli_refs == bulk_refs == web_refs
    assert cli_refs[0]["authors"] == ["URL Reference"]
    assert cli_refs[0]["source_authors"] == ["von Delft, S.", "Yang Zhao, Y."]
    assert cli_refs[0]["title"] == "Business models in process industries: Emerging trends and future research"
    assert cli_refs[0]["venue"] == "Technovation"
    assert "authors" not in cli_refs[0].get("field_extraction_status", {})

    projected = project_verification_result(cli_refs[0], None, [], None, enrich_enabled=False)
    assert projected["authors"] == ["von Delft, S.", "Yang Zhao, Y."]
    cli._print_reference_header(cli_refs[0], 0, 2)
    assert "von Delft" in capsys.readouterr().out
    _print_bulk_reference_block({"original_reference": cli_refs[0]}, 1, 2)
    assert "von Delft" in capsys.readouterr().out
    verifier = EnhancedHybridReferenceChecker.__new__(EnhancedHybridReferenceChecker)
    assert verifier._verify_reference_core(cli_refs[0]) == (None, [], cli_refs[0]["url"])


def test_colon_website_fields_match_across_paths(monkeypatch, tmp_path):
    from backend.reference_result import project_verification_result

    monkeypatch.setattr(
        "backend.refchecker_wrapper.extract_pdf_references_with_grobid_fallback",
        _raise_grobid_unavailable,
    )
    bibliography = (
        "[1] K. Nguyen, M. Borrego: Instructor strategies to aid implementation of active "
        "learning: a systematic literature review, Springer Nature https://example.com/, 2021\n"
        '[2] A. Other, "Another paper," Journal of Tests, 2020.'
    )
    cli = ArxivReferenceChecker(llm_config={"disabled": True}, cache_dir=str(tmp_path / "cli"))
    bulk = ArxivReferenceChecker(llm_config={"disabled": True}, cache_dir=str(tmp_path / "bulk"))
    webui = ProgressRefChecker.__new__(ProgressRefChecker)
    webui.check_id = None
    webui.llm = None
    webui.extraction_mode = "cascade"
    webui.emit_progress = AsyncMock()

    cli_refs = cli.parse_references(bibliography)
    bulk_refs = parse_references_bulk(bulk, bibliography, BulkLLMExtractionBatcher(enabled=False))
    web_refs, _ = asyncio.run(
        webui._extract_references_from_pdf(
            "unused.pdf", bibliography, bibliography_text=bibliography
        )
    )
    assert cli_refs == bulk_refs == web_refs
    assert cli_refs[0]["authors"] == ["URL Reference"]
    assert cli_refs[0]["source_authors"] == ["K. Nguyen", "M. Borrego"]
    assert cli_refs[0]["title"] == (
        "Instructor strategies to aid implementation of active learning: a systematic literature review"
    )
    assert cli_refs[0]["venue"] == "Springer Nature"
    assert project_verification_result(cli_refs[0], None, [], None, enrich_enabled=False)["authors"] == (
        ["K. Nguyen", "M. Borrego"]
    )


def test_source_confirmed_missing_titles_match_across_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "backend.refchecker_wrapper.extract_pdf_references_with_grobid_fallback",
        _raise_grobid_unavailable,
    )
    bibliography = (
        "[1] United Nations - World Population Prospects; "
        "https://population.un.org/wpp/\n"
        "[2] Google, Google Colaboratory. [Online]. "
        "Available: https://colab.google/\n"
        "[3] Microsoft. Visual Studio Code. Logiciel. Redmond, WA.\n"
        "[4] R. Mendoza-Gonzalez, User-Centered Design Strategies for Massive "
        "Open Online Courses (MOOCs), IGI Global, 2016. ISBN: 978-1-4666-9743-0.\n"
        "[5] T. Abcouwer, E. Takács, T. Schilstra and O. Banga, The Me, We, All "
        "approach: Circular resilience, A.A.A. & O., 2022.\n"
        "[6] S. Elio, J. Herranz, G. Carro Fernandez, A. Contreras, E. Camacho, "
        "F. Loro, and M. Castro, From a Hands-on Chemistry Lab to a Remote Chemistry "
        "Lab: Challenges and Constrains, 01 2018, pp. 125-131.\n"
        "[7] World Economic Forum, The Gender Gap in Science and Technology, in "
        "Numbers, Geneva, Switzerland, 2021.\n"
        "[8] Investing in Climate for Growth and Development. OECD Publishing, "
        "2025. doi: 10.1787/16b7cbc7-en.\n"
        "[9] L. S. Vygotsky, Zone of Proximal Development. Online: Research-\n"
        "Gate.\n"
        "[10] M. Apiola, S. L ́opez-Pernas, and M. Saqr, Past, Present and "
        "Future of Computing Education Research: A Global Perspective.\n"
        "Springer\nNature, 2023.\n"
        "[11] Su, F. E., Mathematics for Human Flourishing, Yale University "
        "Press,\n2020.\n"
        "[12] Fatma Sasmaz Oren. Self, peer and teacher assessments: What is "
        "the level of relationship between them? European Journal of Education "
        "Studies, 2018.\n"
        "[13] I. Casebourne, S. Shi, M. Hogan, et al. Using AI to Support "
        "Education for\nCollective Intelligence. Int J Artif Intell Educ "
        "35, 1597-1629 2025.\n"
        "[14] International Energy Agency, CO2 Emissions from Fuel Combustion\n"
        "2023, IEA Publications, Paris, France, 2023.\n"
        "[15] European Commission, Circular Economy Action Plan, COM 2020/98\n"
        "final.\n"
        '[16] N. McDonald, "Generative artificial intelligence in higher '
        'education," Computers in Human Behavior: Artificial Humans, 3, 2025.'
    )
    cli = ArxivReferenceChecker(
        llm_config={"disabled": True}, cache_dir=str(tmp_path / "cli")
    )
    bulk = ArxivReferenceChecker(
        llm_config={"disabled": True}, cache_dir=str(tmp_path / "bulk")
    )
    webui = ProgressRefChecker.__new__(ProgressRefChecker)
    webui.check_id = None
    webui.llm = None
    webui.extraction_mode = "cascade"
    webui.emit_progress = AsyncMock()

    cli_refs = cli.parse_references(bibliography)
    bulk_refs = parse_references_bulk(
        bulk, bibliography, BulkLLMExtractionBatcher(enabled=False)
    )
    web_refs, _ = asyncio.run(
        webui._extract_references_from_pdf(
            "unused.pdf", bibliography, bibliography_text=bibliography
        )
    )

    assert cli_refs == bulk_refs == web_refs
    assert [reference["title"] for reference in cli_refs] == [
        "World Population Prospects",
        "Google Colaboratory",
        "Visual Studio Code",
        "User-Centered Design Strategies for Massive Open Online Courses (MOOCs)",
        "The Me, We, All approach: Circular resilience",
        "From a Hands-on Chemistry Lab to a Remote Chemistry Lab: Challenges and Constrains",
        "The Gender Gap in Science and Technology, in Numbers",
        "Investing in Climate for Growth and Development",
        "Zone of Proximal Development",
        "Past, Present and Future of Computing Education Research: A Global Perspective",
        "Mathematics for Human Flourishing",
        "Self, peer and teacher assessments: What is the level of relationship between them?",
        "Using AI to Support Education for Collective Intelligence",
        "CO2 Emissions from Fuel Combustion 2023",
        "Circular Economy Action Plan",
        "Generative artificial intelligence in higher education",
    ]
    assert cli_refs[10]["authors"] == ["Su, F. E."]
    assert cli_refs[11]["venue"] == "European Journal of Education Studies"
    assert cli_refs[12]["venue"] == "Int J Artif Intell Educ"
    assert cli_refs[13]["venue"] == "IEA Publications"
    assert cli_refs[14].get("venue") in (None, "")
    assert cli_refs[15]["venue"] == "Computers in Human Behavior: Artificial Humans"


def test_source_absent_fields_match_across_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "backend.refchecker_wrapper.extract_pdf_references_with_grobid_fallback",
        _raise_grobid_unavailable,
    )
    bibliography = (
        "[1] https://example.edu/report.pdf\n"
        "[2] ICPC, 2023. http://icpc.baylor.edu/\n"
        "[3] A New Biology for the 21st Century. 2009.\n"
        "[4] Investing in Climate for Growth and Development. "
        "OECD Publishing, 2025. doi: 10.1787/16b7cbc7-en.\n"
        '[5] K. Simonyan and A. Zisserman, "Very Deep Convolutional Networks '
        'for Large-Scale Image Recognition," 2014, arXiv:1409.1556. '
        "https://arxiv.org/abs/1409.1556\n"
        '[6] Delft University of Technology, "Minor Robotics," '
        "https://www.tudelft.nl/robotics, 2025, accessed: Nov. 6, 2025.\n"
        '[7] K-12 Computer Science Framework Steering Committee, '
        '"K-12 Computer Science Framework," 2016. [Online]. Available: '
        "http://www.k12cs.org"
    )
    cli = ArxivReferenceChecker(
        llm_config={"disabled": True}, cache_dir=str(tmp_path / "cli")
    )
    bulk = ArxivReferenceChecker(
        llm_config={"disabled": True}, cache_dir=str(tmp_path / "bulk")
    )
    webui = ProgressRefChecker.__new__(ProgressRefChecker)
    webui.check_id = None
    webui.llm = None
    webui.extraction_mode = "cascade"
    webui.emit_progress = AsyncMock()

    cli_refs = cli.parse_references(bibliography)
    bulk_refs = parse_references_bulk(
        bulk, bibliography, BulkLLMExtractionBatcher(enabled=False)
    )
    web_refs, _ = asyncio.run(
        webui._extract_references_from_pdf(
            "unused.pdf", bibliography, bibliography_text=bibliography
        )
    )

    assert cli_refs == bulk_refs == web_refs
    assert [ref["title"] for ref in cli_refs] == [
        "",
        "",
        "A New Biology for the 21st Century",
        "Investing in Climate for Growth and Development",
        "Very Deep Convolutional Networks for Large-Scale Image Recognition",
        "Minor Robotics",
        "K-12 Computer Science Framework",
    ]
    assert [ref["authors"] for ref in cli_refs] == [
        [],
        ["ICPC"],
        [],
        [],
        ["K. Simonyan", "A. Zisserman"],
        ["Delft University of Technology"],
        ["K-12 Computer Science Framework Steering Committee"],
    ]
    assert [ref["venue"] for ref in cli_refs] == [
        "",
        "",
        "",
        "OECD Publishing",
        "",
        "",
        "",
    ]


def test_missing_field_status_matches_across_paths_and_cli_displays(monkeypatch, tmp_path, capsys):
    from backend.reference_result import project_verification_result
    from refchecker.core.bulk_pipeline import _print_bulk_reference_block

    monkeypatch.setattr(
        "backend.refchecker_wrapper.extract_pdf_references_with_grobid_fallback",
        _raise_grobid_unavailable,
    )
    bibliography = (
        '[1] T. Collins, R. Getz, 2018.\n'
        '[2] A. Jones, Conference on Testing, 2021.'
    )
    cli = ArxivReferenceChecker(
        llm_config={"disabled": True}, cache_dir=str(tmp_path / "cli")
    )
    bulk = ArxivReferenceChecker(
        llm_config={"disabled": True}, cache_dir=str(tmp_path / "bulk")
    )
    webui = ProgressRefChecker.__new__(ProgressRefChecker)
    webui.check_id = None
    webui.llm = None
    webui.extraction_mode = "cascade"
    webui.emit_progress = AsyncMock()

    cli_refs = cli.parse_references(bibliography)
    bulk_refs = parse_references_bulk(bulk, bibliography, BulkLLMExtractionBatcher(enabled=False))
    web_refs, _ = asyncio.run(
        webui._extract_references_from_pdf(
            "unused.pdf", bibliography, bibliography_text=bibliography
        )
    )
    assert cli_refs == bulk_refs == web_refs
    assert cli_refs[0]["field_extraction_status"] == {"title": "absent", "venue": "absent"}
    assert cli_refs[1]["field_extraction_status"]["title"] == "uncertain"

    for ref in cli_refs:
        projected = project_verification_result(ref, None, [], None, enrich_enabled=False)
        cli._print_reference_header(ref, 0, 2)
        cli_output = capsys.readouterr().out
        _print_bulk_reference_block({
            "ref_title": ref.get("title"), "original_reference": ref,
        }, 1, 2)
        bulk_output = capsys.readouterr().out
        for message in projected["extraction_field_messages"]:
            assert message in cli_output
            assert message in bulk_output
        assert ref["raw_text"] in cli_output
        assert ref["raw_text"] in bulk_output


def test_webui_no_bibliography_does_not_require_grobid(monkeypatch):
    monkeypatch.setattr(
        "backend.refchecker_wrapper.extract_pdf_references_with_grobid_fallback",
        _raise_grobid_unavailable,
    )
    webui = ProgressRefChecker.__new__(ProgressRefChecker)
    webui.check_id = None
    webui.llm = None
    webui.extraction_mode = "cascade"
    webui.emit_progress = AsyncMock()

    references, _ = asyncio.run(
        webui._extract_references_from_pdf("unused.pdf", "No bibliography here.")
    )

    assert references == []
