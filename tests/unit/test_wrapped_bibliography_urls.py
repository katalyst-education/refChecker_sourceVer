import pytest

from refchecker.core.refchecker import ArxivReferenceChecker
from refchecker.utils.url_utils import clean_url, join_wrapped_url_lines


def test_url_path_word_split_before_pdf_path():
    source = "Available: https://example.com/insights/doc\numents/report.pdf"
    assert join_wrapped_url_lines(source) == (
        "Available: https://example.com/insights/documents/report.pdf"
    )


@pytest.mark.parametrize(("source", "expected"), [
    ("http:// basenacionalcomum.mec.gov.br/",
     "http://basenacionalcomum.mec.gov.br/"),
    ("https:// openjfx.io/",
     "https://openjfx.io/"),
    ("https://\n www.taylorfrancis.com/books/9781315297293",
     "https://www.taylorfrancis.com/books/9781315297293"),
])
def test_url_with_whitespace_after_protocol_slashes(source, expected):
    assert join_wrapped_url_lines(source) == expected


def test_annotated_camel_case_url_wrap_preserves_source_url():
    source = (
        'https://www.scribd.com/document/568038123/CriticalThinkingProbl\n'
        'emSolving :contentReference[oaicite:1]{index=1}'
    )
    assert join_wrapped_url_lines(source) == (
        'https://www.scribd.com/document/568038123/CriticalThinkingProblemSolving '
        ':contentReference[oaicite:1]{index=1}'
    )


def test_url_wrap_does_not_consume_unannotated_camel_case_prose():
    source = 'https://example.com/document/Report\nAboutResults'
    assert join_wrapped_url_lines(source) == source


@pytest.mark.parametrize(("source", "expected"), [
    ('https://www.mathworks.com/products/quantum-computing.h\ntml',
     'https://www.mathworks.com/products/quantum-computing.html'),
    ('http://link.springer.com/10.105\n7/s41307-016-0034-4',
     'http://link.springer.com/10.1057/s41307-016-0034-4'),
    ('https://www.sciencedirect.com/science/article/pii/S1361372\n317300519',
     'https://www.sciencedirect.com/science/article/pii/S1361372317300519'),
    ('https://www.britishcouncil.org/sites/default/files/bc_environment_for_tn\n'
     'e_partnerships_in_pakistan.pdf',
     'https://www.britishcouncil.org/sites/default/files/'
     'bc_environment_for_tne_partnerships_in_pakistan.pdf'),
    ('https://www.frontiersin.org/journals/edu\ncation/articles/10.3389/feduc.2023.1320822',
     'https://www.frontiersin.org/journals/education/articles/10.3389/feduc.2023.1320822'),
    ('https://www.sciencedirect.com/science/articl\ne/pii/S1877042811028655',
     'https://www.sciencedirect.com/science/article/pii/S1877042811028655'),
    ('https://books.google.com.br/books?id=\nmToqEAAAQBAJ',
     'https://books.google.com.br/books?id=mToqEAAAQBAJ'),
    ('https://uhra.herts.ac.uk/902911.pdf?sequ\nence=1&isAllowed=y',
     'https://uhra.herts.ac.uk/902911.pdf?sequence=1&isAllowed=y'),
    ('https://linkinghub.elsevier.com/retrieve/pii/S088303552300\n1222',
     'https://linkinghub.elsevier.com/retrieve/pii/S0883035523001222'),
    ('https://ieeexplore.ieee.org/document/8\n363425/',
     'https://ieeexplore.ieee.org/document/8363425/'),
    ('https://link.aps.org/doi/10.1103\n/PhysRevPhysEducRes.19.010137',
     'https://link.aps.org/doi/10.1103/PhysRevPhysEducRes.19.010137'),
    ('https://link.aps.org/doi/10.1103/PhysRevPh\nysEducRes.16.020131',
     'https://link.aps.org/doi/10.1103/PhysRevPhysEducRes.16.020131'),
    ('https://doi.org/10.1287/ijoc\n.2.1.4',
     'https://doi.org/10.1287/ijoc.2.1.4'),
    ('https://www.frontiersin.org/journals/education/articles/10.3389/feduc.20\n'
     '23.1153647/full',
     'https://www.frontiersin.org/journals/education/articles/10.3389/feduc.2023.1153647/full'),
    ('https://www.tandfonline.com/doi/full/10.1080/030\n43797.2016.1232372',
     'https://www.tandfonline.com/doi/full/10.1080/03043797.2016.1232372'),
    ('https://www.annualreviews.org/doi/10.1146/annure\nv.psych.52.1.1',
     'https://www.annualreviews.org/doi/10.1146/annurev.psych.52.1.1'),
    ('https://www.taylorfrancis.com/books/978100\n3271789',
     'https://www.taylorfrancis.com/books/9781003271789'),
])
def test_source_url_components_split_across_lines(source, expected):
    assert join_wrapped_url_lines(source) == expected


@pytest.mark.parametrize("source", [
    'https://example.com/a.h\nThe next sentence.',
    'https://example.com/page?id=\nTheNextSentence',
    'https://example.com/report\nordinary prose continues.',
    'https://example.com/path?query\nNext sentence.',
    'https://example.com/article/pii/S123456\n12345',
    'https://example.com/10.1234/identifier\n2024',
    'https://example.com/document/8\n363425/',
    'https://example.com/books/978100\n3271788',
])
def test_url_component_repair_does_not_append_prose(source):
    assert join_wrapped_url_lines(source) == source


@pytest.mark.parametrize(("title", "wrapped", "complete"), [
    (
        "Beyond blended: rethinking curriculum and learning design",
        "https://www.jisc.ac.uk/guides/beyond-blended-rethinking-curriculum-a\n"
        "nd-learning-design",
        "https://www.jisc.ac.uk/guides/beyond-blended-rethinking-curriculum-and-learning-design",
    ),
    (
        "Beyond blended: Researching institutional approaches to blended learning in higher education",
        "https://www.jisc.ac.uk/innovation/projects/beyond-blended-r\n"
        "esearching-institutional-approaches-to-blended-learning-in-higher-edu\n"
        "cation",
        "https://www.jisc.ac.uk/innovation/projects/beyond-blended-researching-"
        "institutional-approaches-to-blended-learning-in-higher-education",
    ),
])
def test_url_path_split_inside_words_matches_source_title(title, wrapped, complete):
    source = f'[1] Jisc, "{title}," 2024. [Online]. Available: {wrapped}'
    assert join_wrapped_url_lines(source) == source.replace(wrapped, complete)


def test_title_slug_repair_does_not_append_unrelated_prose():
    source = '[1] Jisc, "An unrelated title," 2024. Available: https://example.com/report\nordinary prose.'
    assert join_wrapped_url_lines(source) == source


def test_title_slug_repair_does_not_use_an_unrelated_unnumbered_title():
    source = (
        '"A longer matching title" was mentioned elsewhere.\n'
        'https://example.com/a-longer-matching-tit\nle'
    )
    assert join_wrapped_url_lines(source) == source


def test_url_filename_split_before_hyphenated_pdf_suffix():
    source = (
        "Available: https://example.com/files/Computati\n"
        "onal-Thinking-Rubric-2ktkkgv.pdf."
    )
    assert join_wrapped_url_lines(source) == (
        "Available: https://example.com/files/"
        "Computational-Thinking-Rubric-2ktkkgv.pdf."
    )


def test_url_hash_split_before_abstract_filename():
    source = (
        "Available: https://papers.nips.cc/paper_files/paper/2017/hash/"
        "3f5ee243547dee91\nfbd053c1c4a845aa-Abstract.html"
    )
    expected = source.replace("\n", "")
    assert join_wrapped_url_lines(source) == expected

    unrelated = "See https://example.com/hash/3f5ee243547dee91\nfbd053c1-Abstract.html"
    assert join_wrapped_url_lines(unrelated) == unrelated

    checker = ArxivReferenceChecker(llm_config={"disabled": True})
    refs = checker.parse_references(_numbered_bibliography(
        '[2] A. Author, "Attention is All you Need," in Advances in Neural '
        'Information Processing Systems, 2017. [Online]. ' + source
    ))
    assert refs[1]["url"] == expected.removeprefix("Available: ")


def test_url_filename_wrap_after_plus_preserves_source_underscores():
    source = (
        "Available: https://www.mim.gov.it/documents/20182/0/"
        "MIM_Linee+guida+IA+\nnella+Scuola_09_08_2025-signed.pdf, "
        "Accessed on: Nov. 5, 2025."
    )
    assert join_wrapped_url_lines(source) == (
        "Available: https://www.mim.gov.it/documents/20182/0/"
        "MIM_Linee+guida+IA+nella+Scuola_09_08_2025-signed.pdf, "
        "Accessed on: Nov. 5, 2025."
    )
    prose = "See https://example.com/a+\nThe next sentence."
    assert join_wrapped_url_lines(prose) == prose


def test_spaced_path_slash_does_not_invent_an_underscore():
    source = (
        "https://gitlab.cc-asp.fraunhofer.de/\n"
        "fraunhofer_iao_qc / programming_qc, Accessed: 2025-01-02"
    )
    assert join_wrapped_url_lines(source) == (
        "https://gitlab.cc-asp.fraunhofer.de/"
        "fraunhofer_iao_qc/programming_qc, Accessed: 2025-01-02"
    )


LASEK_ENTRY = (
    "[2] J. Lasek, Z. Szl\u00e1vik, and S. Bhulai, \u201cThe Predictive Power of "
    "Ranking Systems in\nAssociation Football,\u201d International Journal of "
    "Applied Pattern Recognition, vol. 1,\nno. 1, p. 27, 2013. [Online]. "
    "Available: http://www.inderscience.com/link.php?id=\n52339"
)

CEDTECH_ENTRY = (
    '[2] N. Kara and N. Sevim, "Adaptive Learning Systems: Beyond Teaching '
    'Machines," Contemporary Educational Technology, vol. 4, no. 2, Jun. '
    '2013. [Online]. Available: https://www.cedtech.net/article/\n'
    'adaptive-learning-systems-beyond-teaching-machines-6095'
)


def _numbered_bibliography(entry):
    return (
        '[1] A. Author, "Earlier work," Journal of Tests, 2012.\n'
        f"{entry}\n"
        '[3] B. Other, "Later work," Journal of Tests, 2014.'
    )


def test_join_wrapped_url_lines_repairs_query_value_wrap():
    text = "Available: http://www.inderscience.com/link.php?id=\n52339"
    assert join_wrapped_url_lines(text) == (
        "Available: http://www.inderscience.com/link.php?id=52339"
    )


def test_join_wrapped_url_lines_preserves_printed_hyphen_and_multiple_wraps():
    text = (
        "URL https://methods.\nsagepub.com/book/mono/intro-\n"
        "chpt/monotone-homogeneity-model."
    )
    assert join_wrapped_url_lines(text) == (
        "URL https://methods.sagepub.com/book/mono/intro-"
        "chpt/monotone-homogeneity-model."
    )


def test_join_wrapped_url_lines_does_not_merge_next_entry_or_prose():
    complete = "See https://example.com/page.\nSmith"
    assert join_wrapped_url_lines(complete) == complete

    next_entry = "http://example.com/a?id=\n[3] B. Other, Title, 2014."
    assert join_wrapped_url_lines(next_entry) == next_entry

    text_after = "http://example.com/a?id=\nNext sentence follows here."
    assert join_wrapped_url_lines(text_after) == text_after


@pytest.mark.parametrize(
    ("wrapped", "expected"),
    [
        ("https://betaflight.co\nm/docs/wiki,", "https://betaflight.com/docs/wiki,"),
        (
            "https://example.com/product/first-tes\nt-prototype/,",
            "https://example.com/product/first-test-prototype/,",
        ),
        (
            "https://example.com/product/cy8cp\nroto-062-4343w,",
            "https://example.com/product/cy8cproto-062-4343w,",
        ),
    ],
)
def test_url_line_wrap_before_access_date(wrapped, expected):
    source = f'{wrapped} accessed: 2026-01-15.'
    assert join_wrapped_url_lines(source) == f'{expected} accessed: 2026-01-15.'

    refs = ArxivReferenceChecker(llm_config={"disabled": True}).parse_references(
        _numbered_bibliography(f'[2] A. Author, "Work," {source}')
    )
    assert refs[1]["url"] == expected.rstrip(",")


def test_url_access_date_wrap_does_not_consume_plain_prose():
    source = "https://example.com/page\nSome words, accessed: 2026-01-15."
    assert join_wrapped_url_lines(source) == source
    source = "https://example.com/page.\nOther-page, accessed: 2026-01-15."
    assert join_wrapped_url_lines(source) == source
    source = "https://example.com,\n2025, accessed: 2026-01-15."
    assert join_wrapped_url_lines(source) == source


def test_pdf_url_hyphen_and_access_date_are_preserved_separately():
    from refchecker.services.pdf_pipeline.text_extractors.paper_helpers import (
        paper_clean_text_preserve_lines,
    )

    text = (
        "Available: https://example.com/demand-\n"
        "for-programmers/ (accessed Mar. 17, 2025)."
    )
    cleaned = paper_clean_text_preserve_lines(text)
    assert join_wrapped_url_lines(cleaned) == (
        "Available: https://example.com/demand-for-programmers/"
        " (accessed Mar. 17, 2025)."
    )
    assert clean_url("https://example.com/demand-for-programmers/(accessed") == (
        "https://example.com/demand-for-programmers/"
    )


def test_wrapped_doi_is_not_truncated():
    checker = ArxivReferenceChecker(llm_config={"disabled": True})
    bibliography = _numbered_bibliography(
        '[2] A. Smith, "A useful paper," Journal of Tests, vol. 1, 2024, '
        'doi: 10.1007/s43621-024-\n00677-6.'
    )

    refs = checker.parse_references(bibliography)

    assert refs[1]["doi"] == "10.1007/s43621-024-00677-6"


def test_biblatex_preserves_printed_hyphen_in_wrapped_doi():
    from refchecker.utils.biblatex_parser import parse_biblatex_entry_content

    ref = parse_biblatex_entry_content(
        "1",
        'A. Smith, "Learning methods," Journal of Testing, 2020, '
        'doi: 10.1007/978-\n3-662-49080-8.',
    )

    assert ref["doi"] == "10.1007/978-3-662-49080-8"
    assert ref["url"] == "https://doi.org/10.1007/978-3-662-49080-8"


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("10.48550/arXiv.2506.\n08872.", "10.48550/arXiv.2506.08872."),
        ("10.1016/j.jadr.\n2023.100658.", "10.1016/j.jadr.2023.100658."),
        ("10.1016/j.c\nompag.2020.105694.", "10.1016/j.compag.2020.105694."),
        ("10.1007/s11119-022-09\n872-9.", "10.1007/s11119-022-09872-9."),
        ("10.1016/j.compag.2022.10\n7521.", "10.1016/j.compag.2022.107521."),
    ],
)
def test_join_wrapped_doi_fragments_from_pdf_lines(source, expected):
    from refchecker.utils.doi_utils import join_wrapped_doi_lines

    assert join_wrapped_doi_lines(source) == expected


def test_join_wrapped_doi_does_not_consume_following_prose():
    from refchecker.utils.doi_utils import join_wrapped_doi_lines

    source = "doi: 10.1234/complete.\nAvailable online in 2024."
    assert join_wrapped_doi_lines(source) == source
    source = "doi: 10.1234/complete.\n2024."
    assert join_wrapped_doi_lines(source) == source
    source = "doi: 10.1234/complete.\n123."
    assert join_wrapped_doi_lines(source) == source
    source = "doi: 10.1234/complete.\n12345. Additional text."
    assert join_wrapped_doi_lines(source) == source


def test_terminal_numeric_suffix_completes_doi_and_resolver_url():
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": '[34] D. A. Long, "A study," Journal of Community Psychology, '
                    '2003. DOI: 10.1002/jcop.\n10046.',
        "authors": ["D. A. Long"], "title": "A study",
        "doi": "10.1002/jcop", "url": "https://doi.org/10.1002/jcop",
    })
    assert reference["doi"] == "10.1002/jcop.10046"
    assert reference["url"] == "https://doi.org/10.1002/jcop.10046"


def test_doi_separated_from_following_author_initial():
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": '[3] A. Author, "A study," Journal of Tests, 2019, '
                    'doi: 10.1016/j.compedu.2019.103612.K. Elissa, '
                    '"Title of paper if known," unpublished.',
        "authors": ["A. Author"], "title": "A study",
        "doi": "10.1016/j.compedu.2019.103612.K",
        "url": "https://doi.org/10.1016/j.compedu.2019.103612.k",
    })
    assert reference["doi"] == "10.1016/j.compedu.2019.103612"
    assert reference["url"] == "https://doi.org/10.1016/j.compedu.2019.103612"


def test_doi_following_author_repair_preserves_unrelated_doi():
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": '[3] A. Author, "A study," doi: 10.1234/example.K. Elissa, "Next work".',
        "authors": ["A. Author"], "title": "A study",
        "doi": "10.1234/different", "url": "https://doi.org/10.1234/different",
    })
    assert reference["doi"] == "10.1234/different"
    assert reference["url"] == "https://doi.org/10.1234/different"


def test_numbered_citation_recovers_wrapped_doi_numeric_suffix():
    checker = ArxivReferenceChecker(llm_config={"disabled": True})
    bibliography = _numbered_bibliography(
        '[2] A. Smith, "A useful paper," Journal of Tests, 2024, '
        'doi: 10.1016/j.compag.2022.10\n7521.'
    )

    refs = checker.parse_references(bibliography)

    assert refs[1]["doi"] == "10.1016/j.compag.2022.107521"
    assert refs[1]["url"] == "https://doi.org/10.1016/j.compag.2022.107521"


def test_join_wrapped_url_with_newline_normalized_to_space():
    text = (
        "[Online]. Available: https://www.cedtech.net/article/ "
        "adaptive-learning-systems-beyond-teaching-machines-6095"
    )
    assert join_wrapped_url_lines(text) == (
        "[Online]. Available: https://www.cedtech.net/article/"
        "adaptive-learning-systems-beyond-teaching-machines-6095"
    )


def test_numbered_pdf_reference_keeps_complete_wrapped_url():
    checker = ArxivReferenceChecker()

    references = checker._parse_references_regex(_numbered_bibliography(LASEK_ENTRY))

    urls = [reference.get("url") for reference in references]
    assert "http://www.inderscience.com/link.php?id=52339" in urls
    lasek = next(r for r in references if "Lasek" in r.get("raw_text", ""))
    assert lasek["url"] == "http://www.inderscience.com/link.php?id=52339"
    assert "Available: 52339" not in lasek["title"]
    assert len(references) == 3


def test_parse_references_cascade_keeps_complete_wrapped_url_offline():
    checker = ArxivReferenceChecker()
    checker.extraction_mode = "cascade"

    references = checker.parse_references(_numbered_bibliography(LASEK_ENTRY))

    urls = [reference.get("url") for reference in references]
    assert "http://www.inderscience.com/link.php?id=52339" in urls
    assert len(references) == 3


def test_screenshot_shaped_cedtech_url_is_complete_in_shared_parser():
    checker = ArxivReferenceChecker()
    checker.extraction_mode = "cascade"
    bibliography = _numbered_bibliography(CEDTECH_ENTRY)

    references = checker.parse_references(bibliography)

    kara = next(reference for reference in references if "Kara" in reference.get("raw_text", ""))
    assert kara["url"] == (
        "https://www.cedtech.net/article/"
        "adaptive-learning-systems-beyond-teaching-machines-6095"
    )
    assert "article/\nadaptive-learning" in bibliography


def test_screenshot_shaped_cedtech_url_is_complete_after_line_whitespace_normalization():
    checker = ArxivReferenceChecker()
    checker.extraction_mode = "cascade"
    bibliography = _numbered_bibliography(CEDTECH_ENTRY).replace(
        "article/\nadaptive-learning",
        "article/ adaptive-learning",
    )

    references = checker.parse_references(bibliography)

    kara = next(reference for reference in references if "Kara" in reference.get("raw_text", ""))
    assert kara["url"] == (
        "https://www.cedtech.net/article/"
        "adaptive-learning-systems-beyond-teaching-machines-6095"
    )
def test_wrapped_tu_darmstadt_hostname_and_escaped_underscores_are_repaired():
    text = (
        "https://ww\n"
        "w.tu-darmstadt.de/universitaet/aktuelles\\_meldungen/"
        "einzelansicht\\_525\n"
        "888.de.jsp"
    )
    assert join_wrapped_url_lines(text) == (
        "https://www.tu-darmstadt.de/universitaet/aktuelles_meldungen/"
        "einzelansicht_525888.de.jsp"
    )


def test_tu_darmstadt_url_with_pdf_extracted_spaces_is_reconstructed():
    text = (
        "https://www.tu-darmstadt.de/universitaet/aktuelles "
        "meldungen/einzelansicht 525\n888.de.jsp, Sept. 2024"
    )
    assert join_wrapped_url_lines(text) == (
        "https://www.tu-darmstadt.de/universitaet/aktuelles_meldungen/"
        "einzelansicht_525888.de.jsp, Sept. 2024"
    )


def test_tu_darmstadt_pdf_url_survives_numbered_reference_parsing():
    bibliography = (
        '[1] A. Author, "First work," Journal, 2022.\n'
        '[2] B. Other, "University news," Sept. 2024. '
        "https://www.tu-darmstadt.de/universitaet/aktuelles "
        "meldungen/einzelansicht 525\n888.de.jsp\n"
        '[3] C. Researcher, "Third work," Journal, 2025.'
    )
    checker = ArxivReferenceChecker()

    references = checker.parse_references(bibliography)

    darmstadt = next(
        reference for reference in references
        if reference.get("title") == "University news"
    )
    assert darmstadt["url"] == (
        "https://www.tu-darmstadt.de/universitaet/aktuelles_meldungen/"
        "einzelansicht_525888.de.jsp"
    )


def test_wrapped_jstor_numeric_suffix_is_repaired():
    text = "https://www.jstor.org/stable/jeductechsoci.8.3.\n26"
    assert join_wrapped_url_lines(text) == (
        "https://www.jstor.org/stable/jeductechsoci.8.3.26"
    )


def test_wrapped_cedtech_path_is_repaired_after_space_normalization():
    text = (
        "https://www.cedtech.net/article/ "
        "adaptive-learning-systems-beyond-teaching-machines-6095"
    )
    assert join_wrapped_url_lines(text) == (
        "https://www.cedtech.net/article/"
        "adaptive-learning-systems-beyond-teaching-machines-6095"
    )


def test_wrapped_query_value_and_following_parameter_are_repaired():
    text = "https://example.org/article?id=\n12345&lang=en"
    assert join_wrapped_url_lines(text) == (
        "https://example.org/article?id=12345&lang=en"
    )


@pytest.mark.parametrize(
    ("wrapped_url", "expected_url"),
    [
        (
            "https://linkinghub.elsevier.com/retrieve/pii/\n"
            "S187704281501486X",
            "https://linkinghub.elsevier.com/retrieve/pii/S187704281501486X",
        ),
        (
            "https://www.tandfonline.com/doi/abs/10.\n"
            "1080/00461520.2011.611369",
            "https://www.tandfonline.com/doi/abs/10.1080/00461520.2011.611369",
        ),
        (
            "https://journals.sagepub.com/doi/10.3102/\n"
            "0013189X013006004",
            "https://journals.sagepub.com/doi/10.3102/0013189X013006004",
        ),
        (
            "http://journal.frontiersin.org/article/10.3389/fpsyg.\n"
            "2017.01739/full",
            "http://journal.frontiersin.org/article/10.3389/fpsyg.2017.01739/full",
        ),
        (
            "https://www.\nmicrosoft.com/en-us/research/page",
            "https://www.microsoft.com/en-us/research/page",
        ),
        (
            "https://www.web.cmu.\nedu/project/resource",
            "https://www.web.cmu.edu/project/resource",
        ),
        (
            "https:\n//dl.acm.org/doi/10.1145/3544549.3585758",
            "https://dl.acm.org/doi/10.1145/3544549.3585758",
        ),
        (
            "https://linkinghub.elsevier.com/retrieve/pii/ "
            "S2666920X22000595",
            "https://linkinghub.elsevier.com/retrieve/pii/S2666920X22000595",
        ),
    ],
)
def test_reconstructs_url_fragments_seen_in_glicko_pdf(wrapped_url, expected_url):
    assert join_wrapped_url_lines(
        "[Online]. Available: " + wrapped_url
    ) == "[Online]. Available: " + expected_url


def test_all_supplied_wrapped_urls_are_extracted_from_reference_text():
    wrapped_urls = [
        (
            "https://ww\n"
            "w.tu-darmstadt.de/universitaet/aktuelles\\_meldungen/"
            "einzelansicht\\_525\n"
            "888.de.jsp",
            "https://www.tu-darmstadt.de/universitaet/aktuelles_meldungen/"
            "einzelansicht_525888.de.jsp",
        ),
        (
            "https://www.jstor.org/stable/jeductechsoci.8.3.\n26",
            "https://www.jstor.org/stable/jeductechsoci.8.3.26",
        ),
        (
            "https://www.cedtech.net/article/\n"
            "adaptive-learning-systems-beyond-teaching-machines-6095",
            "https://www.cedtech.net/article/"
            "adaptive-learning-systems-beyond-teaching-machines-6095",
        ),
        (
            "http://www.inderscience.com/link.php?id=\n52339",
            "http://www.inderscience.com/link.php?id=52339",
        ),
    ]
    for index, (wrapped_url, expected_url) in enumerate(wrapped_urls):
        entry = (
            f'[1] A. Author, "Title {index}," Journal, 2020. {wrapped_url}'
        )
        references = ArxivReferenceChecker()._parse_references_regex(entry)
        assert references[0]["url"] == expected_url


def test_wrapped_url_repair_stops_at_access_metadata_and_strips_final_period():
    text = "https://example.com.\naccessed: Nov. 07, 2025"
    assert join_wrapped_url_lines(text) == text
    assert clean_url(text.splitlines()[0]) == "https://example.com"

    year_after_url = "https://example.com/article.\n2025"
    assert join_wrapped_url_lines(year_after_url) == year_after_url
    checker = ArxivReferenceChecker()
    references = checker._parse_references_regex(
        '[1] A. Author, "A title," Journal, 2020. ' + text
    )
    assert references[0]["url"] == "https://example.com"


def test_wrapped_url_repair_does_not_consume_next_reference_marker():
    text = "https://example.com/page [37] Smith, J..."
    assert join_wrapped_url_lines(text) == text
    checker = ArxivReferenceChecker()
    references = checker._parse_references_regex(
        '[1] A. Author, "A title," Journal, 2020. ' + text
    )
    assert references[0]["url"] == "https://example.com/page"


def test_wrapped_url_repair_does_not_join_ordinary_prose():
    text = "https://example.com/some-path\nand normal prose follows here"
    assert join_wrapped_url_lines(text) == text
    after_slash = "https://example.com/article/\nSmith et al. continue here"
    assert join_wrapped_url_lines(after_slash) == after_slash


def test_complete_doi_url_is_unchanged():
    text = "https://doi.org/10.1234/example.123"
    assert join_wrapped_url_lines(text) == text


def test_clean_url_preserves_balanced_parentheses():
    assert clean_url("https://example.org/wiki/Title_(example).") == (
        "https://example.org/wiki/Title_(example)"
    )


def test_two_references_with_wrapped_urls_remain_separate():
    bibliography = (
        '[1] A. Author, "First title," Journal, 2020. '
        "https://example.org/article?id=\n12345\n"
        '[2] B. Author, "Second title," Journal, 2021. '
        "https://example.net/item/456"
    )
    checker = ArxivReferenceChecker()
    references = checker._parse_references_regex(bibliography)
    assert len(references) == 2
    assert [reference["url"] for reference in references] == [
        "https://example.org/article?id=12345",
        "https://example.net/item/456",
    ]


def test_pdf_page_header_cleanup_preserves_jstor_numeric_url_suffix():
    bibliography = (
        '[1] S. Retalis, "Title," Journal, 2005. [Online]. Available: '
        "https://www.jstor.org/stable/jeductechsoci.8.3.\n"
        "26\n"
        '[2] N. Anindyaputri, "Next title," Journal, 2020.\n'
        '[3] C. Author, "Another title," Journal, 2021.'
    )
    cleaned = ArxivReferenceChecker._strip_pdf_page_headers_from_bibliography(
        bibliography
    )
    assert "8.3.\n26\n[2]" in cleaned
    references = ArxivReferenceChecker()._parse_references_regex(cleaned)
    assert references[0]["url"] == (
        "https://www.jstor.org/stable/jeductechsoci.8.3.26"
    )
    assert references[0]["raw_text"].endswith("8.3.\n26")


def test_page_label_after_complete_url_does_not_extend_url():
    bibliography = (
        '[1] A. Author, "First title," Journal, 2020. [Online]. Available: '
        "https://example.com/article\n"
        "90\n"
        '[2] B. Author, "Second title," Journal, 2021.\n'
        '[3] C. Author, "Third title," Journal, 2022.'
    )
    cleaned = ArxivReferenceChecker._strip_pdf_page_headers_from_bibliography(
        bibliography
    )
    assert "https://example.com/article\n90" not in cleaned


def test_period_wrapped_url_suffix_matches_reference_page_range():
    bibliography = (
        '[1] A. Author, "Previous work," Journal, 2004.\n'
        '[2] S. Retalis, "Adaptive Hypermedia," Journal, vol. 8, '
        'pp. 26-35, 2005. [Online]. Available: '
        "https://www.jstor.org/stable/jeductechsoci.8.3.\n"
        "26\n"
        '[3] N. Anindyaputri, "Next work," Journal, 2006.'
    )

    joined = join_wrapped_url_lines(bibliography)
    references = ArxivReferenceChecker().parse_references(bibliography)
    retalis = next(
        reference for reference in references
        if "Adaptive Hypermedia" in (reference.get("title") or "")
    )

    assert retalis["url"] == (
        "https://www.jstor.org/stable/jeductechsoci.8.3.26"
    )
    assert len(references) == 3
    assert "https://www.jstor.org/stable/jeductechsoci.8.3.26" in joined


def test_period_wrapped_url_rejects_mismatched_page_number_and_prose():
    unrelated_number = (
        "pp. 26-35, 2005. [Online]. Available: "
        "https://example.org/stable/item.8.3.\n"
        "27\n[37] Another reference."
    )
    prose = (
        "[Online]. Available: https://example.org/stable/item.8.3.\n"
        "The following numeric value is 26 words long."
    )
    next_reference = (
        "[Online]. Available: https://example.org/stable/item.8.3.\n"
        "[37] Another reference."
    )

    assert join_wrapped_url_lines(unrelated_number).startswith(
        "pp. 26-35, 2005. [Online]. Available: "
        "https://example.org/stable/item.8.3.\n27"
    )
    assert join_wrapped_url_lines(prose) == prose
    assert join_wrapped_url_lines(next_reference) == next_reference


def test_period_wrapped_url_suffix_matches_after_space_normalization():
    text = (
        "pp. 26-35, 2005. [Online]. Available: "
        "https://www.jstor.org/stable/jeductechsoci.8.3. 26\n[37] "
        "Another reference."
    )
    assert join_wrapped_url_lines(text) == (
        "pp. 26-35, 2005. [Online]. Available: "
        "https://www.jstor.org/stable/jeductechsoci.8.3.26\n[37] "
        "Another reference."
    )


@pytest.mark.parametrize(
    ("wrapped_url", "expected_url"),
    [
        (
            "http://www.tandfonline.com/doi/abs/10. "
            "1080/00461520.2011.611369",
            "http://www.tandfonline.com/doi/abs/10.1080/00461520.2011.611369",
        ),
        (
            "https://linkinghub.elsevier.com/retrieve/pii/ "
            "S187704281501486X",
            "https://linkinghub.elsevier.com/retrieve/pii/S187704281501486X",
        ),
        (
            "https://journals.sagepub.com/doi/10.3102/ "
            "0013189X013006004",
            "https://journals.sagepub.com/doi/10.3102/0013189X013006004",
        ),
        (
            "https://www.jstor.org/stable/jeductechsoci.8.3.\n26",
            "https://www.jstor.org/stable/jeductechsoci.8.3.26",
        ),
        (
            "https://www. microsoft.com/en-us/research/wp-content/uploads/"
            "2008/01/NIPS2007_0931.pdf",
            "https://www.microsoft.com/en-us/research/wp-content/uploads/"
            "2008/01/NIPS2007_0931.pdf",
        ),
        (
            "https://www.frontiersin.org/article/10.3389/fpsyg.\n"
            "2019.00620/full",
            "https://www.frontiersin.org/article/10.3389/fpsyg.2019.00620/full",
        ),
        (
            "https://linkinghub.elsevier.com/retrieve/pii/\n"
            "S2666920X22000595",
            "https://linkinghub.elsevier.com/retrieve/pii/S2666920X22000595",
        ),
        (
            "https://pslcdatashop.web.cmu. edu/KDDCup/",
            "https://pslcdatashop.web.cmu.edu/KDDCup/",
        ),
    ],
)
def test_exact_glicko_pdf_url_wrap_shapes_are_reconstructed(
    wrapped_url, expected_url
):
    bibliography = (
        '[1] A. Author, "Study," Journal, pp. 26-35, 2019. '
        f"[Online]. Available: {wrapped_url}\n"
        '[2] B. Other, "Next Work," Journal, 2020.'
    )

    references = ArxivReferenceChecker()._parse_references_regex(bibliography)

    assert len(references) == 2
    assert references[0]["url"] == expected_url
    assert references[1]["title"] == "Next Work"


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("https://example.org/article.Accessed:Feb.2,2026", "https://example.org/article"),
        ("https://example.org/article,accessed", "https://example.org/article"),
        ("https://example.org/article,2024,accessed:2025-01-20", "https://example.org/article"),
        ("https://example.org/article(Accessed:2026-02-01)", "https://example.org/article"),
        ("https://example.org/article[Accessed:12Aug2025]", "https://example.org/article"),
        ("https://example.org/article[Accessed:12Aug2025].", "https://example.org/article"),
        ("https://example.org/article.Accessedon27Sept2025", "https://example.org/article"),
        ("https://example.org/article,[Online;accessedAugust", "https://example.org/article"),
        ("https://example.org/accessed", "https://example.org/accessed"),
    ],
)
def test_clean_url_removes_glued_access_dates_without_removing_paths(source, expected):
    from refchecker.utils.url_utils import clean_url

    assert clean_url(source) == expected


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("https://arxiv.org/ab\ns/1411.4028", "https://arxiv.org/abs/1411.4028"),
        ("https://aclanthology.org/2020.\nemnlp-main.550.pdf", "https://aclanthology.org/2020.emnlp-main.550.pdf"),
    ],
)
def test_join_wrapped_urls_recovers_split_path_components(source, expected):
    from refchecker.utils.url_utils import join_wrapped_url_lines

    assert join_wrapped_url_lines(source) == expected
