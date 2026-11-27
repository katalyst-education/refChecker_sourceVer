"""Regression tests for targeted reference-extraction false positives."""

import re

import pytest

from refchecker.llm.base import LLMProvider
from refchecker.core.refchecker import ArxivReferenceChecker
from refchecker.utils.url_utils import clean_url_punctuation


@pytest.mark.parametrize(("reference", "authors", "title", "venue"), [
    ({
        "raw_text": "[14] K.K. Ching Cheung & D.T. Kit Ng, A systematic review of research "
        "on translanguaging in STEM education, International Journal of Multi-lingualism, "
        "Taylor & Francis, 2025",
        "authors": [],
        "title": "Ching Cheung & D",
        "venue": "Kit Ng, A systematic review of research on translanguaging in STEM education, "
        "International Journal of Multi-lingualism, Taylor & Francis, 2025",
    }, ["K.K. Ching Cheung", "D.T. Kit Ng"],
     "A systematic review of research on translanguaging in STEM education",
     "International Journal of Multi-lingualism"),
    ({
        "raw_text": "[7] A. V. Proletarsky, T. I. Buldakova, and A. V. Lantsberg, Educational "
        "programmes for training digital economy personnel, in Cyber-Phys. Syst., "
        "A. G. Kravets and A. A. Bolshakov, Eds. Cham, Switzerland: Springer, 2024, "
        "ch. 8, pp. 123-140. doi: 10.1007/978-3-031- 67911-\n7_8.",
        "authors": [], "title": "", "venue": "",
    }, ["A. V. Proletarsky", "T. I. Buldakova", "A. V. Lantsberg"],
     "Educational programmes for training digital economy personnel", "Cyber-Phys. Syst."),
    ({
        "raw_text": "[8] C. India, instructional-design-strategies-commlab. 2023. [Online]. "
        "Available: https://www.commlabindia.com/resources/ebook/instructional-\ndesign-strategies",
        "authors": [], "title": "India, instructional-design-strategies-commlab",
    }, ["C. India"], "instructional-design-strategies-commlab", None),
])
def test_recover_reviewed_unquoted_source_fields(reference, authors, title, venue):
    from refchecker.utils.text_utils import normalize_reference_fields

    result = normalize_reference_fields(reference)
    assert result["authors"] == authors
    assert result["title"] == title
    assert result.get("venue") == venue


def test_unquoted_field_recovery_preserves_existing_authors_and_title():
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = {
        "raw_text": "[8] C. India, instructional-design-strategies-commlab. 2023. [Online]. "
        "Available: https://www.commlabindia.com/resources/ebook/instructional-design-strategies",
        "authors": ["C. India"], "title": "Existing title",
    }

    result = normalize_reference_fields(reference)
    assert result["authors"] == ["C. India"]
    assert result["title"] == "Existing title"


@pytest.mark.parametrize(
    ("reference", "authors", "title", "venue"),
    [
        (
            {
                "raw_text": "[1] https://example.edu/report.pdf",
                "authors": [],
                "title": "https://example.edu/report.pdf",
                "venue": "",
            },
            [],
            "",
            "",
        ),
        (
            {
                "raw_text": "[2] ICPC, 2023. http://icpc.baylor.edu/",
                "authors": ["ICPC"],
                "title": "http://icpc.baylor.edu/",
                "venue": "",
            },
            ["ICPC"],
            "",
            "",
        ),
        (
            {
                "raw_text": (
                    "[3] A New Biology for the 21st Century. 2009."
                ),
                "authors": ["A New"],
                "title": "Biology for the 21st Century. 2009",
                "venue": "",
            },
            [],
            "A New Biology for the 21st Century",
            "",
        ),
        (
            {
                "raw_text": (
                    "[4] Investing in Climate for Growth and Development. "
                    "OECD Publishing, 2025."
                ),
                "authors": [
                    "Investing in Climate for Growth and Development, OECD"
                ],
                "title": "Investing in Climate for Growth and Development",
                "venue": "OECD Publishing",
            },
            [],
            "Investing in Climate for Growth and Development",
            "OECD Publishing",
        ),
        (
            {
                "raw_text": (
                    '[5] A. Author, "Example title," 2024, '
                    "arXiv:1409.1556. https://arxiv.org/abs/1409.1556"
                ),
                "authors": ["A. Author"],
                "title": "Example title",
                "venue": "arXiv:1409",
            },
            ["A. Author"],
            "Example title",
            "",
        ),
        (
            {
                "raw_text": (
                    '[6] Delft University of Technology, "Minor Robotics," '
                    "https://www.tudelft.nl/robotics, 2025, accessed: Nov. 6, 2025."
                ),
                "authors": ["Delft University of Technology"],
                "title": "Minor Robotics",
                "venue": "https://www.tudelft.nl/robotics, 2025, accessed: Nov. 6",
            },
            ["Delft University of Technology"],
            "Minor Robotics",
            "",
        ),
    ],
)
def test_source_absent_fields_are_not_promoted(reference, authors, title, venue):
    from refchecker.utils.text_utils import normalize_reference_fields

    result = normalize_reference_fields(reference)
    assert result["authors"] == authors
    assert result["title"] == title
    assert result["venue"] == venue


def test_normalization_preserves_full_when_it_is_part_of_a_doi_resolver_url():
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = {
        "raw_text": "[1] A. Smith, Example, 2020. https://doi.org/10.3389/example/full",
        "title": "Example",
        "authors": ["A. Smith"],
        "url": "https://doi.org/10.3389/example/full",
        "doi": "10.3389/example/full",
    }

    assert normalize_reference_fields(reference)["doi"] == "10.3389/example/full"


@pytest.mark.parametrize("publication", ["New York", "no. January"])
def test_page_range_does_not_make_location_or_issue_a_venue(publication):
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = {
        "raw_text": f'[1] A. Smith, "Example title," {publication}, pp. 4-7, 1998.',
        "authors": ["A. Smith"], "title": "Example title", "venue": "",
    }

    assert not normalize_reference_fields(reference).get("venue")


def test_proceedings_recovery_does_not_overwrite_existing_venue():
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = {
        "raw_text": '[1] A. Smith, "Example," in Proceedings of the International '
        'Conference on Testing, London, 2025.',
        "authors": ["A. Smith"], "title": "Example", "venue": "Existing venue",
    }

    assert normalize_reference_fields(reference)["venue"] == "Existing venue"


def test_proceedings_city_is_not_treated_as_an_acronym():
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = {
        "raw_text": '[1] A. Smith, "Example," in Proceedings of the International '
        'Conference on Testing, London 2020, UK, 2020.',
        "authors": ["A. Smith"], "title": "Example", "venue": "",
    }

    result = normalize_reference_fields(reference)
    assert result["venue"] == "Proceedings of the International Conference on Testing"


@pytest.mark.parametrize(("raw", "author", "title", "venue"), [
    ("[3] Department of Education and Training, Government of Western Australia, "
     "Competency Framework for Teachers, Perth, 2004.",
     "Department of Education and Training, Government of Western Australia",
     "Competency Framework for Teachers", None),
    ("[4] National Society of Professional Engineers (NSPE), Engineering Body "
     "of Knowledge, 2nd ed., Licensure and Qualifications for Practice Committee, 2013.",
     "National Society of Professional Engineers (NSPE)", "Engineering Body of Knowledge, 2nd ed.",
     "Licensure and Qualifications for Practice Committee"),
    ("[9] European Commission, Artificial Intelligence and the Future of Teaching "
     "and Learning in Higher Education, Joint Research Centre, Luxembourg, 2022.",
     "European Commission", "Artificial Intelligence and the Future of Teaching and Learning in Higher Education",
     "Joint Research Centre"),
    ("[19] American Society for Engineering Education (ASEE), Transforming "
     "Undergraduate Education in Engineering (TUEE) Phase III: Synthesizing and "
     "Integrating Industry Perspectives, Washington, DC, 2019.",
     "American Society for Engineering Education (ASEE)",
     "Transforming Undergraduate Education in Engineering (TUEE) Phase III: Synthesizing and Integrating Industry Perspectives",
     None),
    ("[2] International Energy Agency, CO2 Emissions from Fuel Combustion 2023, "
     "IEA Publications, Paris, France, 2023.",
     "International Energy Agency", "CO2 Emissions from Fuel Combustion 2023", "IEA Publications"),
    ("[3] European Commission, Circular Economy Action Plan, COM 2020/98 final.",
     "European Commission", "Circular Economy Action Plan", None),
])
def test_recover_reviewed_institutional_citation(raw, author, title, venue):
    from refchecker.utils.text_utils import normalize_reference_fields

    result = normalize_reference_fields({"raw_text": raw, "authors": [], "title": "", "venue": ""})
    assert result["authors"] == [author]
    assert result["title"] == title
    assert (result.get("venue") or None) == venue


@pytest.mark.parametrize(("raw", "authors", "title", "venue"), [
    (
        "[4] I. Casebourne, S. Shi, M. Hogan, et al. Using AI to Support "
        "Education for\nCollective Intelligence. Int J Artif Intell Educ "
        "35, 1597-1629 2025.",
        ["I. Casebourne", "S. Shi", "M. Hogan", "et al"],
        "Using AI to Support Education for Collective Intelligence",
        "Int J Artif Intell Educ",
    ),
    (
        "[2] International Energy Agency, CO2 Emissions from Fuel Combustion\n"
        "2023, IEA Publications, Paris, France, 2023.",
        ["International Energy Agency"],
        "CO2 Emissions from Fuel Combustion 2023",
        "IEA Publications",
    ),
    (
        "[3] European Commission, Circular Economy Action Plan, COM 2020/98\n"
        "final.",
        ["European Commission"],
        "Circular Economy Action Plan",
        "",
    ),
])
def test_recover_source_fields_when_authors_were_already_parsed(
    raw, authors, title, venue
):
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": raw, "authors": authors, "title": "", "venue": "",
    })

    assert reference["authors"] == authors
    assert reference["title"] == title
    assert (reference.get("venue") or "") == venue


def test_do_not_recover_source_fields_when_parsed_authors_conflict():
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": "[2] International Energy Agency, CO2 Emissions from Fuel "
        "Combustion 2023, IEA Publications, Paris, France, 2023.",
        "authors": ["A. Different Author"], "title": "", "venue": "",
    })

    assert reference["authors"] == ["A. Different Author"]
    assert not reference.get("title")
    assert not reference.get("venue")


def test_proceedings_recovery_does_not_infer_year_from_doi():
    from refchecker.utils.text_utils import _recover_unambiguous_numbered_fields

    reference = {"authors": ["A. Smith"], "title": "Example", "venue": ""}
    raw = ('[1] A. Smith, "Example," in Proceedings of the International '
           'Conference on Testing, doi: 10.1234/abc.2024.22.')
    _recover_unambiguous_numbered_fields(reference, raw)
    assert not reference["venue"]
    assert "year" not in reference


@pytest.mark.parametrize(("raw", "title", "venue", "year"), [
    ("[15] Types of HVAC systems. (2018, November 5). IntechOpen - Open Science "
     "Open Minds | IntechOpen. https://www.intechopen.com/chapters/62059",
     "Types of HVAC systems", "IntechOpen - Open Science Open Minds | IntechOpen", 2018),
    ("[17] Green wall specification and drawings. (2022, July 1). Biotecture. "
     "https://www.biotecture.uk.com/design-and-specify/specifications-\nandcompliance/",
     "Green wall specification and drawings", "Biotecture", 2022),
    ("[21] Work Breakdown Structure (WBS): The Ultimate Guide (with Examples). "
     "(n.d.). https://www.projectmanager.com/guides/work-\nbreakdown-structure.",
     "Work Breakdown Structure (WBS): The Ultimate Guide (with Examples)", None, None),
    ("[11] Official websites of universities in the World University Rankings Top- "
     "100, Times Higher Education, 2025. [Online]. Available: "
     "https://www.timeshighereducation.com/world-ranking.",
     "Official websites of universities in the World University Rankings Top- 100",
     "Times Higher Education", 2025),
    ("[31] Official websites of universities in the top ranking of Russian "
     "universities, RAEX, 2025. [Online]. Available: "
     "https://raex-rr.com/education/top-100.",
     "Official websites of universities in the top ranking of Russian universities",
     "RAEX", 2025),
    ("[37] Federal Law No. 273-FZ, Government of the Russian Federation, "
     "Dec. 2012. [Online]. Available: https://example.com/federal-law.",
     "Federal Law No. 273-FZ", "Government of the Russian Federation", 2012),
])
def test_title_first_website_preserves_source_fields_and_absences(raw, title, venue, year):
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = {"raw_text": raw, "authors": [], "title": "", "venue": ""}
    result = normalize_reference_fields(reference)
    assert result["authors"] == []
    assert result["title"] == title
    assert (result.get("venue") or None) == venue
    assert result.get("year") == year
    assert result["field_extraction_status"]["authors"] == "absent"
    if not venue:
        assert result["field_extraction_status"]["venue"] == "absent"


def test_title_first_website_keeps_url_reference_sentinel():
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = {
        "raw_text": "[1] Example website. (n.d.). https://example.com/",
        "authors": ["URL Reference"], "title": "", "venue": "",
    }

    result = normalize_reference_fields(reference)
    assert result["authors"] == ["URL Reference"]
    assert result["title"] == "Example website"


@pytest.mark.parametrize(("raw", "title", "expected_authors"), [
    (
        "[1] Luo, Z. Curriculum Design of Competitive Programming: A "
        "Contestbased Approach. 2025. https://doi.org/10.48550/arXiv.2504.00533.",
        "Curriculum Design of Competitive Programming: A Contestbased Approach",
        ["Luo, Z."],
    ),
    (
        "[10] P.R. Nair \"Increasing Employability of Indian Engineering "
        "Graduates through Experiential Learning Programs\" Procedia Computer Science.",
        "Increasing Employability of Indian Engineering Graduates through "
        "Experiential Learning Programs",
        ["P.R. Nair"],
    ),
    (
        "[7] W. M. Taha, A.-E. M. Taha, and J. Thunberg, Coordinate "
        "Transformation (Robot Arm). Cham: Springer International Publishing, 2021.",
        "Coordinate Transformation (Robot Arm)",
        ["W. M. Taha", "A.-E. M. Taha", "J. Thunberg"],
    ),
    (
        "[4] AGUNE, P.; RODRIGUES, V. G.; KUNINARI, R. F.; ZANESKI, M.; "
        "ARAÚJO, M. V.; NOTARGIACOMO, P. Gamificação associada à Realidade "
        "Virtual no Ensino Superior: Uma revisão sistemática.",
        "Gamificação associada à Realidade Virtual no Ensino Superior",
        [
            "AGUNE, P.", "RODRIGUES, V. G.", "KUNINARI, R. F.",
            "ZANESKI, M.", "ARAÚJO, M. V.", "NOTARGIACOMO, P.",
        ],
    ),
    (
        "[6] CARDOSO, Rodrigo Elias; PÓVOA, Carlos Alberto; CORRÊA, Thiago "
        "Henrique Barnabé. Design Thinking na educação. Observatorium, 2023.",
        "Design Thinking na educação",
        [
            "CARDOSO, Rodrigo Elias", "PÓVOA, Carlos Alberto",
            "CORRÊA, Thiago Henrique Barnabé",
        ],
    ),
    (
        "[19] N'goran, R., Tetchueng, J.-L., Pandry, G., Kermarrec, Y. and "
        "Asseu, O. Trust Assessment Model Based on a Zero Trust Strategy in "
        "a Community Cloud Environment. Engineering, 2022.",
        "Trust Assessment Model Based on a Zero Trust Strategy in a Community "
        "Cloud Environment",
        [
            "N'goran, R.", "Tetchueng, J.-L.", "Pandry, G.",
            "Kermarrec, Y.", "Asseu, O.",
        ],
    ),
    (
        "[11] SANTOS, E. O. dos; OKADA, A. L. P. A construção de ambientes "
        "virtuais de aprendizagem: por autorias plurais e gratuitas no "
        "ciberespaço. UFBA, 2003.",
        "A construção de ambientes virtuais de aprendizagem",
        ["SANTOS, E. O. dos", "OKADA, A. L. P."],
    ),
    (
        "[2] National Centre for Science and Engineering Statistics, "
        "International Comparisons of S&E Higher Education, 2023. "
        "[Online]. Available: https://example.com/report.",
        "National Centre for Science and Engineering Statistics, "
        "International Comparisons of S&E Higher Education",
        ["National Centre for Science and Engineering Statistics"],
    ),
    (
        "[9] ICPC, 2023. http://icpc.baylor.edu/",
        "",
        ["ICPC"],
    ),
    (
        "[14] Digital Education Council. What Students Want: Key Results from "
        "DEC Global AI Student Survey 2024. "
        "https://www.digitaleducationcouncil.com/post/what-students-want.",
        "Digital Education Council. What Students Want: Key Results from "
        "DEC Global AI Student Survey",
        ["Digital Education Council"],
    ),
    (
        "[2] Mkhize, Z. 2023. Is it transformation or reform? The lived "
        "experiences of African women doctoral students in STEM disciplines.",
        "Is it transformation or reform? The lived experiences of African "
        "women doctoral students in STEM disciplines",
        ["Mkhize, Z."],
    ),
    (
        "[4] R.-V. International, The RISC-v instruction set manual, 2025.",
        "R.-V. International, The RISC-v instruction set manual",
        ["R.-V. International"],
    ),
])
def test_recovers_explicit_leading_authors(raw, title, expected_authors):
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": raw, "authors": ["URL Reference"], "title": title, "venue": "",
    })

    assert reference["authors"] == expected_authors


@pytest.mark.parametrize(("raw", "title"), [
    (
        '[28] "Sustainability Awareness Framework (SusAF)," SUSO. '
        "Accessed: Oct. 28, 2025. [Online]. Available: https://example.com/",
        "Sustainability Awareness Framework (SusAF)",
    ),
    (
        '[20] "Open Dataset | OU Analyse | Knowledge Media Institute | The '
        'Open University," Open.ac.uk, 2015. https://example.com/open-dataset',
        "Open Dataset | OU Analyse | Knowledge Media Institute | The Open University",
    ),
    (
        "[27] BMSTU Student Trade Union Committee. [Online]. "
        "Available: http://profkom.bmstu.ru/",
        "BMSTU Student Trade Union Committee",
    ),
])
def test_does_not_promote_titles_or_ambiguous_labels_to_authors(raw, title):
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": raw, "authors": [], "title": title, "venue": "",
    })

    assert not reference.get("authors")


def test_short_organization_website_is_not_misclassified_as_title_first():
    from refchecker.utils.text_utils import finalize_reference_fields

    reference = {
        "raw_text": (
            "[61] GoogleLabs, Notebooklm, 2023. [Online]. Available: "
            "https://notebooklm.google/."
        ),
        "authors": [],
        "title": "",
        "venue": "",
    }

    result = finalize_reference_fields([reference])[0]
    assert result["title"] == ""
    assert not result.get("venue")


def test_author_year_web_journal_fields_are_recovered_from_source():
    from refchecker.utils.text_utils import finalize_reference_fields

    reference = {
        "raw_text": (
            "[39] T. Yu. Krotenko, Engineering economics and technological "
            "education: A transdisciplinary approach to the training of modern "
            "engineers, Vestn. PNIPU. Sotsial'no-ekon. Nauki, no. 4, 2022. "
            "[Online]. Available: https://example.com/article. "
            "(Accessed: 3 November 2025)."
        ),
        "authors": ["URL Reference"],
        "title": (
            "T. Yu. Krotenko, Engineering economics and technological "
            "education: A transdisciplinary approach to the training of modern "
            "engineers, Vestn. PNIPU. Sotsial'no-ekon. Nauki, no. 4, 2022. "
            "[Online]. Available: (Accessed: 3 November 2025)"
        ),
        "venue": "",
        "year": 2022,
    }

    result = finalize_reference_fields([reference])[0]
    assert result["authors"] == ["T. Yu. Krotenko"]
    assert result["title"] == (
        "Engineering economics and technological education: A "
        "transdisciplinary approach to the training of modern engineers"
    )
    assert result["venue"] == "Vestn. PNIPU. Sotsial'no-ekon. Nauki"
    assert result["year"] == 2022
    assert "field_extraction_status" not in result


@pytest.mark.parametrize(("raw", "title"), [
    ("[6] 3Dnatives\nHomepage, https://www.3dnatives.com/en/women-in-3d-\n"
     "printing-080320184/ last accessed 2025/26/05", "3Dnatives Homepage"),
    ("[11] APA\nScience\nHomepage, www.science.apa.at/power-\n"
     "search/17012929664440812974, last accessed 2025/10/06", "APA Science Homepage"),
])
def test_homepage_citation_preserves_site_descriptor_and_source_absences(raw, title):
    from refchecker.utils.text_utils import normalize_reference_fields

    result = normalize_reference_fields({"raw_text": raw, "authors": [], "title": "", "venue": ""})
    assert result["title"] == title
    assert result["authors"] == []
    assert result["field_extraction_status"] == {"authors": "absent", "venue": "absent"}


def test_homepage_with_additional_authorship_is_not_marked_absent():
    from refchecker.utils.text_utils import _match_homepage_citation

    raw = "[1] Example Homepage, https://example.com/, by Alice, last accessed 2025/06/07"
    assert not _match_homepage_citation(raw)


def test_website_recovery_preserves_conflicting_populated_fields():
    from refchecker.utils.text_utils import _recover_unambiguous_numbered_fields

    raw = "[1] Example website. (2022, July 1). Publisher. https://example.com/"
    for existing in (
        {"authors": ["A. Author"], "title": "", "venue": ""},
        {"authors": [], "title": "Different title", "venue": ""},
        {"authors": [], "title": "", "venue": "Different publisher"},
    ):
        original = existing.copy()
        _recover_unambiguous_numbered_fields(existing, raw)
        assert existing == original


@pytest.mark.parametrize(("raw", "authors", "title", "venue", "year"), [
    (
        "[11] Micheli, P., Wilner, S., Bhatti, S.B., Mura, M., Beverland M., [2019] "
        "Doing Design Thinking: Conceptual Review, Synthesis, and Research Agenda. "
        "Journal of Product Innovation Management, pp. 1-25",
        ["Micheli, P.", "Wilner, S.", "Bhatti, S.B.", "Mura, M.", "Beverland M."],
        "Doing Design Thinking: Conceptual Review, Synthesis, and Research Agenda",
        "Journal of Product Innovation Management", 2019,
    ),
    (
        "[21] von Delft, S.,Yang Zhao, Y., (2021). Business models in process industries: "
        "Emerging trends and future research, Technovation, Vol 105, "
        "https://doi.org/10.1016/j.technovation.2020.102195",
        ["von Delft, S.", "Yang Zhao, Y."],
        "Business models in process industries: Emerging trends and future research",
        "Technovation", 2021,
    ),
    (
        "[22] Wirtz, B.W. (2016), Business Model Management: Design Process Instruments, "
        "Textbook for the Digital Society, 2nd ed., Amazon Media Kindle E-Book, Speyer",
        ["Wirtz, B.W."],
        "Business Model Management: Design Process Instruments, Textbook for the Digital Society",
        "Amazon Media Kindle E-Book", 2016,
    ),
    (
        "[23] Zott,C., Amit., R., Massa., L, (2011). The Business Model: Recent "
        "Developments and Future Research. Journal of Management Vol. 37 No. 4, "
        "July 2011 1019-1042 DOI: 10.1177/0149206311406265",
        ["Zott, C.", "Amit., R.", "Massa., L"],
        "The Business Model: Recent Developments and Future Research",
        "Journal of Management", 2011,
    ),
])
def test_recover_reviewed_numbered_author_year_fields(raw, authors, title, venue, year):
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = {"raw_text": raw, "authors": [], "title": "", "venue": ""}
    result = normalize_reference_fields(reference)
    assert result["authors"] == authors
    assert result["title"] == title
    assert result["venue"] == venue
    assert result["year"] == year


def test_author_year_recovery_does_not_override_populated_citation():
    from refchecker.utils.text_utils import _recover_unambiguous_numbered_fields

    raw = ("[1] Jones, A. (2021). Source title, Journal of Tests, Vol 2, "
           "https://doi.org/10.1234/5678")
    reference = {"authors": ["A. Different"], "title": "Another title", "venue": ""}
    _recover_unambiguous_numbered_fields(reference, raw)
    assert reference == {"authors": ["A. Different"], "title": "Another title", "venue": ""}


@pytest.mark.parametrize(("raw", "authors"), [
    (
        "[1] O. Lutsenko, G. Lutsenko: Active Learning, regory, Doab: "
        "https://www.mdpi.com/2227-7102/11/5/196, 2022",
        ["O. Lutsenko", "G. Lutsenko"],
    ),
    (
        "[6] H. Erwin, A. Fedewa, A.Beighle, S. Ahn: A Quantitative Review of "
        "Physical Activity, Health, and Learning Outcomes Associated With Classroom-Based "
        "Physical Activity Interventions, Journal of Applied School Psychology: "
        "https://www.tandfonline.com/doi/abs/10.1080/15377903.2012.643755, 2012",
        ["H. Erwin", "A. Fedewa", "A. Beighle", "S. Ahn"],
    ),
])
def test_recover_printed_names_without_replacing_url_sentinel(raw, authors):
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = {"raw_text": raw, "authors": ["URL Reference"], "title": "Existing title"}
    result = normalize_reference_fields(reference)
    assert result["authors"] == ["URL Reference"]
    assert result["source_authors"] == authors
    assert "authors" not in result.get("field_extraction_status", {})


def test_colon_website_recovery_does_not_treat_a_title_as_author():
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = {
        "raw_text": "[1] AI Learning: New ideas, Publisher: https://example.com/, 2022",
        "authors": ["URL Reference"], "title": "AI Learning",
    }
    assert "source_authors" not in normalize_reference_fields(reference)


@pytest.mark.parametrize(("raw", "title", "authors"), [
    (
        "[1] Ministero dell'Istruzione e del Merito (MIM), Linee guida per "
        "l'introduzione dell'Intelligenza Artificiale, 2025.",
        "",
        ["Ministero dell'Istruzione e del Merito (MIM)"],
    ),
    (
        "[1] Kompetenzzentrum Technik-Diversity-Chancengleichheit e.V. "
        "(2025) Datentool [Online]. Verfügbar unter "
        "https://www.komm-mach-mint.de/service/datentool.",
        "",
        ["Kompetenzzentrum Technik-Diversity-Chancengleichheit e.V."],
    ),
    (
        "[1] Superintendencia Nacional de Educación, SUNEDU. "
        "https://enlinea.sunedu.gob.pe/",
        "",
        ["Superintendencia Nacional de Educación, SUNEDU"],
    ),
    (
        "[1] Organization for Economic Co-operation and Development (OECD). "
        "https://www.oecd.org/en.html",
        "",
        ["Organization for Economic Co-operation and Development (OECD)"],
    ),
    (
        "[1] Arduino Mini Radar Kit Project, Arduino Mini Radar Kit, 2025, "
        "accessed 12 Nov 2025. [Online]. Available: "
        "https://it.scribd.com/document/701200052/Arduino-Mini-Radar-Kit",
        "",
        ["Arduino Mini Radar Kit Project"],
    ),
    (
        '[1] "Spatial Skills and their Relationship to Creativity and '
        'Innovation in Undergraduate Engineering Design" by Sheryl A. Sorby.',
        "Spatial Skills and their Relationship to Creativity and Innovation "
        "in Undergraduate Engineering Design",
        ["Sheryl A. Sorby"],
    ),
    (
        "[1] Hermann Ebbinghaus. Über das Gedächtnis: Untersuchungen zur "
        "experimentellen Psychologie. Leipzig: Duncker & Humblot, 1885.",
        "Hermann Ebbinghaus",
        ["Hermann Ebbinghaus"],
    ),
    (
        "[1] St \u0301ephane Badreau et Jean-Louis Boulanger. "
        "Ing \u0301enierie des exigences : Méthodes et bonnes pratiques "
        "pour construire un référentiel. Dunod, Paris, 2014.",
        "Ing \u0301enierie des exigences : Méthodes et bonnes pratiques "
        "pour construire un référentiel",
        ["Stéphane Badreau", "Jean-Louis Boulanger"],
    ),
    (
        "[1] J. C. Nunnally y I. H. Bernstein, Psychometric theory, "
        "3. ed., 1994.",
        "Psychometric theory",
        ["J. C. Nunnally", "I. H. Bernstein"],
    ),
    (
        "[1] Eikelmann, B. et al. (2019), Computer- und "
        "informationsbezogene Kompetenzen von Schülerinnen und Schülern "
        "im zweiten",
        "",
        ["Eikelmann, B.", "et al"],
    ),
    (
        "[1] 1. U. Congress, H.r.6227 - national quantum initiative act, "
        "2018.",
        "H.r.6227 - national quantum initiative act",
        ["1. U. Congress"],
    ),
    (
        "[1] Institution of Engineering and Technology, Accreditation of "
        "Higher Education Programmes (AHEP), 4th Edition, IET, 2020.",
        "Accreditation of Higher Education Programmes (AHEP)",
        ["Institution of Engineering and Technology"],
    ),
])
def test_recover_source_reviewed_author_formats(raw, title, authors):
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": raw,
        "authors": [],
        "title": title,
    })

    assert reference["authors"] == authors


@pytest.mark.parametrize(("raw", "title", "venue"), [
    (
        "[2] K. Nguyen, M. Borrego: Instructor strategies to aid implementation of active "
        "learning: a systematic literature review, Springer Nature https://example.com/, 2021",
        "Instructor strategies to aid implementation of active learning: a systematic literature review",
        "Springer Nature",
    ),
    (
        "[6] H. Erwin, A. Fedewa: A Quantitative Review of Physical Activity, Health, and "
        "Learning Outcomes Associated With Classroom-Based Physical Activity Interventions, "
        "Journal of Applied School Psychology : https://example.com/, 2012",
        "A Quantitative Review of Physical Activity, Health, and Learning Outcomes Associated With "
        "Classroom-Based Physical Activity Interventions",
        "Journal of Applied School Psychology",
    ),
])
def test_colon_website_recovers_title_and_venue_from_source(raw, title, venue):
    from refchecker.utils.text_utils import normalize_reference_fields

    before_url = raw.split("https://", 1)[0].split("] ", 1)[1].strip()
    result = normalize_reference_fields({"raw_text": raw, "authors": ["URL Reference"], "title": before_url})
    assert result["title"] == title
    assert result["venue"] == venue


def test_colon_website_does_not_split_ambiguous_source_details():
    from refchecker.utils.text_utils import normalize_reference_fields

    title = "O. Lutsenko, G. Lutsenko: Active Learning, regory, Doab:"
    raw = f"[1] {title} https://example.com/, 2022"
    result = normalize_reference_fields({"raw_text": raw, "authors": ["URL Reference"], "title": title})
    assert result["title"] == title
    assert not result.get("venue")


def test_normalization_recovers_source_inverted_author_book_fields():
    from refchecker.utils.text_utils import normalize_reference_fields

    raw = "[1] Wiggins, G., & McTighe, J. Understanding by Design. ASCD, 2005"
    reference = {
        "raw_text": raw,
        "authors": ["Wiggins, G.", "& McTighe, J"],
        "title": "ASCD",
        "year": 2005,
    }

    result = normalize_reference_fields(reference)

    assert result["authors"] == ["Wiggins, G.", "McTighe, J."]
    assert result["title"] == "Understanding by Design"
    assert result["venue"] == "ASCD"
    assert result["raw_text"] == raw


def test_normalization_recovers_author_only_source_without_inventing_fields():
    from refchecker.utils.text_utils import normalize_reference_fields

    raw = "[15] T. Collins, R. Getz, A. Wyglinski, and D. Pu, 2018."
    reference = {
        "raw_text": raw,
        "authors": ["Unknown Author"],
        "title": "Unknown Title",
        "year": 2018,
    }

    result = normalize_reference_fields(reference)

    assert result["authors"] == ["T. Collins", "R. Getz", "A. Wyglinski", "D. Pu"]
    assert not result["title"]
    assert not result.get("venue")
    assert result["raw_text"] == raw
    assert any("does not state" in warning for warning in result["extraction_warnings"])
    assert result["field_extraction_status"] == {"title": "absent", "venue": "absent"}


def test_normalization_does_not_infer_author_only_from_an_incomplete_record():
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = {
        "raw_text": "[1] T. Collins, A. Wyglinski, 2018. Unreadable title.",
        "authors": ["Unknown Author"],
        "title": "Unknown Title",
    }

    assert normalize_reference_fields(reference)["authors"] == ["Unknown Author"]


def test_author_year_only_citation_rejects_misparsed_title_and_venue():
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = {
        "raw_text": "[1] T. Collins, R. Getz, 2018.",
        "authors": ["T. Collins"],
        "title": "R. Getz",
        "venue": "2018",
    }

    result = normalize_reference_fields(reference)

    assert result["authors"] == ["T. Collins", "R. Getz"]
    assert result["title"] == ""
    assert result["venue"] == ""
    assert result["field_extraction_status"] == {"title": "absent", "venue": "absent"}


def test_missing_fields_are_uncertain_when_the_source_is_not_complete():
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = {
        "raw_text": "[1] A. Smith, 2021. An incomplete",
        "authors": ["Unknown Author"],
        "title": "",
    }

    result = normalize_reference_fields(reference)

    assert result["field_extraction_status"] == {
        "authors": "uncertain", "title": "uncertain", "venue": "uncertain",
    }


def test_partially_unknown_author_list_remains_uncertain():
    from refchecker.utils.text_utils import (
        annotate_reference_field_status, cited_authors_for_display,
    )

    reference = {"authors": ["A. Smith", "Unknown Author"], "title": "A study", "venue": "Journal"}

    result = annotate_reference_field_status(reference)

    assert result["field_extraction_status"] == {"authors": "uncertain"}
    assert cited_authors_for_display(result["authors"]) == ["A. Smith"]
    assert result["authors"] == ["A. Smith", "Unknown Author"]


def test_final_field_status_clears_placeholders_but_preserves_url_sentinel():
    from refchecker.utils.text_utils import finalize_reference_field_status

    unknown = finalize_reference_field_status({
        "authors": ["Unknown Author"], "title": "Unknown Title", "raw_text": "[1] Incomplete",
    })
    url_only = finalize_reference_field_status({
        "authors": ["URL Reference"], "title": "", "url": "https://example.org",
    })

    assert unknown["authors"] == []
    assert unknown["title"] == ""
    assert unknown["field_extraction_status"]["authors"] == "uncertain"
    assert unknown["field_extraction_status"]["title"] == "uncertain"
    assert url_only["authors"] == ["URL Reference"]
    assert url_only["field_extraction_status"]["authors"] == "uncertain"


def test_normalization_does_not_remove_unpaired_replacement_character():
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = {
        "raw_text": "[1] A. Smith, \ufffdUnknown glyph in title. Journal, 2021.",
        "title": "\ufffdUnknown glyph in title",
    }

    assert normalize_reference_fields(reference)["title"] == "\ufffdUnknown glyph in title"


def test_normalization_recovers_inverted_author_year_journal_entry():
    from refchecker.utils.text_utils import normalize_reference_fields

    raw = (
        "[21] Arnab, S., Lim, T., Carvalho, M.B., Bellotti, F., de Freitas, S., "
        "Louchart, S., Suttie, N., Berta, R. and De Gloria, A. (2015), "
        "Mapping learning and game mechanics. Br J Educ Technol, 46: 391-\n"
        "411. https://doi.org/10.1111/bjet.12113"
    )
    result = normalize_reference_fields({
        "raw_text": raw, "title": "Br J Educ Technol, 46: 391411",
        "authors": ["Arnab, S.", "Lim, T.", "Carvalho", "M.B."],
        "doi": "10.1111/bjet.12113",
    })

    assert result["authors"] == [
        "Arnab, S.", "Lim, T.", "Carvalho, M.B.", "Bellotti, F.",
        "de Freitas, S.", "Louchart, S.", "Suttie, N.", "Berta, R.",
        "De Gloria, A.",
    ]
    assert result["title"] == "Mapping learning and game mechanics"
    assert result["venue"] == "Br J Educ Technol"
    assert result["raw_text"] == raw
    assert result["doi"] == "10.1111/bjet.12113"


def test_author_year_recovery_does_not_treat_a_title_as_journal_metadata():
    from refchecker.utils.text_utils import normalize_reference_fields

    raw = "[1] Smith, J. and Jones, A. (2015), A study. Another sentence, 46: 10."
    reference = {"raw_text": raw, "title": "Existing title", "authors": ["J. Smith"]}

    # A bare number after the colon is not sufficient to establish a page range.
    assert normalize_reference_fields(reference)["title"] == "Existing title"


def test_normalization_recovers_inverted_authors_and_volume_year_journal():
    from refchecker.utils.text_utils import normalize_reference_fields

    raw = (
        "[25] Mapanga, A., Faleni, N. Integrating entrepreneurship education into "
        "STEM curricula in global South higher education institutions. Discov Educ "
        "4, 335 (2025). https://doi.org/10.1007/s44217-025-00798-8"
    )
    result = normalize_reference_fields({
        "raw_text": raw, "title": "Discov Educ 4, 335",
        "authors": ["Mapanga, A.", "Faleni"],
    })

    assert result["authors"] == ["Mapanga, A.", "Faleni, N."]
    assert result["title"] == (
        "Integrating entrepreneurship education into STEM curricula in global "
        "South higher education institutions"
    )
    assert result["venue"] == "Discov Educ"
    assert result["year"] == 2025
    assert result["raw_text"] == raw


def test_normalization_recovers_dated_ieee_event_without_conference_word():
    from refchecker.utils.text_utils import normalize_reference_fields

    raw = (
        '[18] H. Smith, "A study," 2020 IEEE Learning With MOOCS '
        '(LWMOOCS), Antigua Guatemala, Guatemala, 2020, pp. 118-123, '
        'doi: 10.1109/LWMOOCS50143.2020.9234360.'
    )
    reference = {"raw_text": raw, "title": "A study", "authors": ["H. Smith"]}

    result = normalize_reference_fields(reference)

    assert result["venue"] == "2020 IEEE Learning With MOOCS (LWMOOCS)"
    assert result["title"] == "A study"
    assert result["authors"] == ["H. Smith"]
    assert result["raw_text"] == raw


def test_normalization_does_not_infer_ieee_event_from_incomplete_tail():
    from refchecker.utils.text_utils import normalize_reference_fields

    raw = '[1] H. Smith, "A study," 2020 IEEE Learning With MOOCS (LWMOOCS).'
    assert not normalize_reference_fields({"raw_text": raw}).get("venue")


def test_normalization_recovers_semicolon_authors_and_journal():
    from refchecker.utils.text_utils import normalize_reference_fields

    raw = (
        "[2] Walters, K.; Rodriguez, J. The Importance of Training and "
        "Development in Employee Performance and Evaluation. World Wide "
        "J.Multidiscip. Res. Dev. 2017, 3, 206-212"
    )
    result = normalize_reference_fields({
        "raw_text": raw, "title": "Dev",
        "authors": ["Development in Employee Performance", "Evaluation"],
    })

    assert result["authors"] == ["Walters, K.", "Rodriguez, J."]
    assert result["title"] == "The Importance of Training and Development in Employee Performance and Evaluation"
    assert result["venue"] == "World Wide J.Multidiscip. Res. Dev."
    assert result["year"] == 2017
    assert result["raw_text"] == raw


def test_normalization_does_not_infer_journal_from_semicolon_authors_alone():
    from refchecker.utils.text_utils import normalize_reference_fields

    raw = "[2] Walters, K.; Rodriguez, J. A title. Notes, 2017, 3, 206-212."
    reference = {"raw_text": raw, "title": "Existing title"}

    assert normalize_reference_fields(reference)["title"] == "Existing title"


def test_normalization_recovers_labeled_chapter_publisher():
    from refchecker.utils.text_utils import normalize_reference_fields

    raw = (
        "[6] Sen,J. Embedded Systems and Wireless Technology. Chapter: 1. "
        "Publisher: CRC Press, Taylor & Francis Group, USA. 2012."
    )
    result = normalize_reference_fields({
        "raw_text": raw, "title": "Publisher: CRC Press, Taylor & Francis Group, USA",
        "authors": ["Sen,J. Embedded Systems", "Wireless Technology. Chapter: 1"],
    })

    assert result["authors"] == ["Sen,J."]
    assert result["title"] == "Embedded Systems and Wireless Technology"
    assert result["venue"] == "CRC Press, Taylor & Francis Group"
    assert result["year"] == 2012
    assert result["raw_text"] == raw


@pytest.mark.parametrize(
    ("raw", "authors", "title", "venue"),
    [
        (
            "[1] Farrell, C. (2012). Our (Work) Education Crisis: Send in the "
            "MOOCS, Bloomberg Newsweek, September 18.",
            ["Farrell, C."],
            "Our (Work) Education Crisis: Send in the MOOCS",
            "Bloomberg Newsweek",
        ),
        (
            "[5] Ho Lee,S. Hoon Han,J. Taik Leem,Y. Yigitcanlar,T. Towards "
            "ubiquitous city: concept, planning, and experiences in the Republic "
            "of Korea. IGI Global, Information Science Reference, Hershey. 2008.",
            [],
            "Towards ubiquitous city: concept, planning, and experiences in the Republic of Korea",
            "IGI Global, Information Science Reference",
        ),
        (
            "[17] Doost Mohammadian, H. An Overview of International Cross-Cultural "
            "Management. Fachhochschule des Mitt elstands GmbH, Bielefeld. Germany.2017.",
            ["Doost Mohammadian, H."],
            "An Overview of International Cross-Cultural Management",
            "Fachhochschule des Mitt elstands GmbH",
        ),
    ],
)
def test_normalization_recovers_reviewed_news_and_publisher_citations(raw, authors, title, venue):
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = {"raw_text": raw, "authors": ["Unknown Author"], "title": "Unknown Title"}

    result = normalize_reference_fields(reference)

    assert result["authors"] == authors
    assert result["title"] == title
    assert result["venue"] == venue
    assert result["raw_text"] == raw
    if not authors:
        assert result["field_extraction_status"]["authors"] == "uncertain"
        assert result["extraction_warnings"]


def test_normalization_recovers_unbalanced_quote_article_with_publisher():
    from refchecker.utils.text_utils import normalize_reference_fields

    raw = (
        "[26] Mohammadian, H.D. Blue-Green Smart Mobility Technologies as "
        "Readiness for Facing Tomorrow's Urban Shock toward the World as a Better "
        "Place for Living (Case Studies: Songdo and Copenhagen)'', Thecnologies, "
        "MDPI, Published: 2nd of July 2020, https://www.mdpi.com/2227-7080/8/3/39"
    )
    result = normalize_reference_fields({
        "raw_text": raw, "authors": ["Mohammadian, H"], "title": "Unknown Title",
    })

    assert result["authors"] == ["Mohammadian, H.D."]
    assert result["title"] == (
        "Blue-Green Smart Mobility Technologies as Readiness for Facing Tomorrow's "
        "Urban Shock toward the World as a Better Place for Living "
        "(Case Studies: Songdo and Copenhagen)"
    )
    assert result["venue"] == "Thecnologies"
    assert result["year"] == 2020
    assert result["raw_text"] == raw


@pytest.mark.parametrize("raw", [
    "[1] Farrell, C. (2012). Our Education Crisis, September 18.",
    "[5] Ho Lee,S. Hoon Han,J. Towards ubiquitous city. IGI Global, 2008.",
    "[17] Doost Mohammadian, H. An Overview. 2017.",
    "[26] Mohammadian, H.D. Blue-Green Mobility'', Thecnologies, MDPI, 2020.",
])
def test_source_format_recovery_leaves_incomplete_citations_unchanged(raw):
    from refchecker.utils.text_utils import _recover_unambiguous_numbered_fields

    reference = {"authors": ["Original"], "title": "Original", "venue": ""}
    before = dict(reference)
    _recover_unambiguous_numbered_fields(reference, raw)
    assert reference == before


def test_ambiguous_author_warning_is_not_duplicated():
    from refchecker.utils.text_utils import normalize_reference_fields

    raw = (
        "[5] Ho Lee,S. Hoon Han,J. Taik Leem,Y. Yigitcanlar,T. Towards ubiquitous "
        "city: concept, planning, and experiences in the Republic of Korea. "
        "IGI Global, Information Science Reference, Hershey. 2008."
    )
    result = normalize_reference_fields({"raw_text": raw, "authors": ["Unknown Author"]})
    result = normalize_reference_fields(result)

    assert result["authors"] == []
    assert len(result["extraction_warnings"]) == 1


@pytest.mark.parametrize(("raw", "title", "venue"), [
    (
        "[20] Doost Mohammadian, H. Rezaie, F. Sustainable Innovative Project "
        "Management: Response to Improve Livability and Quality of Life: Case "
        "Studies: Iran Germany, Inventions, MDPI, Published: Sept. 2019,",
        "Sustainable Innovative Project Management: Response to Improve Livability "
        "and Quality of Life: Case Studies: Iran Germany",
        "Inventions",
    ),
    (
        '[39] Mattiello, H. Domann, C. "Overcoming SME Legal and Regulatory '
        'Challenges and Fostering Sustainable Collaboration and 7PS Engineering '
        'in the Digital Age through Integrating the X.0 Wave Theory & SME 5.0 '
        'Concept", Intelligent and Sustainable Manufacturing 2024, 1 (2), 10011; '
        'https://doi.org/10.35534/ism.2024.10011',
        "Overcoming SME Legal and Regulatory Challenges and Fostering Sustainable "
        "Collaboration and 7PS Engineering in the Digital Age through Integrating "
        "the X.0 Wave Theory & SME 5.0 Concept",
        "Intelligent and Sustainable Manufacturing",
    ),
])
def test_normalization_separates_reviewed_journal_fields(raw, title, venue):
    from refchecker.utils.text_utils import normalize_reference_fields

    original_authors = ["Previously extracted author"]
    result = normalize_reference_fields({
        "raw_text": raw, "authors": original_authors, "title": "Original",
    })
    assert result["authors"] == original_authors
    assert result["title"] == title
    assert result["venue"] == venue
    assert result["raw_text"] == raw


def test_normalization_recovers_publisher_statement_without_guessing_authors():
    from refchecker.utils.text_utils import normalize_reference_fields

    raw = (
        "[14] Dutzler, H. Schmaus, B. Schrauf.S. Nitschke,A. Hochrainer,P. "
        "Industry 4.0: Opportunities and challenges for consumer product and "
        "retail companies. Published by Service Mark of PwC Strategy& LLC. "
        "The United States. 2016."
    )
    result = normalize_reference_fields({
        "raw_text": raw,
        "authors": ["challenges for consumer product", "retail companies"],
        "title": "The United States",
    })
    assert result["authors"] == []
    assert result["title"] == (
        "Industry 4.0: Opportunities and challenges for consumer product and retail companies"
    )
    assert result["venue"] == "Service Mark of PwC Strategy& LLC"
    assert result["extraction_warnings"]
    assert result["raw_text"] == raw


def test_normalization_rejoins_source_acronym_compound_in_title():
    from refchecker.utils.text_utils import normalize_reference_fields

    raw = '[13] A. Author, "IoT-\neducation policies," IEEE Conference, 2020.'
    result = normalize_reference_fields({
        "raw_text": raw, "authors": ["A. Author"],
        "title": "IoT- education policies", "venue": "IEEE Conference",
    })
    assert result["title"] == "IoT-education policies"
    assert result["raw_text"] == raw


def test_normalization_rejoins_source_self_compound_in_title():
    from refchecker.utils.text_utils import normalize_reference_fields

    raw = '[21] A. Author. Comparison of student self-\nassessment. Journal, 2023.'
    reference = normalize_reference_fields({
        "raw_text": raw, "authors": ["A. Author"],
        "title": "Comparison of student self- assessment", "venue": "Journal",
    })
    assert reference["title"] == "Comparison of student self-assessment"
    assert reference["raw_text"] == raw


@pytest.mark.parametrize(("raw", "author", "title"), [
    (
        "[1] European Commission, Industry 5.0: towards a sustainable, human "
        "centric and resilient European industry. Publications Office of the "
        "European Union, 2021. Accessed: Nov. 14, 2025. [Online]. Available: "
        "https://data.europa.eu/doi/10.2777/308407",
        "European Commission",
        "Industry 5.0: towards a sustainable, human centric and resilient European industry",
    ),
    (
        "[23]. Directorate-General for Research and Innovation, Industry 5.0, a "
        "transformative vision for Europe - Governing systemic transformations "
        "towards a sustainable industry, Publications Office of the European "
        "Union, 2021, https://data.europa.eu/doi/10.2777/17322",
        "Directorate-General for Research and Innovation",
        "Industry 5.0, a transformative vision for Europe - Governing systemic "
        "transformations towards a sustainable industry",
    ),
])
def test_normalization_recovers_source_institutional_publications(raw, author, title):
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": raw, "authors": ["URL Reference"], "title": raw,
    })
    assert reference["authors"] == [author]
    assert reference["title"] == title
    assert reference["venue"] == "Publications Office of the European Union"
    assert reference["year"] == 2021
    assert reference["raw_text"] == raw


def test_institutional_book_does_not_treat_title_as_author():
    from refchecker.utils.text_utils import normalize_reference_fields

    raw = ('[7] UNESCO, ChatGPT and Artificial Intelligence in Higher Education: '
           'Quick Start Guide. Paris, France: UNESCO, 2023.')
    reference = normalize_reference_fields({
        "raw_text": raw, "authors": ["UNESCO, ChatGPT", "Artificial Intelligence"],
        "title": "ChatGPT and Artificial Intelligence in Higher Education: Quick Start Guide",
    })
    assert reference["authors"] == ["UNESCO"]
    assert reference["title"] == "ChatGPT and Artificial Intelligence in Higher Education: Quick Start Guide"
    assert reference["venue"] == "UNESCO"


def test_edition_catalog_book_recovers_source_fields():
    from refchecker.utils.text_utils import normalize_reference_fields

    raw = ('[15] A. Booth, A. Sutton, and D. Papaioannou, Systematic approaches '
           'to a successful literature review, second edition ed. '
           'Los Angeles: Sage, 2016, oCLC: ocn950914568.')
    reference = normalize_reference_fields({"raw_text": raw, "authors": [], "title": ""})
    assert reference["authors"] == ["A. Booth", "A. Sutton", "D. Papaioannou"]
    assert reference["title"] == "Systematic approaches to a successful literature review"
    assert reference["venue"] == "Sage"


def test_final_multiword_author_is_not_truncated_to_initial():
    from refchecker.utils.text_utils import normalize_reference_fields

    raw = ('[43] G. C. Zapata, J. W. Jones, and R. Abrantes Da Silva, '
           '"AI and peer reviews," Technology, Pedagogy and Education, 2025.')
    reference = normalize_reference_fields({
        "raw_text": raw, "authors": ["G. C. Zapata", "J. W. Jones", "R"],
        "title": "AI and peer reviews",
    })
    assert reference["authors"] == ["G. C. Zapata", "J. W. Jones", "R. Abrantes Da Silva"]


def test_author_separator_is_not_part_of_the_author_name():
    from refchecker.utils.text_utils import normalize_reference_fields

    raw = '[3] Y. Shi, D. Wu, & H. Yang, "A title", Journal, 2022.'
    reference = normalize_reference_fields({
        "raw_text": raw, "authors": ["Y. Shi", "D. Wu", "& H. Yang"], "title": "A title",
    })
    assert reference["authors"] == ["Y. Shi", "D. Wu", "H. Yang"]


def test_author_separator_cleanup_requires_source_support():
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": '[3] Y. Shi, D. Wu, "A title mentioning & H. Yang", Journal, 2022.',
        "authors": ["Y. Shi", "& H. Yang"],
        "title": "A title mentioning & H. Yang",
    })
    assert reference["authors"] == ["Y. Shi", "& H. Yang"]


def test_inverted_author_separator_is_not_part_of_the_author_name():
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": '[4] Roomi, M. M., & Mashima, D. "A title", Journal, 2025.',
        "authors": ["Roomi, M. M.", "& Mashima, D."],
        "title": "A title",
    })
    assert reference["authors"] == ["Roomi, M. M.", "Mashima, D."]


def test_unquoted_author_year_title_recovers_missing_authors():
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": (
            "[5] F. Amiri and M. Abdollahi Saryazdi 2024. Code-switching as a "
            "pedagogical tool in EFL classrooms: Cultural and practical implications."
        ),
        "authors": ["Unknown Author"],
        "title": "Amiri and M",
    })
    assert reference["authors"] == ["F. Amiri", "M. Abdollahi Saryazdi"]
    assert reference["title"] == (
        "Code-switching as a pedagogical tool in EFL classrooms: Cultural and practical implications"
    )


def test_unquoted_author_year_title_preserves_url_sentinel():
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": "[5] F. Amiri and M. Saryazdi 2024. A title.",
        "authors": ["URL Reference"],
        "title": "A title",
    })
    assert reference["authors"] == ["URL Reference"]


def test_apa_conference_restores_authors_title_and_venue():
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": (
            "[7] Chakraborty, S., & Galatro, D. (2025, April). Artificial Intelligence "
            "(AI) Equality in Engineering Education. In 2025 IEEE Global Engineering "
            "Education Conference (EDUCON) (pp. 1-10). IEEE."
        ),
        "authors": ["Chakraborty, S.", "& Galatro", "D. (", "April)"],
        "title": "Artificial Intelligence (AI) Equality in Engineering Education",
    })
    assert reference["authors"] == ["Chakraborty, S.", "Galatro, D."]
    assert reference["title"] == "Artificial Intelligence (AI) Equality in Engineering Education"
    assert reference["venue"] == "2025 IEEE Global Engineering Education Conference (EDUCON)"


def test_apa_conference_preserves_decimal_points_in_title():
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": (
            "[14] Galatro, D., & Chakraborty, S. (2025, June). Chemical Process Design "
            "to meet Industry 5.0 competencies. In 2025 ASEE Annual Conference & Exposition."
        ),
        "authors": ["Galatro, D"],
        "title": ", & Chakraborty, S",
    })
    assert reference["authors"] == ["Galatro, D.", "Chakraborty, S."]
    assert reference["title"] == "Chemical Process Design to meet Industry 5.0 competencies"
    assert reference["venue"] == "2025 ASEE Annual Conference & Exposition"


def test_abbreviated_proceedings_with_doi_is_recovered():
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": (
            '[3] M. Yampolsky and E. Altman, "A case study," '
            'Proc. 5th Int. Workshop Games Softw. Eng. (GAS), pp. 8-14, '
            '2016, doi: 10.1109/GAS.2016.010.'
        ),
        "authors": ["M. Yampolsky", "E. Altman"],
        "title": "A case study",
    })
    assert reference["venue"] == "Proc. 5th Int. Workshop Games Softw. Eng. (GAS)"


def test_unquoted_institutional_report_recovers_fields_without_expanding_authors():
    from refchecker.utils.text_utils import normalize_reference_fields

    raw = ('[4] N. Fouad et al., Why Women Leave Engineering, '
           'University of Wisconsin-Milwaukee, 2011.')
    reference = normalize_reference_fields({"raw_text": raw, "authors": [], "title": ""})
    assert reference["authors"] == ["N. Fouad", "et al"]
    assert reference["title"] == "Why Women Leave Engineering"
    assert reference["venue"] == "University of Wisconsin-Milwaukee"
    assert reference["year"] == 2011

    sentinel = normalize_reference_fields({"raw_text": raw, "authors": ["URL Reference"], "title": ""})
    assert sentinel["authors"] == ["URL Reference"]
    assert not sentinel.get("venue")


def test_institution_title_and_untitled_conference_stay_separate():
    checker = ArxivReferenceChecker(llm_config={"disabled": True})
    bibliography = (
        "[1] UNESCO, Cracking the Code: Girls' and Women's Education in STEM, 2017.\n"
        '[2] S. Cheryan et al., "Why Are Some STEM Fields More Gender Balanced?" '
        'Psychological Bulletin, 2017.\n'
        "[3] E. McGee & J. Bentley, IEEE EDUCON, 2022.\n"
        "[4] N. Fouad et al., Why Women Leave Engineering, University of Wisconsin-Milwaukee, 2011."
    )

    refs = checker.parse_references(bibliography)

    assert refs[0]["authors"] == ["UNESCO"]
    assert refs[0]["title"] == "Cracking the Code: Girls' and Women's Education in STEM"
    assert refs[2]["authors"] == ["E. McGee", "J. Bentley"]
    assert not refs[2]["title"]
    assert refs[2]["venue"] == "IEEE EDUCON"
    assert refs[2]["field_extraction_status"]["title"] == "absent"
    assert refs[3]["authors"] == ["N. Fouad", "et al"]


@pytest.mark.parametrize(("raw", "author", "title"), [
    (
        '[6] UNESCO, Guidance for Generative AI in Education and Research, Paris, 2023.',
        'UNESCO', 'Guidance for Generative AI in Education and Research',
    ),
    (
        '[24] Xilinx, Debug Bridge v3.0 IP Product Guide (PG245), 2018.',
        'Xilinx', 'Debug Bridge v3.0 IP Product Guide (PG245)',
    ),
])
def test_institutional_title_recovers_without_inventing_venue(raw, author, title):
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({"raw_text": raw, "authors": [], "title": ""})
    assert reference["authors"] == [author]
    assert reference["title"] == title
    assert not reference.get("venue")


def test_institutional_guide_does_not_override_existing_authors():
    from refchecker.utils.text_utils import normalize_reference_fields

    raw = '[24] Xilinx, Debug Bridge v3.0 IP Product Guide (PG245), 2018.'
    reference = normalize_reference_fields({"raw_text": raw, "authors": ["Another Author"], "title": ""})
    assert reference["authors"] == ["Another Author"]
    assert not reference["title"]


def test_institutional_guide_repairs_title_split_across_fields():
    from refchecker.utils.text_utils import normalize_reference_fields

    raw = '[24] Xilinx, Debug Bridge v3.0 IP Product Guide (PG245), 2018.'
    reference = normalize_reference_fields({
        "raw_text": raw, "authors": ["Xilinx", "Debug Bridge v"],
        "title": "0 IP Product Guide (PG245)",
    })
    assert reference["authors"] == ["Xilinx"]
    assert reference["title"] == "Debug Bridge v3.0 IP Product Guide (PG245)"
    assert not reference.get("venue")


def test_author_suffix_is_not_a_separate_author():
    from refchecker.utils.text_utils import normalize_reference_fields

    raw = ('[26] T. U. Ganiron, Jr., "Evaluation of engineering programs '
           'towards global accreditation", World Scientific News, 2016.')
    reference = normalize_reference_fields({
        "raw_text": raw, "authors": ["T. U. Ganiron", "Jr."],
        "title": "Evaluation of engineering programs towards global accreditation",
    })
    assert reference["authors"] == ["T. U. Ganiron, Jr."]
    reference = normalize_reference_fields({
        "raw_text": raw, "authors": ["T. U. Ganiron", "Jr.", "Another Author"],
        "title": "Evaluation of engineering programs towards global accreditation",
    })
    assert reference["authors"] == ["T. U. Ganiron", "Jr.", "Another Author"]


@pytest.mark.parametrize(("raw", "venue"), [
    (
        '[9] A. Vaswani et al., "Attention is All you Need," in Advances in '
        'Neural Information Processing Systems, Curran Associates, Inc., 2017. '
        'Accessed: June 07, 2025. [Online]. Available: https://example.org/article',
        "Advances in Neural Information Processing Systems",
    ),
    (
        '[55] C. Liu and S. Yang, "Application of large language models in '
        'engineering education: A case study of system modeling and simulation '
        'courses," International Journal of Mechanical Engineering Education, '
        'p. 03064190241272728, Aug. 2024, doi: 10.1177/03064190241272728.',
        "International Journal of Mechanical Engineering Education",
    ),
    (
        '[16] J. Park and S. Choo, "Generative ai prompt engineering for educators: '
        'Practical strategies," Journal of Special Education Technology, '
        'p. 01626434241298954, 2024.',
        "Journal of Special Education Technology",
    ),
    (
        '[4] E. Alyahyan, M. Bikanga Ada, and J. Lever, "Adoption, usage, '
        'and perceptions of LLM-generated feedback," in Proceedings of the '
        '2025 Frontiers in Education Conference (FIE 2025), Nashville, '
        'Tennessee, 2025, (Accepted for Publication).',
        "Proceedings of the 2025 Frontiers in Education Conference (FIE 2025)",
    ),
    (
        '[31] X. Tang et al., "Sphere: Supporting personalized feedback," '
        'in Proceedings of the Extended Abstracts of the CHI Conference on '
        "Human Factors in Computing Systems, ser. CHI EA '25. New York, NY, "
        'USA: Association for Computing Machinery, 2025. [Online]. Available: '
        'https://doi.org/10.1145/3706599.3720203',
        "Proceedings of the Extended Abstracts of the CHI Conference on Human Factors in Computing Systems",
    ),
    (
        '[36] T. Van Mullem et al., "Are llms good at answering student '
        "questions in cs1 courses?\" ser. ITiCSE 2025. New York, NY, USA: "
        'Association for Computing Machinery, 2025, p. 780. [Online]. Available: '
        'https://doi.org/10.1145/3724389.3730778',
        "ITiCSE 2025",
    ),
    (
        '[17] R. Abuzayeda, I. Karamitsos, and A. Kanavos, "Advancing Student '
        'Guidance Using Classification Data Mining Techniques," in International '
        'Conference on Artificial Intelligence, Computer, Data Sciences, and '
        'Applications, ACDSA 2024, Institute of Electrical and Electronics '
        'Engineers Inc., 2024. doi: 10.1109/ACDSA59508.2024.10467350.',
        "International Conference on Artificial Intelligence, Computer, Data Sciences, and Applications, ACDSA 2024",
    ),
    (
        '[4] Y. Lu et al., " GNN 101: Visual learning of graph neural networks '
        'in your web browser, " arXiv preprint arXiv:2411.17849, 2024.',
        "arXiv preprint",
    ),
    (
        '[3] Y. Shi et al., "Examining the effects of notetaking styles", '
        'Australasian Journal of Educational Technology, p. 1-11, 2022.',
        "Australasian Journal of Educational Technology",
    ),
    (
        '[31] T. Lei et al., "Graph-based robot optimal path planning with '
        'bio-inspired algorithms," Biomimetic Intelligence and Robotics, '
        'p. 100119, 2023.',
        "Biomimetic Intelligence and Robotics",
    ),
    (
        '[2] O.I. Dolgaya, "Distance learning abroad at the present stage," '
        'School Technologies, no. 2, pp. 9-16, 2019.',
        "School Technologies",
    ),
    (
        '[26] T. U. Ganiron, Jr., "Evaluation of engineering programs towards '
        'global accreditation", World Scientific News, no. 59, pp. 97-108, 2016.',
        "World Scientific News",
    ),
    (
        '[10] C. C. Beatty and K. L. Guthrie, "Developing culturally relevant '
        'leadership educators," New Directions for Student Leadership, '
        'no. 182, pp. 11-22, 2024.',
        "New Directions for Student Leadership",
    ),
    (
        '[14] P. S. Figueiro, "Education for sustainability," Journal of Cleaner '
        'Production, no. 339, p. 130539, 2022.',
        "Journal of Cleaner Production",
    ),
    (
        '[25] S. Boechat-Heer, "Les methodes mixtes," Form. Prat. '
        "d'enseignement en Quest., no. 17, pp. 49-65, 2014.",
        "Form. Prat. d'enseignement en Quest.",
    ),
    (
        '[28] M. Firat, "Integrating AI Applications into Learning Management '
        'Systems to Enhance e-Learning," ITALL, pp. 1-14, Jun. 2023, '
        'doi: 10.52911/itall.1244453.',
        "ITALL",
    ),
    (
        '[10] T. K. F. Chiu et al., "Teacher support and student motivation to '
        'learn with Artificial Intelligence (AI) based chatbot," Interactive Learning '
        'Environments, pp. 1-17, Feb. 2023, doi: 10.1080/10494820.2023.2172044. '
        'Available: https://www.tandfonline.com/doi/full/10.1080/10494820.2023.2172044. '
        '[Accessed: Nov. 16, 2025]',
        "Interactive Learning Environments",
    ),
    (
        '[2] A. Kelly, M. Sullivan, and K. Strampel, "Generative artificial '
        'intelligence in education". Journal of University Teaching and Learning '
        'Practice, 20(6), pp.1-16. 2023.',
        "Journal of University Teaching and Learning Practice",
    ),
])
def test_normalization_recovers_online_proceedings_and_article_venue(raw, venue):
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": raw, "authors": ["A. Author"], "title": "Original",
    })
    assert reference["authors"] == ["A. Author"]
    assert reference["title"] == "Original"
    assert reference["venue"] == venue


def test_arxiv_recovery_preserves_populated_source_venue():
    from refchecker.utils.text_utils import normalize_reference_fields

    raw = ('[4] Y. Lu et al., " GNN 101, " '
           'arXiv preprint arXiv:2411.17849, 2024.')
    reference = normalize_reference_fields({
        "raw_text": raw, "authors": ["Y. Lu"], "title": "GNN 101",
        "venue": "arXiv preprint arXiv:2411.17849",
    })
    assert reference["venue"] == "arXiv preprint arXiv:2411.17849"


def test_dated_page_range_doi_preserves_existing_venue():
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": '[1] A. Author, "A title," ITALL, pp. 1-14, Jun. 2023, doi: 10.1234/example.',
        "authors": ["A. Author"], "title": "A title", "venue": "Existing venue",
    })
    assert reference["venue"] == "Existing venue"


@pytest.mark.parametrize(("venue", "tail"), [
    ("Informatics in Education", ""),
    ("Health Care Management Science", ""),
    ("arXiv.org", " [Online]. Available: https://arxiv.org/abs/2308.11584"),
    ("Authorea (Authorea)", ""),
    ("Harvard.edu", " [Online]. Available: https://dash.harvard.edu/item"),
])
def test_numeric_month_source_venue(venue, tail):
    from refchecker.utils.text_utils import normalize_reference_fields

    raw = f'[1] A. Author, "A study," {venue}, 06 2020.{tail}'
    result = normalize_reference_fields({"raw_text": raw, "authors": ["A. Author"], "title": "A study"})
    assert result["venue"] == venue


@pytest.mark.parametrize("detail", ["New York", "pp. 555-560"])
def test_numeric_month_detail_is_not_automatically_a_venue(detail):
    from refchecker.utils.text_utils import normalize_reference_fields

    raw = f'[1] A. Author, "A study," {detail}, 06 2020.'
    result = normalize_reference_fields({"raw_text": raw, "authors": ["A. Author"], "title": "A study"})
    assert not result.get("venue")


@pytest.mark.parametrize(("raw", "authors", "title", "venue", "year"), [
    (
        "[7] Hilton, J. Open educational resources and college textbook choices: a review "
        "of research on efficacy and perceptions. Education Tech Research Dev 64, 573-590 (2016).",
        ["Hilton, J"],
        "Open educational resources and college textbook choices: a review of research on efficacy and perceptions",
        "Education Tech Research Dev", 2016,
    ),
    (
        "[40] [40] WING, 2006. Computational thinking. Communications of the ACM 49, 3, 33-35.",
        ["WING"], "Computational thinking", "Communications of the ACM", 2006,
    ),
    (
        "[1] Xu L. Innovative interdisciplinary models in engineering education: Transforming "
        "practices across global universities. Engineering Education Review 2025;2(3):129-144.",
        ["Xu L"],
        "Innovative interdisciplinary models in engineering education: Transforming practices across global universities",
        "Engineering Education Review", 2025,
    ),
])
def test_recover_journal_metadata_joined_to_populated_title(raw, authors, title, venue, year):
    from refchecker.utils.text_utils import normalize_reference_fields

    match = re.search(re.escape(title) + r'\..*?(?= \(\d{4}\)|\.$)', raw)
    reference = {
        "raw_text": raw, "authors": authors, "title": match.group(), "year": year,
    }
    result = normalize_reference_fields(reference)
    assert result["title"] == title
    assert result["venue"] == venue
    assert result["authors"] == authors


def test_joined_title_recovery_does_not_assume_location_is_a_journal():
    from refchecker.utils.text_utils import normalize_reference_fields

    raw = "[1] A. Author. A long example title. New York 64, 573-590 (2016)."
    reference = {"raw_text": raw, "authors": ["A. Author"], "title": "A long example title. New York 64, 573-590"}
    result = normalize_reference_fields(reference)
    assert result["title"] == reference["title"]
    assert not result.get("venue")


def test_author_title_recovery_preserves_a_distinct_populated_title():
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = {
        "raw_text": "[1] Xu L. A long example article title. Engineering Education Review 2025;2(3):129-144.",
        "authors": ["Xu L"],
        "title": "A different populated title",
        "year": 2025,
    }
    result = normalize_reference_fields(reference)
    assert result["title"] == reference["title"]
    assert not result.get("venue")


@pytest.mark.parametrize(("raw", "title", "venue"), [
    (
        '[19] A. Almusaed, M. R. Cortez, and A. Almssad, '
        '"Redefining Engineering Education: The Transformative Role of Generative AI Technologies", '
        'International Society for Technology, Education, and Science, 2024.',
        "Redefining Engineering Education: The Transformative Role of Generative AI Technologies",
        "International Society for Technology, Education, and Science",
    ),
    (
        '[24] C. T. Cripe, "Real-time cognitive tools for space," Intelligent Human '
        'Systems Integration (IHSI 2025): Integrating People and Intelligent Systems, p. 87, 2025.',
        "Real-time cognitive tools for space",
        "Intelligent Human Systems Integration (IHSI 2025): Integrating People and Intelligent Systems",
    ),
    (
        '[17] B. Qureshi, "Chatgpt in computer science curriculum assessment: An analysis of its '
        'successes and shortcomings," in 2023 9th International Conference on e-Society '
        'e-Learning and e-Technologies, ICSLT 2023, p. 7-13, ACM, June 2023.',
        "Chatgpt in computer science curriculum assessment: An analysis of its successes and shortcomings",
        "2023 9th International Conference on e-Society e-Learning and e-Technologies, ICSLT 2023",
    ),
    (
        '[8] Francois Lopitaux, "Spotter: Your ai analyst," ThoughtSpot, Tech. Rep., '
        '2025, [Online]. Available: https://www.thoughtspot.com/blog/\n'
        'everyone-gets-an-ai-analyst.',
        "Spotter: Your ai analyst",
        "ThoughtSpot",
    ),
    (
        '[7] F. Gottschalk and H. Borhan, "Child participation in decision making: '
        'Implications for education and beyond," tech. rep., OECD, Paris, Nov. 2023.',
        "Child participation in decision making: Implications for education and beyond",
        "OECD",
    ),
])
def test_recover_source_quoted_publication_venues(raw, title, venue):
    from refchecker.utils.text_utils import normalize_reference_fields

    result = normalize_reference_fields({
        "raw_text": raw, "authors": ["A. Source Author"], "title": title,
    })
    assert result["title"] == title
    assert result["venue"] == venue
    assert result["journal"] == venue


def test_technical_report_date_is_not_treated_as_venue():
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": '[1] A. Author, "A report," Tech. Rep., Feb. 2021.',
        "authors": ["A. Author"], "title": "A report",
    })
    assert not reference.get("venue")


@pytest.mark.parametrize(("raw", "title", "venue"), [
    (
        '[36] N. L. Webb, "Criteria for alignment of expectations and assessments in mathematics '
        'and science education," Council of Chief State School Officers, Washington, DC, '
        'Tech. Rep., 1997.',
        "Criteria for alignment of expectations and assessments in mathematics and science education",
        "Council of Chief State School Officers",
    ),
    (
        '[4] R. Luckin, W. Holmes, M. Griffiths, and L. B. Forcier, "Intelligence unleashed: '
        'An argument for AI in education," UCL Knowledge Lab, London, UK, Tech. Rep., 2016.',
        "Intelligence unleashed: An argument for AI in education",
        "UCL Knowledge Lab",
    ),
    (
        '[5] L. Acree, "Seven lessons learned from implementing microcredentials," Friday Institute '
        'for Educational Innovation, NC State University College of Education, Raleigh, NC, '
        'Tech. Rep., Jan. 2016.',
        "Seven lessons learned from implementing microcredentials",
        "Friday Institute for Educational Innovation, NC State University College of Education",
    ),
])
def test_technical_report_venue_drops_trailing_publication_location(raw, title, venue):
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": raw, "authors": ["A. Source Author"], "title": title,
    })
    assert reference["venue"] == venue


def test_institutional_book_separates_title_from_misparsed_author_and_publisher():
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": "[1] National Academy of Engineering, Engineering as a Social Enterprise. "
        "Washington, D.C.: National Academies Press, 1991. doi: 10.17226/1829.",
        "authors": ["National Academy of Engineering", "Engineering as a Social Enterprise"],
        "title": "",
    })
    assert reference["authors"] == ["National Academy of Engineering"]
    assert reference["title"] == "Engineering as a Social Enterprise"
    assert reference["venue"] == "National Academies Press"
    assert reference["year"] == 1991


def test_institutional_book_recovery_preserves_a_different_populated_title():
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": "[1] National Academy of Engineering, Engineering as a Social Enterprise. "
        "Washington, D.C.: National Academies Press, 1991. doi: 10.17226/1829.",
        "authors": ["National Academy of Engineering", "Engineering as a Social Enterprise"],
        "title": "Different extracted title",
    })
    assert reference["title"] == "Different extracted title"
    assert not reference.get("venue")


@pytest.mark.parametrize(("raw", "authors", "title", "venue"), [
    (
        "[5] Coyle, D., Hood, P., and D. Marsh, CLIL: Content and Language "
        "Integrated Learning, Cambridge University Press, 2010.",
        ["Coyle, D.", "Hood, P.", "D. Marsh"],
        "CLIL: Content and Language Integrated Learning",
        "Cambridge University Press",
    ),
    (
        "[6] Hyland, K., English for Academic Purposes: An Advanced Resource "
        "Book, Routledge, 2006.",
        ["Hyland, K."],
        "English for Academic Purposes: An Advanced Resource Book",
        "Routledge",
    ),
])
def test_unquoted_compact_book_fields_recover_all_printed_fields(raw, authors, title, venue):
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": raw, "authors": [], "title": "",
    })
    assert reference["authors"] == authors
    assert reference["title"] == title
    assert reference["venue"] == venue


def test_unquoted_book_recovery_leaves_quoted_article_fields_unchanged():
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": '[6] L.M. Nkomo, B.K. Daniel and R.J. Butson, '
                    '"Synthesis of student engagement with digital technologies: '
                    'A systematic review of the literature", Int J Education '
                    'Technology Higher Education 18(34) Springer, 2021.',
        "authors": ["L.M. Nkomo", "B.K. Daniel", "R.J. Butson"],
        "title": "Synthesis of student engagement with digital technologies: "
                 "A systematic review of the literature",
        "venue": "Int J Education Technology Higher Education 18(34) Springer",
    })
    assert reference["authors"] == ["L.M. Nkomo", "B.K. Daniel", "R.J. Butson"]
    assert reference["title"] == (
        "Synthesis of student engagement with digital technologies: "
        "A systematic review of the literature"
    )
    assert reference["venue"] == "Int J Education Technology Higher Education 18(34) Springer"


def test_compact_book_recovery_leaves_location_prefix_for_city_publisher_rule():
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": '[20] M. Eraut, Developing Professional Knowledge and '
                    'Competence, London: Routledge, 1994.',
        "authors": ["M. Eraut"],
        "title": "Developing Professional Knowledge and Competence, London: Routledge",
    })
    assert reference["title"] == "Developing Professional Knowledge and Competence"
    assert reference["venue"] == "Routledge"


@pytest.mark.parametrize(("raw", "authors", "title"), [
    (
        "[1] Ministry of Education of China, Outstanding Engineer Education "
        "and Training Plan 2.0, 2018.",
        ["Ministry of Education of China"],
        "Outstanding Engineer Education and Training Plan 2.0",
    ),
    (
        "[2] Ministry of Education, Ministry of Industry and Information "
        "Technology, and Chinese Academy of Engineering, Opinions on Accelerating "
        "the Development of Emerging Engineering Disciplines and Implementing "
        "the Outstanding Engineer Education and Training Programme 2.0, 2018.",
        [
            "Ministry of Education",
            "Ministry of Industry and Information Technology",
            "Chinese Academy of Engineering",
        ],
        "Opinions on Accelerating the Development of Emerging Engineering "
        "Disciplines and Implementing the Outstanding Engineer Education and "
        "Training Programme 2.0",
    ),
])
def test_institutional_policy_without_publisher_recovers_only_printed_fields(
    raw, authors, title
):
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": raw, "authors": [], "title": "",
    })
    assert reference["authors"] == authors
    assert reference["title"] == title
    assert reference["year"] == 2018
    assert not reference.get("venue")


def test_institutional_policy_rule_does_not_match_personal_author_citations():
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": "[1] A. Author, A report title, 2018.",
        "authors": [], "title": "",
    })
    assert not reference.get("authors")
    assert not reference.get("title")
    assert not reference.get("venue")


@pytest.mark.parametrize(("reference", "authors", "title", "venue"), [
    (
        {
            "raw_text": "[16] Organización de las Naciones Unidas para la Educación, "
                        "la Ciencia y la Cultura (UNESCO), Guidance for Generative AI "
                        "in Education and Research. Paris: UNESCO, 2023, doi: "
                        "10.54675/unesco.2023.iaedu.",
            "authors": [
                "Organización de las Naciones Unidas para la Educación",
                "la Ciencia y la Cultura (UNESCO)",
                "Guidance for Generative AI in Education and Research",
            ],
            "title": "Paris: UNESCO, 2023, doi: 10",
        },
        ["Organización de las Naciones Unidas para la Educación, la Ciencia y la Cultura (UNESCO)"],
        "Guidance for Generative AI in Education and Research",
        "UNESCO",
    ),
    (
        {
            "raw_text": "[17] OECD, OECD Framework for the Classification of AI "
                        "Systems. Paris: OECD Publishing, 2022, doi: "
                        "10.1787/cb6aeca5-en.",
            "authors": ["OECD"],
            "title": "OECD Framework for the Classification of AI Systems",
            "venue": "Paris: OECD Publishing",
        },
        ["OECD"],
        "OECD Framework for the Classification of AI Systems",
        "OECD Publishing",
    ),
])
def test_institutional_city_publisher_recovers_source_fields(
    reference, authors, title, venue
):
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields(reference)
    assert reference["authors"] == authors
    assert reference["title"] == title
    assert reference["venue"] == venue


@pytest.mark.parametrize("tail", [
    'New York, pp. 88-102, 2012.',
    'New York, no. 3, pp. 88-102, 2012.',
    'World Scientific News, pp. 88-102, 2012.',
    'New York, pp. 88-102, Jun. 2012, doi: 10.1234/example.',
    'vol. 13, no. 1, pp. 33-50, 2014.',
])
def test_page_range_does_not_make_location_or_volume_a_venue(tail):
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": f'[1] A. Author, "A title," {tail}',
        "authors": ["A. Author"], "title": "A title",
    })
    assert not reference.get("venue")


def test_quoted_page_range_does_not_make_location_a_venue():
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": '[1] A. Author, "A title". New York, 20(6), pp.1-16. 2023.',
        "authors": ["A. Author"], "title": "A title",
    })
    assert not reference.get("venue")


@pytest.mark.parametrize(("tail", "venue"), [
    ('Education Sciences, 11(11), p.698. 2021.', 'Education Sciences'),
    ('Journal of Research on Technology in Education, 54(sup1), pp.S182-S202. 2022.',
     'Journal of Research on Technology in Education'),
    ('Learning and Motivation, 78, p.101802. 2022.', 'Learning and Motivation'),
    ('Innovations in education and teaching international, 62(3), pp.781-794. 2025',
     'Innovations in education and teaching international'),
    ('International Journal of Learning. Teaching and Educational Research, '
     '23(10), pp.395-414. 2024.',
     'International Journal of Learning. Teaching and Educational Research'),
    ('Digital Government: Research and Practice, 6(1), pp.1-21. 2025.',
     'Digital Government: Research and Practice'),
    ('Educational Process: International Journal, 13(2), pp.105-121. 2024.',
     'Educational Process: International Journal'),
])
def test_quoted_journal_recovers_volume_issue_and_article_number(tail, venue):
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": f'[1] A. Author, "A study". {tail}',
        "authors": ["A. Author"], "title": "A study",
    })
    assert reference["venue"] == venue


def test_quoted_journal_does_not_replace_populated_venue():
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": '[1] A. Author, "A study". Education Sciences, 11(11), p.698. 2021.',
        "authors": ["A. Author"], "title": "A study", "venue": "Existing venue",
    })
    assert reference["venue"] == "Existing venue"


@pytest.mark.parametrize(("tail", "venue"), [
    ('Scientific Reports, 13, 13304, 2023.', 'Scientific Reports'),
    ('Education and Information Technologies, 27, pp.4521-4552, 2022.',
     'Education and Information Technologies'),
    ('European Journal of Engineering Education, 49(3), 577-603, 2023.',
     'European Journal of Engineering Education'),
    ('Innov High Educ, 50, 665-684, 2025.', 'Innov High Educ'),
    ('Transactions of the Association for Computational Linguistics, '
     '12, pp.157-173, 2024.', 'Transactions of the Association for Computational Linguistics'),
])
def test_quoted_numeric_volume_journal_recovers_venue(tail, venue):
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": f'[1] A. Author, "A study," {tail}',
        "authors": ["A. Author"], "title": "A study",
    })
    assert reference["venue"] == venue


@pytest.mark.parametrize("tail", [
    'New York, 20, 1-16, 2023.',
    'Proceedings, 20, 1-16, 2023.',
    'Education Street, 20, 2023.',
])
def test_numeric_volume_does_not_infer_ambiguous_venue(tail):
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": f'[1] A. Author, "A study," {tail}',
        "authors": ["A. Author"], "title": "A study",
    })
    assert not reference.get("venue")


def test_numeric_volume_preserves_existing_venue():
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": '[1] A. Author, "A study," Scientific Reports, 13, 13304, 2023.',
        "authors": ["A. Author"], "title": "A study", "venue": "Existing venue",
    })
    assert reference["venue"] == "Existing venue"


@pytest.mark.parametrize(("tail", "venue"), [
    ('IEEE transactions on systems, man, and cybernetics, no. 3, pp. 257-266, 2012.',
     'IEEE transactions on systems, man, and cybernetics'),
    ('Behaviour & Information Technology, pp. 1-15, 2025.',
     'Behaviour & Information Technology'),
])
def test_paged_journal_with_comma_or_technology_recovers_venue(tail, venue):
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": f'[1] A. Author, "A study," {tail}',
        "authors": ["A. Author"], "title": "A study",
    })
    assert reference["venue"] == venue


def test_ieee_paged_citation_does_not_infer_a_location_as_venue():
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": '[1] A. Author, "A study," IEEE meeting, New York, no. 3, pp. 1-16, 2023.',
        "authors": ["A. Author"], "title": "A study",
    })
    assert not reference.get("venue")


@pytest.mark.parametrize(("raw", "venue"), [
    ('[19] A. Author, "Attention is all you need," in Proceedings of the '
     '31st International Conference on Neural Information Processing Systems, '
     "ser. NIPS'17. Red Hook, NY, USA: Curran Associates Inc., 2017, p. 6000-6010.",
     'Proceedings of the 31st International Conference on Neural Information Processing Systems'),
    ('[38] A. Author, "Can language models be too big?" in Proceedings of the '
     "2021 ACM Conference on Fairness, Accountability, and Transparency, ser. FAccT '21. "
     'New York, NY, USA: Association for Computing Machinery, 2021, p. 610-623.',
     'Proceedings of the 2021 ACM Conference on Fairness, Accountability, and Transparency'),
    ('[15] A. Author, "A study," in Proceedings of the 23rd Conference, '
     "ser. Koli '23. New York, NY, USA: ACM, 2024. [Online]. Available: "
     'https://doi.org/10.1145/3631802.3631851',
     'Proceedings of the 23rd Conference'),
])
def test_proceedings_series_recovers_printed_venue(raw, venue):
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": raw, "authors": ["A. Author"], "title": "A study",
    })
    assert reference["venue"] == venue


def test_proceedings_series_does_not_overwrite_existing_venue():
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": '[1] A. Author, "A study," in Proceedings of the Conference, '
                    "ser. ABC '23. New York, NY, USA: ACM, 2023.",
        "authors": ["A. Author"], "title": "A study", "venue": "Existing venue",
    })
    assert reference["venue"] == "Existing venue"


def test_bracket_year_website_recovers_organization_and_title():
    from refchecker.utils.text_utils import finalize_reference_field_status, normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": '[13] Bentley [2025] STAAD 3D Structural Analysis and Design Software. '
                    'https://www.bentley.com/software/staad/',
        "authors": [], "title": "",
    })
    finalize_reference_field_status(reference)
    assert reference["authors"] == ["Bentley"]
    assert reference["title"] == "STAAD 3D Structural Analysis and Design Software"
    assert reference["year"] == 2025
    assert reference["field_extraction_status"]["venue"] == "absent"


def test_bracket_year_website_does_not_overwrite_authors():
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": '[13] Bentley [2025] A title. https://www.bentley.com/software/staad/',
        "authors": ["Existing author"], "title": "",
    })
    assert reference["authors"] == ["Existing author"]
    assert not reference.get("title")


def test_initial_authors_and_et_al_with_abbreviated_journal():
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": '[4] I. Casebourne, S. Shi, M. Hogan, et al. Using AI to Support '
                    'Education for Collective Intelligence. Int J Artif Intell Educ '
                    '35, 1597-1629 2025.',
        "authors": [], "title": "",
    })
    assert reference["authors"] == ["I. Casebourne", "S. Shi", "M. Hogan", "et al"]
    assert reference["title"] == "Using AI to Support Education for Collective Intelligence"
    assert reference["venue"] == "Int J Artif Intell Educ"


def test_initial_et_al_does_not_infer_arbitrary_location_as_journal():
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": '[4] I. Casebourne, S. Shi, et al. A title. New York 35, 1597-1629 2025.',
        "authors": [], "title": "",
    })
    assert not reference.get("venue")


@pytest.mark.parametrize(("authors", "title"), [
    ('S. K. Chee, S. L. J. Hoong, and Y. S. Lee',
     'Innovating engineering education with blended learning and remote laboratories'),
    ('O. A. Oreshkina and Y. A. Safonova',
     'Instructional strategies for hearing-impaired students'),
])
def test_unquoted_educon_repairs_corrupted_fields(authors, title):
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": f'[17] {authors}, {title}, in Proc. 2024 IEEE Global Eng. '
                    'Educ. Conf. (EDUCON), Kos Island, Greece, 2024, pp. 1-5. '
                    'doi: 10.1109/EDUCON60312.2024.10578848.',
        "authors": ["O. A"], "title": "Educ",
    })
    assert reference["authors"][-1] in {"Y. S. Lee", "Y. A. Safonova"}
    assert reference["title"] == title
    assert reference["venue"] == "Proc. 2024 IEEE Global Eng. Educ. Conf. (EDUCON)"


@pytest.mark.parametrize(("tail", "venue"), [
    ('Proc. 2024 IEEE Global Engineering Education Conf. (EDUCON), Kos, Greece, May 2024.',
     'Proc. 2024 IEEE Global Engineering Education Conf. (EDUCON)'),
    ('Proceedings of the International Conference on Engineering Education (ICEE), '
     'Coimbra, Portugal, September 2007, paper 411.',
     'Proceedings of the International Conference on Engineering Education (ICEE)'),
    ('Proc. IEEE Global Eng. Edu. Conf. (EDUCON), Tunis, Tunisia, 2020, '
     'DOI: 10.1109/EDUCON45650.2020.9125223',
     'Proc. IEEE Global Eng. Edu. Conf. (EDUCON)'),
])
def test_located_conference_acronym_recovers_venue(tail, venue):
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": f'[1] A. Author, "A study," in {tail}',
        "authors": ["A. Author"], "title": "A study",
    })
    assert reference["venue"] == venue


def test_located_conference_acronym_preserves_existing_venue():
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": '[1] A. Author, "A study," in Proc. Conference (ABC), '
                    'Tunis, Tunisia, 2020.',
        "authors": ["A. Author"], "title": "A study", "venue": "Existing venue",
    })
    assert reference["venue"] == "Existing venue"


@pytest.mark.parametrize(("tail", "venue"), [
    ('Carnegie Mellon University News, Oct. 20, 2021. [Online]. Available: '
     'https://www.cmu.edu/news/active- learning.html', 'Carnegie Mellon University News'),
    ('Anthropic, Aug 27, 2025. [Online]. Available: https://www.anthropic.com/news/report',
     'Anthropic'),
])
def test_dated_website_recovers_venue_without_access_date(tail, venue):
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": f'[1] A. Author, "A study," {tail}',
        "authors": ["A. Author"], "title": "A study",
    })
    assert reference["venue"] == venue


def test_dated_website_does_not_make_date_the_venue():
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": '[1] A. Author, "A study," Oct. 20, 2021. '
                    '[Online]. Available: https://example.com/study',
        "authors": ["A. Author"], "title": "A study",
    })
    assert not reference.get("venue")


@pytest.mark.parametrize(("raw", "existing_title", "authors", "title", "venue"), [
    ('[12] I. Goodfellow, Y. Bengio, and A. Courville, Deep Learning. '
     'MIT Press, 2016, doi: 10.7551/mitpress/10900.001.0001.',
     'MIT Press, 2016, doi: 10', ['I. Goodfellow', 'Y. Bengio', 'A. Courville'],
     'Deep Learning', 'MIT Press'),
    ("[8] Kay L. O'Halloran. Multimodal Learning in Orchestrating Perceptual Meaning. "
     'The MIT Press, 2020. DOI: 10.7551/mitpress/4561.001.0001.',
     'DOI: 10', ["Kay L. O'Halloran"],
     'Multimodal Learning in Orchestrating Perceptual Meaning', 'The MIT Press'),
    ('[15] R. H. Thaler y C. R. Sunstein, Nudge: Improving Decisions About '
     'Health, Wealth, and Happiness. Yale University Press, 2008.',
     'Nudge: Improving Decisions About Health, Wealth, and Happiness',
     ['R. H. Thaler', 'C. R. Sunstein'],
     'Nudge: Improving Decisions About Health, Wealth, and Happiness', 'Yale University Press'),
    ('[18] M. Cukurova, F. Miao et al., AI competency framework for teachers. '
     'UNESCO Publishing, 2024, retrieved from https://www.unesco.org/en/ articles/teachers.',
     '', ['M. Cukurova', 'F. Miao', 'et al'],
     'AI competency framework for teachers', 'UNESCO Publishing'),
    ('[1] J. H. McClellan, R. Schafer, and M. Yoder, DSP First, 2nd ed. '
     'Pearson, August 2015.',
     '', ['J. H. McClellan', 'R. Schafer', 'M. Yoder'],
     'DSP First', 'Pearson'),
    ('[22] E. L. Deci and R. M. Ryan, Intrinsic Motivation and '
     'Self-Determination in Human Behavior. Springer Science & Business Media, '
     'June 2013. Google-Books-ID: M3CpBgAAQBAJ.',
     '', ['E. L. Deci', 'R. M. Ryan'],
     'Intrinsic Motivation and Self-Determination in Human Behavior',
     'Springer Science & Business Media'),
])
def test_publisher_book_recovers_printed_fields(raw, existing_title, authors, title, venue):
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": raw, "authors": ["Incomplete"], "title": existing_title,
    })
    assert reference["authors"] == authors
    assert reference["title"] == title
    assert reference["venue"] == venue


def test_publisher_book_does_not_replace_unrelated_existing_title():
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": '[1] A. Author and B. Author, A study. MIT Press, 2020.',
        "authors": ["A. Author"], "title": "Different title",
    })
    assert reference["title"] == "Different title"
    assert not reference.get("venue")


def test_publisher_book_replaces_author_fragment_when_authors_are_missing():
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": (
            "[22] E. L. Deci and R. M. Ryan, Intrinsic Motivation and "
            "Self-Determination in Human Behavior. Springer Science & Business "
            "Media, June 2013. Google-Books-ID: M3CpBgAAQBAJ."
        ),
        "authors": [],
        "title": "Deci and R",
    })

    assert reference["authors"] == ["E. L. Deci", "R. M. Ryan"]
    assert reference["title"] == (
        "Intrinsic Motivation and Self-Determination in Human Behavior"
    )
    assert reference["venue"] == "Springer Science & Business Media"


def test_volume_only_book_recovers_author_and_title_without_inventing_venue():
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": (
            "[28] A. Field, Discovering Statistics Using IBM SPSS Statistics "
            "(4th Edition), vol. 4. 2013."
        ),
        "authors": [],
        "title": "",
    })

    assert reference["authors"] == ["A. Field"]
    assert reference["title"] == (
        "Discovering Statistics Using IBM SPSS Statistics (4th Edition)"
    )
    assert not reference.get("venue")


@pytest.mark.parametrize(
    ("raw", "title", "venue"),
    [
        (
            "[4] Arm Cortex-A Series (Armv7-A) Programmer's Guide.",
            "Arm Cortex-A Series (Armv7-A) Programmer's Guide",
            "",
        ),
        (
            "[2] STM32CubeIDE - Software - STMicroelectronics.",
            "STM32CubeIDE - Software",
            "STMicroelectronics",
        ),
        (
            "[3] STM32G4 Series of mixed-signal MCUs with DSP and FPU "
            "instructions - STMicroelectronics.",
            "STM32G4 Series of mixed-signal MCUs with DSP and FPU instructions",
            "STMicroelectronics",
        ),
    ],
)
def test_source_title_only_entries_recover_title_without_an_author(raw, title, venue):
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": raw,
        "authors": [],
        "title": "",
    })

    assert reference["title"] == title
    assert reference.get("venue", "") == venue


@pytest.mark.parametrize(
    ("raw", "existing_venue", "authors", "title", "venue"),
    [
        (
            "[10] Wenqing Wu, Zhenfang Zhu, Jiangtao Qi, Wenling Wang, "
            "Guangyuan Zhang, Peiyu Liu, A dynamic graph expansion network "
            "for multi-hop knowledge base question answering, Neurocomputing, "
            "Volume 515, 2023, Pages 37-47, ISSN 0925-2312.",
            "",
            [
                "Wenqing Wu", "Zhenfang Zhu", "Jiangtao Qi", "Wenling Wang",
                "Guangyuan Zhang", "Peiyu Liu",
            ],
            "A dynamic graph expansion network for multi-hop knowledge base question answering",
            "Neurocomputing",
        ),
        (
            "[19] Ziyan Li, Haofen Wang, Wenqiang Zhang, Translational relation "
            "embeddings for multi-hop knowledge base question answering, "
            "Journal of Web Semantics, Volume 74, 2022, 100723, ISSN 1570-8268.",
            "[19] Ziyan Li, Haofen Wang, Wenqiang Zhang, Translational relation "
            "embeddings for multi-hop knowledge base question answering, "
            "Journal of Web Semantics, Volume 74, 2022, 100723, ISSN 1570-8268.",
            ["Ziyan Li", "Haofen Wang", "Wenqiang Zhang"],
            "Translational relation embeddings for multi-hop knowledge base question answering",
            "Journal of Web Semantics",
        ),
    ],
)
def test_full_name_volume_journal_recovers_contaminated_fields(
    raw, existing_venue, authors, title, venue
):
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": raw,
        "authors": [],
        "title": "",
        "venue": existing_venue,
    })

    assert reference["authors"] == authors
    assert reference["title"] == title
    assert reference["venue"] == venue


def test_government_act_recovers_source_author_title_and_publisher():
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": (
            "[11] Government of India, The Rights of Persons with Disabilities "
            "(RPwD) Act, 2016, Ministry of Social Justice and Empowerment, "
            "New Delhi, 2016."
        ),
        "authors": [],
        "title": "",
    })

    assert reference["authors"] == ["Government of India"]
    assert reference["title"] == (
        "The Rights of Persons with Disabilities (RPwD) Act, 2016"
    )
    assert reference["venue"] == "Ministry of Social Justice and Empowerment"


def test_technical_report_recovers_organization_author_and_publisher():
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": (
            "[64] ENAEE, 2022. EUR-ACE Framework Standards and Guidelines "
            "(EAFS). Tech. rep., European Network for Accreditation of "
            "Engineering Education."
        ),
        "authors": [],
        "title": "EUR-ACE Framework Standards and Guidelines (EAFS)",
        "venue": "Tech. rep., European Network for Accreditation of Engineering Education",
    })

    assert reference["authors"] == ["ENAEE"]
    assert reference["title"] == "EUR-ACE Framework Standards and Guidelines (EAFS)"
    assert reference["venue"] == "European Network for Accreditation of Engineering Education"


def test_journal_misparsed_as_title_restores_source_title_and_venue():
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": (
            "[25] Cleon Xavier, Luiz Rodrigues, Newarney Costa, Rodrigues Neto, "
            "Gabriel Alves, Taciana Pontual Falc ̃ao, Dragan Gasevic, and Rafael "
            "Ferreira Mello. Empowering instructors with ai: Evaluating the "
            "impact of an ai-driven feedback tool in learning analytics. IEEE "
            "Transactions on Learning Technologies, 2025."
        ),
        "authors": [
            "Cleon Xavier", "Luiz Rodrigues", "Newarney Costa",
            "Rodrigues Neto", "Gabriel Alves", "Taciana Pontual Falc ̃ao",
            "Dragan Gasevic", "Rafael Ferreira Mello",
        ],
        "title": "IEEE Transactions on Learning Technologies",
        "venue": "",
    })

    assert reference["title"] == (
        "Empowering instructors with ai: Evaluating the impact of an ai-driven "
        "feedback tool in learning analytics"
    )
    assert reference["venue"] == "IEEE Transactions on Learning Technologies"


@pytest.mark.parametrize(("tail", "venue"), [
    ('Global Educational Studies Review, vol. VI, no. I, p. 369-375, 2021.',
     'Global Educational Studies Review'),
    ('IJRSI, vol. X, no. IV, pp. 88-93, 2023, doi: 10.51244/IJRSI.2023.10412.',
     'IJRSI'),
    ('IEEE Access, vol. PP, pp. 1-1, 2021, doi: 10.1109/ACCESS.2021.3065248.',
     'IEEE Access'),
])
def test_quoted_journal_with_roman_or_provisional_volume(tail, venue):
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": f'[1] A. Author, "A study," {tail}',
        "authors": ["A. Author"], "title": "A study",
    })
    assert reference["venue"] == venue


@pytest.mark.parametrize("tail", [
    'New York, vol. VI, no. I, pp. 1-20, 2021.',
    'ABCD, vol. X, no. IV, pp. 1-20, 2021, doi: 10.1234/other.2021.',
])
def test_roman_volume_does_not_make_ambiguous_value_a_venue(tail):
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": f'[1] A. Author, "A study," {tail}',
        "authors": ["A. Author"], "title": "A study",
    })
    assert not reference.get("venue")


def test_institutional_report_recovers_missing_author_and_publisher():
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": '[64] ENAEE, 2022. EUR-ACE Framework Standards and Guidelines '
                    '(EAFS). Tech. rep., European Network for Accreditation of Engineering Education.',
        "authors": [], "title": 'EUR-ACE Framework Standards and Guidelines (EAFS)',
    })
    assert reference["authors"] == ["ENAEE"]
    assert reference["venue"] == "European Network for Accreditation of Engineering Education"
    assert reference["year"] == 2022


def test_institutional_report_repairs_title_and_publication_year():
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": '[63] ABET Engineering Accreditation Commission, 2024. '
                    'Criteria for accrediting engineering programs, 2024 - 2025. Tech. rep., ABET.',
        "authors": ["ABET Engineering Accreditation Commission"], "title": "2024",
        "venue": "Criteria for accrediting engineering programs", "year": 2025,
    })
    assert reference["title"] == "Criteria for accrediting engineering programs, 2024 - 2025"
    assert reference["venue"] == "ABET"
    assert reference["year"] == 2024


def test_institutional_report_does_not_overwrite_unrelated_venue():
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": '[64] ENAEE, 2022. A title. Tech. rep., A publisher.',
        "authors": ["ENAEE"], "title": "A title", "venue": "Existing venue",
    })
    assert reference["venue"] == "Existing venue"


def test_author_year_chapter_recovers_source_fields():
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": '[34] Bertella, G., Santini, C., and Cavicchi, A., 2018. '
                    'Bringing together tourism practices: Experiences from the international student '
                    'competition of Fermo (Italy). Routledge, London, book chapter '
                    'Theories of Practice in Tourism, p. 149 - 167.',
        "authors": [], "title": "",
    })
    assert reference["authors"] == ["Bertella, G.", "Santini, C.", "Cavicchi, A."]
    assert reference["title"] == ('Bringing together tourism practices: Experiences from the '
                                  'international student competition of Fermo (Italy)')
    assert reference["venue"] == "Theories of Practice in Tourism"


@pytest.mark.parametrize(("author", "title", "year"), [
    ('Organisation for Economic Co-operation and Development (OECD)',
     'OECD Principles on Artificial Intelligence', 2019),
    ('Ministry of Education Malaysia (MOE)', 'Buku Laporan Kebangsaan TIMSS 2019', 2020),
])
def test_unquoted_institutional_website_recovers_author_and_title(author, title, year):
    from refchecker.utils.text_utils import finalize_reference_field_status, normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": f'[1] {author}, {title}, {year}. '
                    '[Online]. Available: https://example.com/report',
        "authors": [], "title": f'{author}, {title},',
    })
    finalize_reference_field_status(reference)
    assert reference["authors"] == [author]
    assert reference["title"] == title
    assert reference["field_extraction_status"]["venue"] == "absent"


def test_institutional_website_preserves_url_sentinel():
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": '[1] Ministry of Education (MOE), A report, 2020. '
                    '[Online]. Available: https://example.com/report',
        "authors": ["URL Reference"], "title": "A report",
    })
    assert reference["authors"] == ["URL Reference"]


def test_unquoted_arxiv_recovers_source_author_title_and_venue():
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": '[14] F. Asif, F. Sohail, Z. H. Butt, F. Nasir, and N. Asgar, '
                    'Ethical Hacking and its role in Cybersecurity. arXiv. 2024. '
                    'https://doi.org/10.48550/arxiv.2408.16033',
        "authors": [], "title": "",
    })
    assert reference["authors"] == ['F. Asif', 'F. Sohail', 'Z. H. Butt', 'F. Nasir', 'N. Asgar']
    assert reference["title"] == "Ethical Hacking and its role in Cybersecurity"
    assert reference["venue"] == "arXiv"


def test_unquoted_arxiv_does_not_replace_populated_title():
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": '[1] A. Author and B. Author, A title. arXiv. 2024. '
                    'https://doi.org/10.48550/arxiv.2408.16033',
        "authors": [], "title": "Existing title",
    })
    assert reference["title"] == "Existing title"
    assert not reference.get("venue")


@pytest.mark.parametrize(("tail", "venue"), [
    ('in Proc. 11th Int. CDIO Conf., Chengdu, China, 2015.',
     'Proc. 11th Int. CDIO Conf.'),
    ('Proc. EDULEARN18 Conf., Palma de Mallorca, Spain, 2018.',
     'Proc. EDULEARN18 Conf.'),
    ('in Proc. of the IEEE Int. Symp Multimedia, Miami, Florida, 2015.',
     'Proc. of the IEEE Int. Symp Multimedia'),
    ('in Proc. 6th Int. Symp. Engineering Education, Sheffield, 2016.',
     'Proc. 6th Int. Symp. Engineering Education'),
])
def test_located_conference_proceedings_recovers_venue(tail, venue):
    from refchecker.utils.text_utils import normalize_reference_fields

    raw = f'[1] A. Author, "A study," {tail}'
    reference = normalize_reference_fields({
        "raw_text": raw, "authors": ["A. Author"], "title": "A study",
    })
    assert reference["venue"] == venue
    assert reference["authors"] == ["A. Author"]
    assert reference["title"] == "A study"
    populated = normalize_reference_fields({
        "raw_text": raw, "authors": ["A. Author"], "title": "A study",
        "venue": "Existing venue",
    })
    assert populated["venue"] == "Existing venue"


@pytest.mark.parametrize("tail", [
    'in Proc. 28th Int. Conf. Testing, pp. 1999-2008, 2010.',
    'in Proc. 2019 ASEE Annu. Conf., Tampa, FL, USA, Art. no. 25169, 2019.',
    'in Proc. A Study, London, 2020.',
])
def test_located_conference_does_not_treat_pages_or_unmarked_text_as_venue(tail):
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": f'[1] A. Author, "A study," {tail}',
        "authors": ["A. Author"], "title": "A study",
    })
    assert not reference.get("venue")


@pytest.mark.parametrize(("tail", "venue"), [
    ('Frontiers in Psychology 14 (Nov. 2023), p. 1280566. DOI: 10.3389/example.',
     'Frontiers in Psychology'),
    ('Ear, Nose & Throat Journal (2022). DOI: 10.1177/example.',
     'Ear, Nose & Throat Journal'),
    ('Contemporary Psychology: A Journal of Reviews 13 (8 1968), p. 426. '
     'DOI: 10.1037/example.', 'Contemporary Psychology: A Journal of Reviews'),
])
def test_biblatex_journal_venue_recovered_without_overwriting_fields(tail, venue):
    from refchecker.utils.text_utils import normalize_reference_fields

    raw = f'[1] A. Author. "A study". In: {tail}'
    reference = normalize_reference_fields({
        "raw_text": raw, "authors": ["A. Author"], "title": "A study",
    })
    assert reference["venue"] == venue
    assert reference["authors"] == ["A. Author"]
    assert reference["title"] == "A study"
    populated = normalize_reference_fields({
        "raw_text": raw, "authors": ["A. Author"], "title": "A study",
        "venue": "Existing venue",
    })
    assert populated["venue"] == "Existing venue"


def test_biblatex_in_does_not_turn_location_into_venue():
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": '[1] A. Author. "A study". In: New York (2022). '
                    'DOI: 10.1234/example.',
        "authors": ["A. Author"], "title": "A study",
    })
    assert not reference.get("venue")


@pytest.mark.parametrize(("tail", "venue"), [
    ('American Psychologist, vol.55, pp.68--78, 2000.', 'American Psychologist'),
    ('Computers & Education, vol.56, no.3, pp.769-780, 2011.', 'Computers & Education'),
    ('Social Sciences & Humanities Open, vol.8, no.1, pp.100532, 2023.',
     'Social Sciences & Humanities Open'),
    ('Int. Journal of Technology and Design Education, vol.30, p. 919, 2020.',
     'Int. Journal of Technology and Design Education'),
])
def test_volume_and_pages_journal_venue(tail, venue):
    from refchecker.utils.text_utils import normalize_reference_fields

    raw = f'[1] A. Author, "A study," {tail}'
    reference = normalize_reference_fields({
        "raw_text": raw, "authors": ["A. Author"], "title": "A study",
    })
    assert reference["venue"] == venue
    populated = normalize_reference_fields({
        "raw_text": raw, "authors": ["A. Author"], "title": "A study",
        "venue": "Existing venue",
    })
    assert populated["venue"] == "Existing venue"


def test_volume_and_pages_does_not_make_location_venue():
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": '[1] A. Author, "A study," New York, vol.30, p. 919, 2020.',
        "authors": ["A. Author"], "title": "A study",
    })
    assert not reference.get("venue")


def test_inverted_authors_and_journal_repair_corrupted_fields():
    from refchecker.utils.text_utils import normalize_reference_fields

    raw = ('[10] Borchers, C., & Pardos, Z. A. Course load analytics interventions '
           'on higher education course selection: Experimental evidence. Journal of '
           'Learning Analytics, 12(2), 293-311, 2025. doi: 10.18608/jla.2025.8473.')
    reference = normalize_reference_fields({
        "raw_text": raw, "authors": ["Borchers, C.", "& Pardos, Z"],
        "title": "A. Course load analytics interventions on higher education "
                 "course selection: Experimental evidence",
    })
    assert reference["authors"] == ["Borchers, C.", "Pardos, Z. A."]
    assert reference["title"] == (
        "Course load analytics interventions on higher education course selection: Experimental evidence"
    )
    assert reference["venue"] == "Journal of Learning Analytics"


def test_inverted_authors_journal_does_not_replace_populated_venue():
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": '[1] Chi, M. T. H., & Wylie, R. The ICAP Framework. '
                    'Educational Psychologist, 49(4), 219-243, 2014. '
                    'doi: 10.1080/00461520.2014.965823.',
        "authors": ["Existing Author"], "title": "Existing title", "venue": "Existing venue",
    })
    assert reference["authors"] == ["Existing Author"]
    assert reference["title"] == "Existing title"
    assert reference["venue"] == "Existing venue"


def test_paired_quotes_recover_author_title_and_conference():
    from refchecker.utils.text_utils import normalize_reference_fields

    raw = ("[28] Mohammadian, H. D., ''Mapping the future sustainable, through "
           "the 5th wave theory'', in the 2022 IEEE conference, Global Engineering "
           "Education Conference (EDUCON), in Tunis, Tunisia, from 28-31 March 2022")
    reference = normalize_reference_fields({
        "raw_text": raw,
        "authors": ["Mohammadian, H. D.", "''Mapping the future sustainable", "in the"],
        "title": "IEEE conference, Global Engineering Education Conference",
    })
    assert reference["authors"] == ["Mohammadian, H. D."]
    assert reference["title"] == "Mapping the future sustainable, through the 5th wave theory"
    assert reference["venue"] == "Global Engineering Education Conference (EDUCON)"


def test_paired_quotes_preserve_existing_unrelated_venue():
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": "[1] Mohammadian, H. D., ''A study'', in the 2022 IEEE conference, "
                    "Global Engineering Education Conference (EDUCON), in Tunis, Tunisia, "
                    "from 28-31 March 2022",
        "authors": ["Existing Author"], "title": "Existing title", "venue": "Existing venue",
    })
    assert reference["authors"] == ["Existing Author"]
    assert reference["title"] == "Existing title"
    assert reference["venue"] == "Existing venue"


@pytest.mark.parametrize(("tail", "venue"), [
    ('Harvard Business School Press, 169 - 178.', 'Harvard Business School Press'),
    ('Sloan Management Review, 40 (Fall), 33 - 48.', 'Sloan Management Review'),
    ('Strategic Management Journal 22, 493 - 520.', 'Strategic Management Journal'),
])
def test_quoted_author_year_paged_publication_venue(tail, venue):
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": f'[1] Smith, A., (2010), "A study", {tail}',
        "authors": ["Smith, A."], "title": "A study",
    })
    assert reference["venue"] == venue


def test_quoted_author_year_pages_do_not_make_location_venue():
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": '[1] Smith, A., (2010), "A study", New York, 169 - 178.',
        "authors": ["Smith, A."], "title": "A study",
    })
    assert not reference.get("venue")


@pytest.mark.parametrize(("site", "url"), [
    ("cursor.com", "https://cursor.com."),
    ("opal.google", "https://opal.google."),
])
def test_domain_only_named_website_venue(site, url):
    from refchecker.utils.text_utils import normalize_reference_fields

    raw = (f'[1] Organization, "A website," {site}. Accessed: Nov. 10, 2025. '
           f'[Online]. Available: {url}')
    reference = normalize_reference_fields({
        "raw_text": raw, "authors": ["Organization"], "title": "A website",
    })
    assert reference["venue"] == site
    populated = normalize_reference_fields({
        "raw_text": raw, "authors": ["Organization"], "title": "A website",
        "venue": "Existing venue",
    })
    assert populated["venue"] == "Existing venue"


def test_domain_only_named_website_requires_matching_domain():
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": '[1] Organization, "A website," example.com. Accessed: Nov. 10, 2025. '
                    '[Online]. Available: https://other.example.com.',
        "authors": ["Organization"], "title": "A website",
    })
    assert not reference.get("venue")


def test_inverted_arxiv_preprint_repairs_author_and_title():
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": '[23] Chen, E., et al. VTutor: An animated pedagogical agent '
                    'SDK that provides real-time multimodal feedback. arXiv preprint, '
                    'arXiv:2505.06676, 2025.',
        "authors": ["Chen, E"], "title": ", et al",
    })
    assert reference["authors"] == ["Chen, E.", "et al"]
    assert reference["title"] == "VTutor: An animated pedagogical agent SDK that provides real-time multimodal feedback"
    assert reference["venue"] == "arXiv preprint"


def test_unparsed_initial_authors_and_preprint_recover_source_fields():
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": '[16] C. Arora, J. Grundy, and M. Abdelrazek. '
                    'Advancing requirements engineering through generative ai: '
                    'Assessing the role of llms. arXiv preprint arXiv:2310.13976, 2023.',
        "authors": [], "title": "",
    })
    assert reference["authors"] == ["C. Arora", "J. Grundy", "M. Abdelrazek"]
    assert reference["title"] == "Advancing requirements engineering through generative ai: Assessing the role of llms"
    assert reference["venue"] == "arXiv preprint"


@pytest.mark.parametrize("suffix", [
    'arXiv preprint arXiv:2510.24783.',
    'arXiv preprint, no. arXiv:2309.08629, 2023.',
])
def test_source_printed_arxiv_preprint_venue(suffix):
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": f'[1] A. Author, "A study," {suffix}',
        "authors": ["A. Author"], "title": "A study",
    })
    assert reference["venue"] == "arXiv preprint"


def test_arxiv_identifier_alone_does_not_invent_preprint_venue():
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": '[1] A. Author, "A study," arXiv:2510.24783.',
        "authors": ["A. Author"], "title": "A study",
    })
    assert not reference.get("venue")


@pytest.mark.parametrize(("raw", "title"), [
    ('[1] United Nations - World Population Prospects; '
     'https://population.un.org/wpp/', 'World Population Prospects'),
    ('[2] Future jobs | CEDEFOP; '
     'https://www.cedefop.europa.eu/en/tools/skills-intelligence/trend-\n'
     'focus/future-jobs',
     'Future jobs'),
    ('[3] Eurostat: [lfsa_epgaed] Persons in full-time/part-time employment '
     'by educational attainment level',
     '[lfsa_epgaed] Persons in full-time/part-time employment by educational attainment level'),
    ('[7] CEDEFOP Occupations and skills; '
     'https://www.cedefop.europa.eu/en/tools/skills-online-\n'
     'vacancies/occupations/skills',
     'Occupations and skills'),
    ('[27] Google, Google Colaboratory. [Online]. '
     'Available: https://colab.google/', 'Google Colaboratory'),
    ('3. Opportunities and challenges in higher education arising from AI: '
     'A systematic literature review (2020-2024), EnPress Systems, Vol 8, '
     'Issue 11, 2024. [Available online]',
     'Opportunities and challenges in higher education arising from AI: '
     'A systematic literature review (2020-2024)'),
    ('[18] Microsoft. Visual Studio Code. Logiciel. Redmond, WA.',
     'Visual Studio Code'),
    ('[17] Successful STEM Mentoring Initiatives for Underrepresented Students: '
     'A Research-Based Guide for Faculty and Administrators. .',
     'Successful STEM Mentoring Initiatives for Underrepresented Students: '
     'A Research-Based Guide for Faculty and Administrators'),
])
def test_recover_source_confirmed_missing_web_and_title_only_fields(raw, title):
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": raw, "authors": [], "title": "", "venue": "",
    })
    assert reference["title"] == title


def test_ambiguous_institution_only_web_reference_does_not_gain_title():
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": '[5] STATISTA; https://www.statista.com/',
        "authors": [], "title": "", "venue": "",
    })
    assert reference["title"] == ""


@pytest.mark.parametrize(("raw", "title"), [
    ('[1] X. Li, Application of educational technology in cross-cultural '
     'communication teaching [C]//Forest Ridge School, 2025: DOI:10.62381/example.',
     'Application of educational technology in cross-cultural communication teaching'),
    ('[6] T. Abcouwer, E. Takács, T. Schilstra and O. Banga, The Me, We, All '
     'approach: Circular resilience, A.A.A. & O., 2022.',
     'The Me, We, All approach: Circular resilience'),
    ('[4] R. Mendoza-Gonzalez, User-Centered Design Strategies for Massive Open '
     'Online Courses (MOOCs), IGI Global, 2016. ISBN: 978-1-4666-9743-0.',
     'User-Centered Design Strategies for Massive Open Online Courses (MOOCs)'),
    ('[5] S. Elio, J. Herranz, G. Carro Fernandez, A. Contreras, E. Camacho, '
     'F. Loro, and M. Castro, From a Hands-on Chemistry Lab to a Remote Chemistry '
     'Lab: Challenges and Constrains, 01 2018, pp. 125-131.',
     'From a Hands-on Chemistry Lab to a Remote Chemistry Lab: Challenges and Constrains'),
    ('[9] Z. Zhang, M. Inonan, P. Ordu ̃na, and R. Hussein, RHLab: Towards '
     'Implementing a Partial Reconfigurable SDR Remote Lab, 06 2024, pp. 180-192.',
     'RHLab: Towards Implementing a Partial Reconfigurable SDR Remote Lab'),
    ('[6] F. E. Ritter, J. Nerb, E. Lehtinen, and T. M. O\'Shea, In Order to '
     'Learn: How the Sequence of Topics Influences Learning, vol. 2. United '
     'States of America: Oxford University Press, July 2007.',
     'In Order to Learn: How the Sequence of Topics Influences Learning'),
    ('[5] J. Clerk Maxwell, A Treatise on Electricity and Magnetism, 3rd ed., '
     'vol. 2. Oxford: Clarendon, 1892, pp. 68-73.',
     'A Treatise on Electricity and Magnetism'),
])
def test_recover_source_title_after_initial_author_lists(raw, title):
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": raw, "authors": [], "title": "", "venue": "",
    })
    assert reference["title"] == title


@pytest.mark.parametrize(("raw", "title"), [
    ('[1] UNESCO, Girls\' and Women\'s Education in Science, Technology, '
     'Engineering and Mathematics (STEM), UNESCO, Paris, France, 2025. '
     '[Online]. Available: https://example.com/stem.',
     'Girls\' and Women\'s Education in Science, Technology, Engineering and Mathematics (STEM)'),
    ('[2] World Economic Forum, The Gender Gap in Science and Technology, in '
     'Numbers, Geneva, Switzerland, 2021.',
     'The Gender Gap in Science and Technology, in Numbers'),
    ('[5] Investing in Climate for Growth and Development. OECD Publishing, '
     '2025. doi: 10.1787/16b7cbc7-en.',
     'Investing in Climate for Growth and Development'),
    ('[24] Institution of Engineering and Technology, Accreditation of Higher '
     'Education Programmes (AHEP), 4th Edition, IET, 2020.',
     'Accreditation of Higher Education Programmes (AHEP)'),
])
def test_recover_source_confirmed_corporate_publication_titles(raw, title):
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": raw, "authors": [], "title": "", "venue": "",
    })
    assert reference["title"] == title


@pytest.mark.parametrize(("raw", "title"), [
    ('[13] St ́ephane Badreau et Jean-Louis Boulanger. Ing ́enierie des '
     'exigences : M ́ethodes et bonnes pratiques pour construire et maintenir '
     'un r ́ef ́erentiel. Dunod, Paris, 2014.',
     'Ing ́enierie des exigences : M ́ethodes et bonnes pratiques pour construire et maintenir un r ́ef ́erentiel'),
    ('[19] N\'goran, R., Tetchueng, J.-L., Pandry, G., Kermarrec, Y. and '
     'Asseu, O. Trust Assessment Model Based on a Zero Trust Strategy in a '
     'Community Cloud Environment. Engineering, 14, 479-496. '
     'https://doi.org/10.4236/eng.2022.1411036',
     'Trust Assessment Model Based on a Zero Trust Strategy in a Community Cloud Environment'),
    ('[21] Kermarrec, Y., Pautet, L. Ada reusable software components for '
     'teaching distributed systems. In: D ́ıaz-Herrera, J.L. (eds) Software '
     'Engineering Education. CSEE 1994.',
     'Ada reusable software components for teaching distributed systems'),
    ('[22] Kapur, M. Productive failure. Cognition and Instruction, 26, '
     '379-424. 2008 doi:10.1080/07370000802212669.',
     'Productive failure'),
    ('[23] Yvon Kermarrec Strengthening Maritime Cyber Resilience: The '
     'Imperative Need for a Global and Cooperative MOOC Initiative CRISIS '
     '2025 conference, University of Quebec en Ouataouais.',
     'Strengthening Maritime Cyber Resilience: The Imperative Need for a Global and Cooperative MOOC Initiative'),
    ('[24] G Booch Software engineering with Ada Benjamin/Cummings '
     'Publishing Company, 1987 - 580 pages Software - Software Engineering.',
     'Software engineering with Ada'),
    ('[25] Stan Kurkovsky, Stephanie Ludi, Linda Clark Active Learning with '
     'LEGO for Software Requirements SIGCSE \'19: Proceedings of the 50th ACM '
     'Technical Symposium on Computer Science Education Pages 218 - 224',
     'Active Learning with LEGO for Software Requirements'),
    ('[26] D. L ́opez-fern ́andez, A. Gordillo, F. Ortega, A. Yagüe and '
     'E. Tovar LEGO® Serious Play in Software Engineering Education, in '
     'IEEE Access, vol. 9, pp. 103120-103131, 2021, doi: 10.1109/ACCESS.2021.',
     'LEGO® Serious Play in Software Engineering Education'),
    ('[13] C. Palmer, B. Roullier, M. Aamir, L. Stella, U. Diala, A. Anjum, '
     'F. Mcquade, K. Cox, and A. Calvert, Virtual Reality Based Digital Twin '
     'System for Remote Laboratories and Online Practical Learning, 08 2021.',
     'Virtual Reality Based Digital Twin System for Remote Laboratories and Online Practical Learning'),
    ('[9] L. S. Vygotsky, Zone of Proximal Development. Online: Research-\nGate.',
     'Zone of Proximal Development'),
    ('[7] M. Apiola, S. L ́opez-Pernas, and M. Saqr, Past, Present and Future\n'
     'of Computing Education Research: A Global Perspective.\nSpringer\nNature, 2023.',
     'Past, Present and Future of Computing Education Research: A Global Perspective'),
    ('[21] Su, F. E., Mathematics for Human Flourishing, Yale University Press,\n'
     '2020.',
     'Mathematics for Human Flourishing'),
    ('[9] UN \'Bodyright\' campaign. https://news.un.org/en/story/2021/12/1106972, 2021',
     'UN \'Bodyright\' campaign'),
    ('[12] Intensification of efforts to eliminate all forms of violence '
     'against women and girls: technology-facilitated violence against women '
     'and girls - Report of the Secretary-General (A/79/500), 2024',
     'Intensification of efforts to eliminate all forms of violence against women and girls: technology-facilitated violence against women and girls'),
    ('[17] О.А. Oreshkina, Yu. А. Safonova. Generative AI as a Technology to '
     'Support Hearing-Impaired Students in Inclusive Programs of a Technical '
     'University. Proceedings of the International 2025 MIPRO 48th ICT and Electronics Convention.',
     'Generative AI as a Technology to Support Hearing-Impaired Students in Inclusive Programs of a Technical University'),
    ('[23] A. Dominguez, F. J. García-Peñalvo, G. Zavala, A. García-Holgado, '
     'y H. Alarcón, Mujeres en la educación universitaria de ciencia, '
     'ingeniería, tecnología y matemáticas. en Universidad. Accedido: '
     '16 de noviembre de 2025. [Online]. Available en: https://example.com/book',
     'Mujeres en la educación universitaria de ciencia, ingeniería, tecnología y matemáticas'),
])
def test_recover_additional_source_confirmed_titles(raw, title):
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": raw, "authors": [], "title": "", "venue": "",
    })
    assert reference["title"] == title


@pytest.mark.parametrize(("raw", "venue"), [
    ('[7] OpenAI, "Introducing study mode," OpenAI, Jul. 29, 2025. '
     'Accessed: Nov. 10, 2025. [Online]. Available: https://openai.com/index/study-mode.',
     'OpenAI'),
    ('[8] Google, "Guided Learning," Google Blog, Aug. 6, 2025. '
     'Accessed: Nov. 10, 2025. [Online]. Available: https://blog.google/guided- learning.',
     'Google Blog'),
    ('[5] H. D. Mohammadian. A study. In the Proceeding of IEEE Global '
     'Engineering Education Conference (EDUCON). 17-20 April. Tenerife, Spain. 2018',
     'IEEE Global Engineering Education Conference (EDUCON)'),
    ('[21] H. D. Mohammadian. A study. In the Proceeding of IEEE Global '
     'Engineering Education Conference (EDUCON). April. Porto, Portugal. 2020.',
     'IEEE Global Engineering Education Conference (EDUCON)'),
])
def test_dated_website_and_conference_recover_only_missing_venue(raw, venue):
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": raw, "authors": ["A. Author"], "title": "Original",
    })
    assert reference["authors"] == ["A. Author"]
    assert reference["title"] == "Original"
    assert reference["venue"] == venue
    populated = normalize_reference_fields({
        "raw_text": raw, "authors": ["A. Author"], "title": "Original",
        "venue": "Existing venue",
    })
    assert populated["venue"] == "Existing venue"


@pytest.mark.parametrize("raw", [
    '[1] A. Author, "A study," Jul. 29, 2025. Accessed: Nov. 10, 2025. '
    '[Online]. Available: https://example.com/study.',
    '[1] A. Author. A study. In the Proceeding of New York. '
    '17-20 April. Tenerife, Spain. 2018.',
])
def test_dated_website_and_conference_do_not_invent_venues(raw):
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": raw, "authors": ["A. Author"], "title": "Original",
    })
    assert not reference.get("venue")


@pytest.mark.parametrize(("raw", "author", "title", "venue"), [
    ('[2] R. E. Boyatzis, The Competent Manager: A Model for Effective '
     'Performance, New York: John Wiley & Sons, 1982.',
     'R. E. Boyatzis', 'The Competent Manager: A Model for Effective Performance',
     'John Wiley & Sons'),
    ('[11] E. L. Boyer, Scholarship Reconsidered: Priorities of the Professoriate, '
     'Princeton, NJ: Carnegie Foundation for the Advancement of Teaching, 1990.',
     'E. L. Boyer', 'Scholarship Reconsidered: Priorities of the Professoriate',
     'Carnegie Foundation for the Advancement of Teaching'),
])
def test_unparsed_city_publisher_books_recover_source_fields(raw, author, title, venue):
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({"raw_text": raw, "authors": [], "title": ""})
    assert reference["authors"] == [author]
    assert reference["title"] == title
    assert reference["venue"] == venue


def test_city_publisher_book_does_not_replace_existing_fields():
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": '[2] M. Eraut, Developing Professional Knowledge and '
                    'Competence, London: Routledge, 1994.',
        "authors": ["M. Eraut"], "title": "Existing title",
    })
    assert reference["title"] == "Existing title"
    assert not reference.get("venue")


@pytest.mark.parametrize(("raw", "authors", "title", "venue"), [
    (
        '[6] B. S. Bloom, M. D. Englehart, E. J. Furst, W. H. Hill, and '
        'D. R. Krathwohl, Taxonomy of Educational Objectives: Handbook I: '
        'The Cognitive Domain. David McKay Company, Inc., 1956.',
        ['B. S. Bloom', 'M. D. Englehart', 'E. J. Furst', 'W. H. Hill', 'D. R. Krathwohl'],
        'Taxonomy of Educational Objectives: Handbook I: The Cognitive Domain',
        'David McKay Company, Inc',
    ),
    (
        '[65] D. H. Jonassen, Computers in the classroom: Mindtools for critical '
        'thinking. Prentice-Hall, Inc., 1996.',
        ['D. H. Jonassen'],
        'Computers in the classroom: Mindtools for critical thinking',
        'Prentice-Hall, Inc',
    ),
    (
        '[11] R. Pekrun and A. Frenzel, The Control-Value Theory of Achievement '
        'Emotions. An Integrative Approach to Emotions in Education. Elsevier Inc., 2007.',
        ['R. Pekrun', 'A. Frenzel'],
        'The Control-Value Theory of Achievement Emotions. An Integrative Approach to Emotions in Education',
        'Elsevier Inc',
    ),
    (
        "[14] A. Downey, Think DSP: digital signal processing in Python. "
        "O'Reilly Media, Inc., 2016.",
        ['A. Downey'],
        'Think DSP: digital signal processing in Python',
        "O'Reilly Media, Inc",
    ),
    (
        '[54] A. Moore and R. Wilson, FPGAs for Dummies. 2nd Intel Special ed., '
        'Hoboken, NJ: John Wiley & Sons, Inc., 2017.',
        ['A. Moore', 'R. Wilson'],
        'FPGAs for Dummies',
        'John Wiley & Sons, Inc',
    ),
])
def test_book_with_abbreviated_publisher_recovers_source_fields(raw, authors, title, venue):
    checker = ArxivReferenceChecker(llm_config={"disabled": True})

    reference = checker._parse_quoted_numbered_references([raw])[0]

    assert reference["authors"] == authors
    assert reference["title"] == title
    assert reference["venue"] == venue


def test_book_parser_does_not_treat_author_suffix_as_publisher():
    from refchecker.utils.biblatex_parser import extract_book_citation_fields

    assert extract_book_citation_fields(
        '[1] A. Author, "A study." Journal, Inc., 2020.'
    ) is None


@pytest.mark.parametrize(("raw", "existing_authors", "authors", "title", "venue"), [
    (
        '[1] Kolb, D. A., 1984. Experiential Learning: Experience as the Source '
        'of Learning and Development. Prentice Hall, Englewood Cliffs, NJ.',
        ['Kolb, D'], ['Kolb, D. A.'],
        'Experiential Learning: Experience as the Source of Learning and Development',
        'Prentice Hall',
    ),
    (
        '[50] de Vaus, D., 2013. Surveys in Social Research, 6th ed. Routledge, London.',
        [], ['de Vaus, D.'], 'Surveys in Social Research', 'Routledge',
    ),
])
def test_inverted_author_year_book_recovers_missing_fields(raw, existing_authors, authors, title, venue):
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": raw, "authors": existing_authors, "title": "", "venue": "",
    })
    assert reference["authors"] == authors
    assert reference["title"] == title
    assert reference["venue"] == venue


def test_inverted_author_year_recovery_does_not_override_ambiguous_source():
    from refchecker.utils.text_utils import normalize_reference_fields

    raw = '[1] Kolb, D. A., 1984. A book. Prentice Hall, London.'
    reference = normalize_reference_fields({
        "raw_text": raw, "authors": ["Another Author"], "title": "", "venue": "",
    })
    assert reference["authors"] == ["Another Author"]
    assert not reference["title"]
    assert not reference["venue"]
    quoted = normalize_reference_fields({
        "raw_text": '[2] Zande, J. M., 2011. "A paper". Conference, London.',
        "authors": [], "title": "", "venue": "",
    })
    assert not quoted["venue"]


def test_online_proceedings_uses_publication_year_not_page_number():
    from refchecker.utils.text_utils import normalize_reference_fields

    raw = (
        '[7] T. Brown et al., "Language Models are Few-Shot Learners," in Advances '
        'in Neural Information Processing Systems, Curran Associates, Inc., '
        '2020, pp. 1877-1901. Accessed: June 07, 2025. [Online]. Available: '
        'https://example.org/article'
    )
    reference = normalize_reference_fields({
        "raw_text": raw, "authors": ["T. Brown", "et al"],
        "title": "Language Models are Few-Shot Learners", "year": 1901,
        "venue": "Advances in Neural Information Processing Systems, Curran Associates, Inc., 2020",
    })
    assert reference["year"] == 2020
    assert reference["venue"] == "Advances in Neural Information Processing Systems"


def test_source_wrapped_compound_restores_hyphen_lost_by_parser():
    from refchecker.utils.text_utils import normalize_reference_fields

    raw = '[21] D. Nicol, "Formative assessment and self-\nregulated learning," Journal, 2006.'
    reference = normalize_reference_fields({
        "raw_text": raw, "authors": ["D. Nicol"],
        "title": "Formative assessment and selfregulated learning",
    })
    assert reference["title"] == "Formative assessment and self-regulated learning"


def test_source_wrapped_compound_does_not_guess_between_duplicate_occurrences():
    from refchecker.utils.text_utils import normalize_reference_fields

    raw = '[1] A. Author, "self-\nassessment and selfassessment," Journal, 2024.'
    reference = normalize_reference_fields({
        "raw_text": raw, "authors": ["A. Author"],
        "title": "selfassessment and selfassessment",
    })
    assert reference["title"] == "selfassessment and selfassessment"


def test_unsigned_web_citation_does_not_treat_month_as_venue():
    from refchecker.utils.text_utils import normalize_reference_fields

    raw = ('[7] "INVEST Alliance," Jul. 2021. Accessed: Oct. 15, 2025. '
           '[Online]. Available: https://www.invest-alliance.eu/')
    reference = normalize_reference_fields({
        "raw_text": raw, "authors": [], "title": "INVEST Alliance", "venue": "Jul",
        "extraction_warnings": [
            "Author could not be extracted; review the source text.", "Other warning",
        ],
    })
    assert reference["authors"] == []
    assert not reference["venue"]
    assert reference["field_extraction_status"] == {"authors": "absent", "venue": "absent"}
    assert reference["extraction_warnings"] == ["Other warning"]


def test_signed_web_citation_does_not_assert_missing_author():
    from refchecker.utils.text_utils import normalize_reference_fields

    raw = ('[7] A. Author, "INVEST Alliance," Jul. 2021. Accessed: Oct. 15, 2025. '
           '[Online]. Available: https://www.invest-alliance.eu/')
    reference = normalize_reference_fields({
        "raw_text": raw, "authors": [], "title": "INVEST Alliance",
    })
    assert reference["field_extraction_status"]["authors"] == "uncertain"


@pytest.mark.parametrize(("author", "parsed_author"), [
    ("AI Fairness 360", "AI Fairness"),
    ("mlr3fairness", "mlrfairness"),
    ("K-12 Computer Science Framework Steering Committee", "K- Computer Science Framework Steering Committee"),
])
def test_signed_web_citation_preserves_digits_in_author(author, parsed_author):
    from refchecker.utils.text_utils import normalize_reference_fields

    raw = f'[1] {author}, "A title," 2024. [Online]. Available: https://example.org/'
    reference = normalize_reference_fields({
        "raw_text": raw, "authors": [parsed_author], "title": "A title",
    })
    assert reference["authors"] == [author]
    assert reference["field_extraction_status"]["venue"] == "absent"


def test_signed_web_citation_does_not_replace_mismatched_author():
    from refchecker.utils.text_utils import normalize_reference_fields

    raw = '[1] Team 360, "A title," 2024. [Online]. Available: https://example.org/'
    reference = normalize_reference_fields({
        "raw_text": raw, "authors": ["Someone Else"], "title": "A title",
    })
    assert reference["authors"] == ["Someone Else"]


def test_direct_url_citation_preserves_digits_in_source_author():
    from refchecker.utils.text_utils import normalize_reference_fields

    raw = (
        '[11] PX4 Development Team, "Px4 autopilot: Open source flight control '
        'software," https://px4.io/, accessed: 2026-01-15.'
    )
    reference = normalize_reference_fields({
        "raw_text": raw, "authors": ["PX Development Team"], "title": "Px4 autopilot",
    })
    assert reference["authors"] == ["PX4 Development Team"]

    reference = normalize_reference_fields({
        "raw_text": raw, "authors": ["Other Team"], "title": "Px4 autopilot",
    })
    assert reference["authors"] == ["Other Team"]


def test_repeated_author_marker_uses_complete_preceding_source_authors():
    from refchecker.utils.text_utils import finalize_reference_fields

    refs = [
        {"raw_text": '[1] C. Romero and S. Ventura, "First work," 2010.',
         "authors": ["C. Romero", "S. Ventura"], "title": "First work"},
        {"raw_text": '[2] --, "Second work," 2020.',
         "authors": ["–"], "title": "Second work"},
    ]
    assert finalize_reference_fields(refs)[1]["authors"] == ["C. Romero", "S. Ventura"]
    assert refs[1]["raw_text"].startswith("[2] --")


def test_repeated_author_marker_after_unquoted_book():
    from refchecker.utils.text_utils import finalize_reference_fields

    refs = [
        {"raw_text": "[3] P. J. Denning and M. Tedre, Computational thinking.\nMit Press, 2019.",
         "authors": ["P. J. Denning", "M. Tedre"], "title": "Computational thinking"},
        {"raw_text": '[4] --, "Another work," 2021.',
         "authors": ["–"], "title": "Another work"},
    ]
    assert finalize_reference_fields(refs)[1]["authors"] == ["P. J. Denning", "M. Tedre"]


@pytest.mark.parametrize(
    ("source", "authors"),
    [
        ('[1] C. Romero and S. Ventura, "First work," 2010.', ["C. Romero"]),
        ('[1] A. B. for Engineering and T. (ABET), "First work," 2010.',
         ["A. B. for Engineering", "T."]),
        ('[3] C. Romero, "First work," 2010.', ["C. Romero"]),
        ('[1] C. Romero, "First work," 2010.', ["Unknown Author"]),
        ('[1] C. Romero and S. Ventura, First work. Publisher, 2010.', ["C. Romero"]),
    ],
)
def test_repeated_author_marker_does_not_guess_prior_authors(source, authors):
    from refchecker.utils.text_utils import finalize_reference_fields

    refs = [
        {"raw_text": source, "authors": authors, "title": "First work"},
        {"raw_text": '[2] --, "Second work," 2020.',
         "authors": ["–"], "title": "Second work"},
    ]
    result = finalize_reference_fields(refs)[1]
    assert result["authors"] == []
    assert result["field_extraction_status"]["authors"] == "uncertain"
    assert result["raw_text"].startswith("[2] --")


def test_unquoted_volume_journal_recovers_ampersand_author_list():
    from refchecker.utils.text_utils import normalize_reference_fields

    raw = (
        "[17] Kim, J., Lee, H. & Cho, Y.H. Learning design to support student-AI "
        "collaboration: perspectives of leading teachers for AI in education. "
        "Educ Inf Technol 27, 6069-6104 (2022)"
    )
    result = normalize_reference_fields({
        "raw_text": raw, "authors": ["Kim, J"], "title": ", Lee, H",
    })
    assert result["authors"] == ["Kim, J.", "Lee, H.", "Cho, Y.H."]
    assert result["title"] == (
        "Learning design to support student-AI collaboration: "
        "perspectives of leading teachers for AI in education"
    )
    assert result["venue"] == "Educ Inf Technol"


def test_comma_journal_with_dated_page_range_recovers_venue():
    from refchecker.utils.text_utils import normalize_reference_fields

    raw = ('[43] A. Author, "A study," Technology, Pedagogy and Education, '
           'pp. 1-19, Mar. 2025.')
    result = normalize_reference_fields({
        "raw_text": raw, "authors": ["A. Author"], "title": "A study",
    })
    assert result["venue"] == "Technology, Pedagogy and Education"
    populated = normalize_reference_fields({
        "raw_text": raw, "authors": ["A. Author"], "title": "A study",
        "venue": "Already extracted",
    })
    assert populated["venue"] == "Already extracted"
    ambiguous = normalize_reference_fields({
        "raw_text": raw.replace("Technology, Pedagogy and Education", "Paris, France"),
        "authors": ["A. Author"], "title": "A study",
    })
    assert not ambiguous.get("venue")


@pytest.mark.parametrize("suffix", [
    "2024.",
    "2025, doi: 10.1080/10494820.2025.2514372.",
])
def test_early_access_journal_recovers_source_venue(suffix):
    from refchecker.utils.text_utils import normalize_reference_fields

    raw = f'[1] A. Author, "A study," Active Learning in Higher Education, early access, {suffix}'
    reference = normalize_reference_fields({
        "raw_text": raw, "authors": ["A. Author"], "title": "A study",
    })
    assert reference["venue"] == "Active Learning in Higher Education"
    assert reference["journal"] == reference["venue"]

    populated = normalize_reference_fields({
        "raw_text": raw, "authors": ["A. Author"], "title": "A study",
        "venue": "Already extracted",
    })
    assert populated["venue"] == "Already extracted"


@pytest.mark.parametrize("pagination", ["103427", "e3208", "pp. 1-11"])
def test_quoted_article_journal_recovers_printed_venue(pagination):
    from refchecker.utils.text_utils import normalize_reference_fields

    raw = f'[12] A. Author, "A study." Teaching and Teacher Education, 105, 2021, {pagination}.'
    reference = normalize_reference_fields({
        "raw_text": raw, "authors": ["A. Author"], "title": "A study",
    })
    assert reference["venue"] == "Teaching and Teacher Education"
    populated = normalize_reference_fields({
        "raw_text": raw, "authors": ["A. Author"], "title": "A study",
        "venue": "Already extracted",
    })
    assert populated["venue"] == "Already extracted"
    ambiguous = normalize_reference_fields({
        "raw_text": raw.replace("Teaching and Teacher Education", "Paris"),
        "authors": ["A. Author"], "title": "A study",
    })
    assert not ambiguous.get("venue")


def test_source_doi_repairs_suffix_only_identifier_and_resolver():
    from refchecker.utils.text_utils import normalize_reference_fields

    raw = "[5] A. Author. A title. Journal. 10.3389/feduc.2022.840618."
    result = normalize_reference_fields({
        "raw_text": raw, "doi": "feduc.2022.840618",
        "url": "https://doi.org/feduc.2022.840618",
    })
    assert result["doi"] == "10.3389/feduc.2022.840618"
    assert result["url"] == "https://doi.org/10.3389/feduc.2022.840618"

    ambiguous = normalize_reference_fields({
        "raw_text": raw + " 10.1234/feduc.2022.840618.",
        "doi": "feduc.2022.840618", "url": "https://example.org/article",
    })
    assert ambiguous["doi"] == "feduc.2022.840618"
    assert ambiguous["url"] == "https://example.org/article"


def test_missing_source_url_is_recovered_without_guessing_between_links():
    from refchecker.utils.text_utils import normalize_reference_fields

    raw = "[8] FFG Homepage, https://www.ffg.at/en/program/innovation-labs-maker-\nspaces-0, last accessed on 2025/07/06"
    result = normalize_reference_fields({"raw_text": raw, "authors": [], "title": ""})
    assert result["url"] == "https://www.ffg.at/en/program/innovation-labs-maker-spaces-0"

    ambiguous = normalize_reference_fields({
        "raw_text": "[1] https://example.org/one and https://example.org/two",
        "authors": [], "title": "",
    })
    assert not ambiguous.get("url")


def test_truncated_source_url_and_its_doi_are_restored():
    from refchecker.utils.text_utils import normalize_reference_fields

    url = "https://www.tandfonline.com/doi/abs/10.1080/15377903.2012.643755"
    result = normalize_reference_fields({
        "raw_text": f"[6] A. Author. A title. {url}, 2012",
        "url": url.removesuffix(".643755"),
        "doi": "10.1080/15377903.2012",
    })
    assert result["url"] == url
    assert result["doi"] == "10.1080/15377903.2012.643755"


def test_truncated_source_url_requires_unique_matching_complete_url():
    from refchecker.utils.text_utils import normalize_reference_fields

    old = "https://example.org/article"
    for raw in (
        "[1] https://example.org/article-extended and https://example.org/other",
        "[1] https://example.org/article-",
        "[1] https://different.example.org/article-extended",
    ):
        assert normalize_reference_fields({"raw_text": raw, "url": old})["url"] == old


def test_normalization_recovers_series_formatted_proceedings():
    from refchecker.utils.text_utils import normalize_reference_fields

    raw = (
        '[13] J. N. Matthews, "Hands-on approach to teaching computer networking '
        'using packet traces," in Proceedings of the 6th Conference on Information '
        "Technology Education, ser. SIGITE '05. New York, NY, USA: Association for "
        "Computing Machinery, 2005, p. 361-367. [Online]. Available: "
        "https://doi.org/10.1145/1095714.1095777"
    )
    reference = normalize_reference_fields({
        "raw_text": raw, "authors": ["J. N. Matthews"],
        "title": "Hands-on approach to teaching computer networking using packet traces",
    })
    assert reference["venue"] == "Proceedings of the 6th Conference on Information Technology Education"
    assert reference["authors"] == ["J. N. Matthews"]
    assert reference["year"] == 2005


def test_normalization_recovers_named_site_without_inventing_a_year():
    from refchecker.utils.text_utils import normalize_reference_fields

    raw = (
        '[8] H. Naveed et al., "A Comprehensive Overview of Large Language Models," '
        "arXiv.org. Accessed: June 07, 2025. [Online]. Available: "
        "https://arxiv.org/abs/2307.06435v10"
    )
    reference = normalize_reference_fields({
        "raw_text": raw, "authors": ["H. Naveed", "et al"],
        "title": "A Comprehensive Overview of Large Language Models", "year": None,
    })
    assert reference["venue"] == "arXiv.org"
    assert reference["year"] is None


@pytest.mark.parametrize(("raw", "venue", "year"), [
    (
        '[4] N. Cardwell, "BBR Congestion Control," Internet Engineering Task '
        'Force, Internet-Draft draft-cardwell-iccrg-bbr-congestion-control-02, '
        'Mar. 2022, work in Progress. [Online]. Available: https://example.org/draft',
        "Internet Engineering Task Force", 2022,
    ),
    (
        '[47] R. K. Jain, "A quantitative measure of fairness," DEC Research '
        'Report, no. TR-301, 1984, digital Equipment Corporation, Accessed: '
        '2025-11-12. [Online]. Available: https://example.org/fairness.pdf',
        "DEC Research Report", 1984,
    ),
])
def test_normalization_recovers_draft_and_report_venues(raw, venue, year):
    from refchecker.utils.text_utils import normalize_reference_fields

    reference = normalize_reference_fields({
        "raw_text": raw, "authors": ["A. Author"], "title": "Original",
    })
    assert reference["venue"] == venue
    assert reference["year"] == year
    assert reference["authors"] == ["A. Author"]
    assert reference["title"] == "Original"


def test_normalization_recovers_edition_book_authors_title_and_publisher():
    from refchecker.utils.text_utils import normalize_reference_fields

    raw = (
        "[9] J. F. Kurose and K. W. Ross, Computer Networking: A Top-Down "
        "Approach, 8th ed. Pearson, 2021, global Edition."
    )
    reference = normalize_reference_fields({
        "raw_text": raw, "authors": ["J. F. Kurose", "K. W"],
        "title": "Ross, Computer Networking: A Top-Down Approach, 8th ed",
    })
    assert reference["authors"] == ["J. F. Kurose", "K. W. Ross"]
    assert reference["title"] == "Computer Networking: A Top-Down Approach"
    assert reference["venue"] == "Pearson"
    assert reference["year"] == 2021


def test_normalization_recovers_plain_journal_and_complete_author_names():
    from refchecker.utils.text_utils import normalize_reference_fields

    raw = (
        "[16] Hongli Li, Yao Xiong, Xiaojiao Zang, Mindy L. Kornhaber, Youngsun "
        "Lyu, Kyung Sun Chung, and Hoi K. Suen. Peer assessment in the digital "
        "age: A meta-analysis comparing peer and teacher ratings. Assessment & "
        "Evaluation in Higher Education, 41(2):245-264, 2016."
    )
    reference = normalize_reference_fields({
        "raw_text": raw, "authors": ["Hongli Li"],
        "title": "Kornhaber, Youngsun Lyu, Kyung Sun Chung, and Hoi K",
    })
    assert reference["authors"] == [
        "Hongli Li", "Yao Xiong", "Xiaojiao Zang", "Mindy L. Kornhaber",
        "Youngsun Lyu", "Kyung Sun Chung", "Hoi K. Suen",
    ]
    assert reference["title"] == (
        "Peer assessment in the digital age: A meta-analysis comparing peer and teacher ratings"
    )
    assert reference["venue"] == "Assessment & Evaluation in Higher Education"
    assert reference["year"] == 2016


def test_plain_journal_recovery_does_not_split_initials_as_complete_names():
    from refchecker.utils.text_utils import _recover_unambiguous_numbered_fields

    raw = (
        '[1] N. T. More, B. Sapre, and P. Chawan, "Requirements engineering", '
        'International Journal of Internet Computing, 1(2):4-8, 2011.'
    )
    reference = {"authors": ["N. T. More"], "title": "Requirements engineering", "venue": ""}
    before = dict(reference)
    _recover_unambiguous_numbered_fields(reference, raw)
    assert reference == before


def test_normalization_recovers_plain_chapter_venue_without_changing_title():
    from refchecker.utils.text_utils import normalize_reference_fields

    raw = (
        "[8] Alvaro Becerra and Ruth Cobos. A guidance tool. In 2024 IEEE "
        "Global Engineering Education Conference (EDUCON), pages 1-8. IEEE, 2024."
    )
    reference = normalize_reference_fields({
        "raw_text": raw, "authors": ["Alvaro Becerra", "Ruth Cobos"],
        "title": "A guidance tool",
    })
    assert reference["venue"] == "2024 IEEE Global Engineering Education Conference (EDUCON)"
    assert reference["title"] == "A guidance tool"
    assert reference["authors"] == ["Alvaro Becerra", "Ruth Cobos"]


def test_normalization_separates_plain_title_from_journal_and_year():
    from refchecker.utils.text_utils import normalize_reference_fields

    raw = (
        "[19] John A Ross. The reliability, validity, and utility of self-assessment. "
        "Practical Assessment, Research & Evaluation, 2006."
    )
    reference = normalize_reference_fields({
        "raw_text": raw, "authors": ["John A Ross"],
        "title": "Practical Assessment, Research & Evaluation",
    })
    assert reference["authors"] == ["John A Ross"]
    assert reference["title"] == "The reliability, validity, and utility of self-assessment"
    assert reference["venue"] == "Practical Assessment, Research & Evaluation"
    assert reference["year"] == 2006


def test_normalization_separates_plain_journal_title_and_page_range():
    from refchecker.utils.text_utils import normalize_reference_fields

    raw = (
        "[20] Juuso Henrik Nieminen and David Boud. Student self-assessment: "
        "a meta-review of five decades of research. Assessment in Education: "
        "Principles, Policy & Practice, pages 1-25, 2025."
    )
    reference = normalize_reference_fields({
        "raw_text": raw,
        "authors": ["Juuso Henrik Nieminen", "David Boud. Student self-assessment"],
        "title": "Assessment in Education: Principles, Policy & Practice, pages 1-25",
    })
    assert reference["authors"] == ["Juuso Henrik Nieminen", "David Boud"]
    assert reference["title"] == "Student self-assessment: a meta-review of five decades of research"
    assert reference["venue"] == "Assessment in Education: Principles, Policy & Practice"
    assert reference["year"] == 2025


def test_normalization_does_not_assume_last_publisher_component_is_location():
    from refchecker.utils.text_utils import normalize_reference_fields

    raw = "[6] Sen,J. A title. Chapter: 1. Publisher: Press, Group. 2012."
    assert not normalize_reference_fields({"raw_text": raw}).get("venue")


def test_normalization_recovers_single_author_available_at_citation():
    from refchecker.utils.text_utils import normalize_reference_fields

    raw = (
        "[15] Hayatul,Y. Society 5.0 for Supper Smart Country. 2019. "
        "Available at: https://www.researchgate.net/publication/331521659"
    )
    result = normalize_reference_fields({
        "raw_text": raw, "title": "Smart Country", "authors": ["Hayatul, Y"],
    })

    assert result["authors"] == ["Hayatul,Y."]
    assert result["title"] == "Society 5.0 for Supper Smart Country"
    assert not result.get("venue")
    assert result["year"] == 2019
    assert result["raw_text"] == raw


@pytest.mark.parametrize(
    ("raw", "authors", "title"),
    [
        (
            "[27] Doost Mohammadian, H. SMEs in Energy Sector - Ubiquitous Blue-\n"
            "Green Energy Management; Volume 1 Foundation1, Fachhochschule des "
            "Mittelstands (FHM) - University of Applied Sciences - Bielefeld - 2020",
            ["Doost Mohammadian, H."],
            "SMEs in Energy Sector - Ubiquitous Blue-Green Energy Management; Volume 1 Foundation1",
        ),
        (
            "[30] Doost Mohammadian, H. Rezaie, F. Global SMEs; Volume 2 SMEs "
            "4.0 to Gain Sustainable Development Globally, Fachhochschule des "
            "Mittelstands (FHM) - University of Applied Sciences - Bielefeld - 2020",
            ["Doost Mohammadian, H.", "Rezaie, F."],
            "Global SMEs; Volume 2 SMEs 4.0 to Gain Sustainable Development Globally",
        ),
    ],
)
def test_normalization_recovers_institutional_book_citations(raw, authors, title):
    from refchecker.utils.text_utils import normalize_reference_fields

    result = normalize_reference_fields({
        "raw_text": raw, "title": "Unknown Title", "authors": ["Doost Mohammadian, H"],
    })

    assert result["authors"] == authors
    assert result["title"] == title
    assert result["venue"] == "Fachhochschule des Mittelstands (FHM) - University of Applied Sciences"
    assert result["year"] == 2020
    assert result["raw_text"] == raw


def test_normalization_does_not_infer_publisher_without_location_separator():
    from refchecker.utils.text_utils import normalize_reference_fields

    raw = "[1] Smith, J. A title, University of Applied Sciences, 2020."
    assert not normalize_reference_fields({"raw_text": raw}).get("venue")


def test_numbered_cascade_recovers_reviewed_formats_without_changing_neighbor():
    bibliography = (
        "[1] Walters, K.; Rodriguez, J. The Importance of Training and "
        "Development in Employee Performance and Evaluation. World Wide "
        "J.Multidiscip. Res. Dev. 2017, 3, 206-212\n"
        "[2] Sen,J. Embedded Systems and Wireless Technology. Chapter: 1. "
        "Publisher: CRC Press, Taylor & Francis Group, USA. 2012.\n"
        "[3] Hayatul,Y. Society 5.0 for Supper Smart Country. 2019. "
        "Available at: https://www.researchgate.net/publication/331521659\n"
        '[4] H. Smith, "A study," 2020 IEEE Learning With MOOCS (LWMOOCS), '
        'Antigua Guatemala, Guatemala, 2020, pp. 118-123, doi: 10.1109/123.\n'
        '[5] A. Smith, "A neighboring paper," Journal of Tests, 2020.'
    )
    checker = ArxivReferenceChecker(llm_config={"disabled": True})
    checker.extraction_mode = "cascade"

    refs = checker.parse_references(bibliography)

    assert len(refs) == 5
    assert refs[0]["authors"] == ["Walters, K.", "Rodriguez, J."]
    assert refs[0]["venue"] == "World Wide J.Multidiscip. Res. Dev."
    assert refs[1]["title"] == "Embedded Systems and Wireless Technology"
    assert refs[1]["venue"] == "CRC Press, Taylor & Francis Group"
    assert refs[2]["title"] == "Society 5.0 for Supper Smart Country"
    assert not refs[2].get("venue")
    assert refs[3]["venue"] == "2020 IEEE Learning With MOOCS (LWMOOCS)"
    assert refs[4]["title"] == "A neighboring paper"
    assert refs[4]["venue"] == "Journal of Tests"


def test_numbered_cascade_recovery_keeps_source_fields_and_neighbors():
    bibliography = (
        "[1] Wiggins, G., & McTighe, J. Understanding by Design. ASCD, 2005\n"
        "[2] Smith, J., Brown, A., & Evans, R. The Work. Press, 2014.\n"
        "[3] T. Collins, R. Getz, A. Wyglinski, and D. Pu, 2018."
    )
    checker = ArxivReferenceChecker(llm_config={"disabled": True})
    checker.extraction_mode = "cascade"

    refs = checker.parse_references(bibliography)

    assert len(refs) == 3
    assert (refs[0]["authors"], refs[0]["title"], refs[0]["venue"]) == (
        ["Wiggins, G.", "McTighe, J."], "Understanding by Design", "ASCD",
    )
    assert (refs[1]["title"], refs[1]["venue"]) == ("The Work", "Press")
    assert refs[2]["authors"] == ["T. Collins", "R. Getz", "A. Wyglinski", "D. Pu"]
    assert not refs[2]["title"]
    assert not refs[2]["venue"]
    assert "does not state" in " ".join(refs[2]["extraction_warnings"])


def test_numbered_cascade_normalizes_replaced_deterministic_entries():
    bibliography = (
        "[1] Means, B., Bakia, M., & Murphy, R. Learning Online: What Research "
        "Tells Us About Whether, When and How. Routledge, 2014.\n"
        "[2] Felder, R. M., & Brent, R. Active learning: An introduction. "
        "ASQ Higher Education Brief, 2(4), 1-5, Aug. 2009.\n"
        '[3] A. Smith, "Article title," Journal of Testing, 2021.'
    )
    checker = ArxivReferenceChecker(llm_config={"disabled": True})
    checker.extraction_mode = "cascade"

    refs = checker.parse_references(bibliography)

    assert len(refs) == 3
    assert refs[0]["authors"] == ["Means, B.", "Bakia, M.", "Murphy, R."]
    assert refs[0]["title"] == "Learning Online: What Research Tells Us About Whether, When and How"
    assert refs[0]["venue"] == "Routledge"
    assert refs[1]["title"] == "Active learning: An introduction"
    assert refs[2]["title"] == "Article title"


def test_offline_numbered_recovery_parses_comma_delimited_book_without_changing_neighbor():
    book = (
        "[22]\nS. Abood and M. Fayyadh, Advanced Power Systems and Security:\n"
        "Computer-Aided Design, New York: Nova Science Pub Inc., 2021."
    )
    neighbor = '[23] A. Smith, "A neighboring paper," Journal of Tests, 2020.'
    checker = ArxivReferenceChecker(llm_config={"disabled": True})

    refs = checker._recover_numbered_reference_entries([book, neighbor])

    assert refs[0]["authors"] == ["S. Abood", "M. Fayyadh"]
    assert refs[0]["title"] == "Advanced Power Systems and Security: Computer-Aided Design"
    assert refs[0]["venue"] == "Nova Science Pub Inc."
    assert refs[0]["raw_text"] == book
    assert refs[1]["title"] == "A neighboring paper"
    assert refs[1]["venue"] == "Journal of Tests"
    assert refs[1]["raw_text"] == neighbor


def test_offline_numbered_recovery_does_not_guess_ambiguous_publisher():
    raw = "[1] A. Smith, Unquoted work, Unknown City: Example, 2021."
    checker = ArxivReferenceChecker(llm_config={"disabled": True})

    ref = checker._recover_numbered_reference_entries([raw])[0]

    assert ref["raw_text"] == raw
    assert not ref["venue"]
    assert ref["extraction_warnings"]


@pytest.mark.parametrize(
    ("raw", "venue"),
    [
        (
            '[1] K. Liu, S. Reddivari, and K. Reddivari, "Artificial intelligence '
            'in software requirements engineering: State-of-the-art", pages '
            '106-111. IEEE, 2022.',
            "IEEE",
        ),
        (
            '[1] Schulz Trenton and Busch Marc, "A Case Study for Universal '
            'Design in the Internet of Things," in Assistive Technology Research '
            'Series, IOS Press, 2014. doi: 10.3233/978-1-61499-403-9-45.',
            "Assistive Technology Research Series",
        ),
        (
            '[1] H. Sarper, "Impulse Calculation of Model Rocket Engines," '
            'in 2019 ASEE Annual Conference & Exposition, June 2019.',
            "2019 ASEE Annual Conference & Exposition",
        ),
        (
            '[1] R. Hussein and D. Wilson, "Remote versus in-hand hardware '
            'laboratory in digital circuits courses," in 2021 ASEE Virtual '
            'Annual Conference Content Access. Virtual Conference: ASEE '
            'Conferences, July 2021, https://peer.asee.org/37662.',
            "2021 ASEE Virtual Annual Conference Content Access",
        ),
        (
            '[1] V. Callea and G. Remigi, "COACH_ING EDUCATIONAL MODEL: '
            'analysis and application for business," 2022 IEEE Global '
            'Engineering Education Conference (EDUCON), Tunis, Tunisia, '
            '2022, pp. 445-450, doi: 10.1109/EDUCON52537.2022.9766810.',
            "2022 IEEE Global Engineering Education Conference (EDUCON)",
        ),
    ],
)
def test_source_venues_exclude_page_ranges_and_publication_location(raw, venue):
    checker = ArxivReferenceChecker(llm_config={"disabled": True})

    refs = checker._parse_quoted_numbered_references([raw])

    assert len(refs) == 1
    assert refs[0]["venue"] == venue
    assert refs[0]["raw_text"] == raw


def test_page_range_alone_is_not_recovered_as_venue():
    raw = '[1] K. Liu, "A work", pages 106-111, 2022.'
    checker = ArxivReferenceChecker(llm_config={"disabled": True})

    refs = checker._parse_quoted_numbered_references([raw])

    assert len(refs) == 1
    assert not refs[0]["venue"]


def test_inverted_book_author_and_edition_publisher_are_preserved():
    raw = (
        '[9] Whitmore, J.: "Coaching for Performance: The Principles and Practice '
        'of Coaching and Leadership". 5th edn. Nicholas Brealey Publishing, '
        'United Kingdom (2017).'
    )
    checker = ArxivReferenceChecker(llm_config={"disabled": True})

    refs = checker._parse_quoted_numbered_references([raw])

    assert len(refs) == 1
    assert refs[0]["authors"] == ["Whitmore, J."]
    assert refs[0]["venue"] == "Nicholas Brealey Publishing"
    assert refs[0]["raw_text"] == raw


def test_quoted_citation_preserves_explicit_et_al_without_expanding_authors():
    raw = (
        '[2] A. Villar-Martinez et al., "Labsland electronics laboratory: '
        'Distributed remote laboratory," in Proc. Int. Conf. Remote Eng., '
        '2024, pp. 261-272.'
    )
    checker = ArxivReferenceChecker(llm_config={"disabled": True})

    refs = checker._parse_quoted_numbered_references([raw])

    assert refs[0]["authors"] == ["A. Villar-Martinez", "et al"]
    assert refs[0]["raw_text"] == raw


def test_author_year_question_title_separates_starred_venue():
    raw = (
        "[1] Holman, L., Stuart-Fox, D., Hauser, C. E. (2018). "
        "The gender gap in science: How long until women are equally represented? "
        "*PLoS Biology*, 16(4), e2004956."
    )
    checker = ArxivReferenceChecker(llm_config={"disabled": True})

    refs = checker.parse_references(
        raw + '\n[2] A. Smith, "A neighboring paper," Journal of Tests, 2020.'
    )

    assert refs[0]["title"] == "The gender gap in science: How long until women are equally represented?"
    assert refs[0]["venue"] == "PLoS Biology"
    assert refs[0]["raw_text"] == raw


def test_numbered_citations_starting_with_prompt_are_not_dropped():
    bibliography = (
        '[1] A. Smith, "First work," Journal of Tests, 2020.\n'
        '[2] Prompt Engineering Guide, "Prompt chaining," 2023.\n'
        '[3] Prompt Engineering Guide, "Prompting techniques," 2023.\n'
        '[4] B. Jones, "Last work," Journal of Tests, 2021.'
    )
    checker = ArxivReferenceChecker(llm_config={"disabled": True})

    refs = checker.parse_references(bibliography)

    assert len(refs) == 4
    assert [ref["entry_number"] for ref in refs] == [1, 2, 3, 4]
    assert refs[1]["title"] == "Prompt chaining"


def test_two_numbered_entries_are_parsed_offline():
    bibliography = (
        '[1] A. Smith, "First work," Journal of Tests, vol. 1, 2020.\n'
        '[2] B. Jones, "Second work," Journal of Tests, vol. 2, 2021.'
    )
    checker = ArxivReferenceChecker(llm_config={"disabled": True})

    refs = checker.parse_references(bibliography)

    assert [ref["title"] for ref in refs] == ["First work", "Second work"]


def test_numbered_reference_joined_to_previous_line_is_not_lost():
    bibliography = (
        '[1] A. Smith, "First work," Journal of Tests, vol. 1, 2020. '
        '[2] B. Jones, "Second work," Journal of Tests, vol. 2, 2021.\n'
        '[3] C. Brown, "Third work," Journal of Tests, vol. 3, 2022.'
    )
    checker = ArxivReferenceChecker(llm_config={"disabled": True})

    refs = checker.parse_references(bibliography)

    assert [ref["entry_number"] for ref in refs] == [1, 2, 3]
    assert refs[1]["title"] == "Second work"


def test_apa_citation_with_doi_preserves_fields():
    bibliography = (
        '[1] Smith, A., & Jones, B. (2022). An informative title. '
        'Journal of Testing. https://doi.org/10.1234/example.\n'
        '[2] Brown, C. (2021). Another informative title. '
        'Research Quarterly. https://doi.org/10.1234/another.'
    )
    checker = ArxivReferenceChecker(llm_config={"disabled": True})

    refs = checker.parse_references(bibliography)

    assert len(refs) == 2
    assert refs[0]["authors"] == ["Smith, A.", "Jones, B"]
    assert refs[0]["title"] == "An informative title"
    assert refs[0]["venue"] == "Journal of Testing"
    assert refs[0]["doi"] == "10.1234/example"


def test_apa_initials_with_duplicated_pdf_periods_keep_authors():
    bibliography = (
        '[1] Smith, A., Jones, B. ., & Brown, C. (2021). '
        'Inspiring future engineers. Journal of Testing, 5(1), 1-4. '
        'https://doi.org/10.1234/example\n'
        '[2] A. Other, "Another paper," Journal of Tests, 2020.'
    )
    checker = ArxivReferenceChecker(llm_config={"disabled": True})

    ref = checker.parse_references(bibliography)[0]

    assert ref["authors"] == ["Smith, A.", "Jones, B.", "Brown, C"]
    assert ref["title"] == "Inspiring future engineers"
    assert ref["venue"].startswith("Journal of Testing")
    assert ref["url"] == "https://doi.org/10.1234/example"
    assert "B. ." in ref["raw_text"]


def test_author_year_title_with_two_sentences_and_explicit_journal():
    bibliography = (
        '[1] Smith, Alex and Jones, Bo and P. G., Ranjith (2025) '
        'Redefining education in the AI era. Empowering students to collaborate '
        'with AI. SSRN Electronic Journal.\n'
        '[2] A. Other, "Another paper," Journal of Tests, 2020.'
    )
    checker = ArxivReferenceChecker(llm_config={"disabled": True})

    ref = checker.parse_references(bibliography)[0]

    assert ref["authors"] == ["Smith, Alex", "Jones, Bo", "P. G., Ranjith"]
    assert ref["title"] == (
        "Redefining education in the AI era. Empowering students to collaborate with AI"
    )
    assert ref["venue"] == "SSRN Electronic Journal"


def test_retrieved_organization_reference_keeps_source_fields():
    bibliography = (
        '[1] University of Example, 2018. Computational Thinking Rubric. '
        'Retrieved July 3, 2025, from https://example.com/rubric.pdf.\n'
        '[2] A. Other, "Another paper," Journal of Tests, 2020.'
    )
    checker = ArxivReferenceChecker(llm_config={"disabled": True})

    ref = checker.parse_references(bibliography)[0]

    assert ref["authors"] == ["University of Example"]
    assert ref["title"] == "Computational Thinking Rubric"
    assert ref["year"] == 2018
    assert not ref["venue"]
    assert ref["url"] == "https://example.com/rubric.pdf"


def test_retrieved_organization_reference_with_school_year():
    bibliography = (
        '[1] Example School District, 2014-15. Critical Thinking Rubric (Grades K-2). '
        'Retrieved July 3, 2025, from https://example.com/rubric.\n'
        '[2] A. Other, "Another paper," Journal of Tests, 2020.'
    )
    checker = ArxivReferenceChecker(llm_config={"disabled": True})

    ref = checker.parse_references(bibliography)[0]

    assert ref["authors"] == ["Example School District"]
    assert ref["title"] == "Critical Thinking Rubric (Grades K-2)"
    assert ref["year"] == 2014
    assert not ref["venue"]
    assert ref["url"] == "https://example.com/rubric"


def test_mixed_numbered_bibliography_keeps_apa_fields():
    bibliography = (
        '[1] Smith, A. (2022). An informative title. Journal of Testing. '
        'https://doi.org/10.1234/example.\n'
        '[2] A. Jones, Conference on Testing, 2021.'
    )
    checker = ArxivReferenceChecker(llm_config={"disabled": True})

    refs = checker.parse_references(bibliography)

    assert refs[0]["authors"] == ["A Smith"]
    assert refs[0]["title"] == "An informative title"
    assert refs[0]["venue"] == "Journal of Testing"


def test_single_quoted_reference_does_not_consume_text_after_doi():
    checker = ArxivReferenceChecker(llm_config={"disabled": True})
    refs = checker._parse_quoted_numbered_references([
        "[1] A. Smith, 'Learning methods', Journal of Testing, vol. 1, "
        "2020, doi: 10.1234/example.\nFurther citation text."
    ])

    assert refs[0]["title"] == "Learning methods"
    assert refs[0]["doi"] == "10.1234/example"


def test_page_range_is_not_a_venue():
    from refchecker.utils.biblatex_parser import parse_biblatex_entry_content

    ref = parse_biblatex_entry_content(
        "1",
        'J. Smith, "A useful paper," AI Open, vol. 1, pp. 57-81, 2020.',
    )

    assert ref["journal"] == "AI Open"


def test_quoted_website_venue_preceding_full_month_is_preserved():
    checker = ArxivReferenceChecker(llm_config={"disabled": True})
    refs = checker.parse_references(
        '[1] D. Smith, "Marketing research," Think with Example, June 2023. '
        '[Online]. Available: https://example.com/research\n'
        '[2] A. Other, "Another paper," Journal of Tests, 2020.'
    )

    assert refs[0]["authors"] == ["D. Smith"]
    assert refs[0]["title"] == "Marketing research"
    assert refs[0]["venue"] == "Think with Example"


@pytest.mark.parametrize("tail", ["pp. 1-12", "https://example.com/article"])
def test_full_month_does_not_make_pages_or_url_a_venue(tail):
    checker = ArxivReferenceChecker(llm_config={"disabled": True})
    ref = checker._parse_quoted_numbered_references([
        f'[1] A. Smith, "A useful paper," {tail}, July 2024.'
    ])[0]

    assert not ref["venue"]


def test_offline_fallback_preserves_incomplete_numbered_entries():
    bibliography = (
        '[1] A. Smith, "First work," Journal of Tests, vol. 1, 2020.\n'
        '[2] A. Jones, Conference on Testing, 2021.'
    )
    checker = ArxivReferenceChecker(llm_config={"disabled": True})

    refs = checker.parse_references(bibliography)

    assert len(refs) == 2
    assert refs[1]["raw_text"].startswith("[2]")
    assert refs[1]["title"] == ""
    assert refs[1]["extraction_warnings"]
    assert checker.fatal_error is False


def test_cli_displays_incomplete_reference_for_review(capsys):
    checker = ArxivReferenceChecker(llm_config={"disabled": True})
    reference = {
        "title": "",
        "authors": [],
        "raw_text": "[2] A. Jones, Conference on Testing, 2021.",
        "extraction_warnings": ["Reference fields could not be fully extracted."],
    }

    checker._print_reference_header(reference, 1, 2)

    output = capsys.readouterr().out
    assert "Reference requires review" in output
    assert reference["raw_text"] in output
    assert reference["extraction_warnings"][0] in output


def test_quoted_title_with_inner_quotes_is_not_truncated():
    checker = ArxivReferenceChecker(llm_config={"disabled": True})
    reference = (
        '[1] "Opinion paper: "so what if chatgpt wrote it?" multidisciplinary '
        'perspectives on generative AI," International Journal of Information '
        'Management, vol. 71, 2023.'
    )

    parsed = checker._parse_quoted_numbered_references([reference])

    assert len(parsed) == 1
    assert "multidisciplinary perspectives on generative AI" in parsed[0]["title"]
    assert parsed[0]["venue"] == "International Journal of Information Management"


def test_question_title_followed_by_conference_venue():
    checker = ArxivReferenceChecker(llm_config={"disabled": True})
    reference = (
        '[1] J. Yosinski, J. Clune, "How Transferable Are Features?" '
        'in Proc. Neural Information Processing, vol. 27, pp. 3320-3328, 2014.'
    )

    parsed = checker._parse_quoted_numbered_references([reference])

    assert parsed[0]["title"] == "How Transferable Are Features?"
    assert parsed[0]["venue"] == "Proc. Neural Information Processing"


def test_compact_quoted_conference_and_book_with_tex_metadata():
    checker = ArxivReferenceChecker(llm_config={"disabled": True})
    conference = (
        '[1]I. Nelson, R. Ferreira, and P. Jamieson, "Is it time for synthesis?"'
        'in 2021 IEEE Symposium. IEEE,2021,pp.1-5.'
    )
    book = (
        '[2]S.L.Harris and D.M.Harris,Digital design and computer architecture '
        'risc-v edition.Morgan Kaufman, 2022,tex.key:978-0-12-820064-3(cited on page 2).'
    )

    parsed_conference = checker._parse_quoted_numbered_references([conference])
    parsed_book = checker._parse_quoted_numbered_references([book])

    assert parsed_conference[0]["title"] == "Is it time for synthesis?"
    assert parsed_conference[0]["venue"] == "2021 IEEE Symposium"
    assert parsed_book[0]["title"] == "Digital design and computer architecture risc-v edition"
    assert parsed_book[0]["venue"] == "Morgan Kaufman"
    assert len(parsed_book[0]["authors"]) == 2
    assert parsed_book[0]["raw_text"] == book


def test_compact_authors_do_not_include_conjunction():
    checker = ArxivReferenceChecker(llm_config={"disabled": True})
    reference = (
        '[1]T.Van Mullem,B.Mesuere,and P.Dawyndt,'
        '"Are llms good at answering student questions?"ser.ITiCSE 2025.'
    )
    parsed = checker._parse_quoted_numbered_references([reference])

    assert parsed[0]["title"] == "Are llms good at answering student questions?"
    assert parsed[0]["authors"] == ["T.Van Mullem", "B.Mesuere", "P.Dawyndt"]


def test_quoted_title_with_space_before_close_and_compact_in():
    checker = ArxivReferenceChecker(llm_config={"disabled": True})
    reference = '[1] P. Veličković and Y. Bengio," Graph attention networks, "in Proc. ICLR, 2018.'

    parsed = checker._parse_quoted_numbered_references([reference])

    assert parsed[0]["title"] == "Graph attention networks"


def test_quoted_reference_venue_before_month_and_year():
    checker = ArxivReferenceChecker(llm_config={"disabled": True})
    reference = '[1]ERM, "The Nature Tech Revolution," NatureTech Alliance, Oct. 2024.'

    parsed = checker._parse_quoted_numbered_references([reference])

    assert parsed[0]["venue"] == "NatureTech Alliance"


def test_book_recovery_does_not_consume_following_authors_or_quoted_title():
    from refchecker.utils.biblatex_parser import extract_book_citation_fields

    citation = (
        'V. Tiefenbeck, A. Wörner, S. Schöb, E. Fleisch, y T. Staake, '
        '"Publisher Correction: Real-time feedback", Nature Energy, 2019.'
    )
    assert extract_book_citation_fields(citation) is None


def test_compact_author_title_journal_citation():
    checker = ArxivReferenceChecker(llm_config={"disabled": True})
    reference = (
        "[1]S.Abbate,P.Centobelli,and R.Cerchione. From fast to slow:An "
        "exploratory analysis of circular business models in the Italian apparel "
        "industry.International Journal of Production Economics,260:108824, 2023."
    )

    parsed = checker._parse_quoted_numbered_references([reference])

    assert parsed[0]["authors"] == ["S.Abbate", "P.Centobelli", "R.Cerchione"]
    assert parsed[0]["title"] == (
        "From fast to slow:An exploratory analysis of circular business models "
        "in the Italian apparel industry"
    )
    assert parsed[0]["venue"] == "International Journal of Production Economics"
    assert parsed[0]["raw_text"] == reference


def test_comma_delimited_journal_citation_with_doi():
    checker = ArxivReferenceChecker(llm_config={"disabled": True})
    reference = (
        "[1] K. Betts, P. Reddy, T. Galoyan, B. Delaney, D.L. McEachron, "
        "An Examination of Virtual Reality Training, Brain Sci 13 (2023). "
        "https://doi.org/10.3390/brainsci13060890."
    )

    parsed = checker._parse_quoted_numbered_references([reference])

    assert parsed[0]["authors"] == [
        "K. Betts", "P. Reddy", "T. Galoyan", "B. Delaney", "D.L. McEachron"
    ]
    assert parsed[0]["title"] == "An Examination of Virtual Reality Training"
    assert parsed[0]["venue"] == "Brain Sci"
    assert parsed[0]["year"] == 2023
    assert parsed[0]["doi"] == "10.3390/brainsci13060890"
    assert parsed[0]["raw_text"] == reference


def test_comma_delimited_citation_with_multiword_surname_in_mixed_list():
    checker = ArxivReferenceChecker(llm_config={"disabled": True})
    bibliography = """
[1] A. Šafhalter, M. Ploj Virtič, A study of spatial thinking,
International Journal of Education 33 (2023) 34-48.
https://doi.org/10.1000/example.
[2] An organization, An unquoted record with no year or publisher.
"""
    references = checker.parse_references(bibliography)

    assert references[0]["authors"] == ["A. Šafhalter", "M. Ploj Virtič"]
    assert references[0]["title"] == "A study of spatial thinking"
    assert references[0]["venue"] == "International Journal of Education"


def test_comma_delimited_citation_with_particles_and_conference_venue():
    checker = ArxivReferenceChecker(llm_config={"disabled": True})
    reference = (
        "[1] F.E.V. dos Anjos, A. de O. Martins, D.O. da Silva, "
        "Virtual reality in education, Proceedings - Frontiers in Education "
        "Conference, FIE 2015 (2015) 1-8."
    )
    parsed = checker._parse_quoted_numbered_references([reference])

    assert parsed[0]["authors"] == [
        "F.E.V. dos Anjos", "A. de O. Martins", "D.O. da Silva"
    ]
    assert parsed[0]["title"] == "Virtual reality in education"
    assert parsed[0]["venue"] == "Proceedings - Frontiers in Education Conference, FIE 2015"


def test_comma_delimited_citation_with_publisher_and_year():
    checker = ArxivReferenceChecker(llm_config={"disabled": True})
    reference = (
        "[1] M.A. Rojas-Sánchez, P.R. Palos-Sánchez, A review of virtual "
        "reality in education, Springer US, 2023. https://doi.org/10.1007/example."
    )
    parsed = checker._parse_quoted_numbered_references([reference])

    assert parsed[0]["authors"] == ["M.A. Rojas-Sánchez", "P.R. Palos-Sánchez"]
    assert parsed[0]["title"] == "A review of virtual reality in education"
    assert parsed[0]["venue"] == "Springer US"
    assert parsed[0]["year"] == 2023


def test_organization_online_citation_with_compact_access_date():
    checker = ArxivReferenceChecker(llm_config={"disabled": True})
    reference = (
        "[1]Wireshark Foundation.(2025)Wireshark:The world's most popular "
        "network protocol analyzer.Accessed:2025-11-12.[Online].Available:"
        "https://www.wireshark.org/"
    )
    parsed = checker._parse_quoted_numbered_references([reference])

    assert parsed[0]["authors"] == ["Wireshark Foundation"]
    assert parsed[0]["title"] == "Wireshark:The world's most popular network protocol analyzer"
    assert parsed[0]["year"] == 2025
    assert parsed[0]["url"] == "https://www.wireshark.org/"
    assert parsed[0]["raw_text"] == reference


def test_organization_online_citation_with_source_publisher():
    checker = ArxivReferenceChecker(llm_config={"disabled": True})
    reference = (
        "[1]UNESCO IIEP, Flexible learning pathways in higher education, UNESCO IIEP. "
        "[Online]. Available: https://example.com/education. (Accessed: 17 November 2025)."
    )
    parsed = checker._parse_quoted_numbered_references([reference])

    assert parsed[0]["authors"] == ["UNESCO IIEP"]
    assert parsed[0]["title"] == "Flexible learning pathways in higher education"
    assert parsed[0]["venue"] == "UNESCO IIEP"
    assert parsed[0]["year"] is None


def test_unquoted_dot_separated_book_with_full_author_names():
    checker = ArxivReferenceChecker(llm_config={"disabled": True})
    reference = (
        "[1]Suzanne Robertson et James Robertson.Mastering the Requirements "
        "Process:Getting Requirements Right.Addison-Wesley Professional,Boston,MA,2013."
    )
    parsed = checker._parse_quoted_numbered_references([reference])

    assert parsed[0]["authors"] == ["Suzanne Robertson", "James Robertson"]
    assert parsed[0]["title"] == "Mastering the Requirements Process:Getting Requirements Right"
    assert parsed[0]["venue"] == "Addison-Wesley Professional"
    assert parsed[0]["year"] == 2013
    assert parsed[0]["raw_text"] == reference


def test_compact_conference_citation_with_comma_in_venue():
    checker = ArxivReferenceChecker(llm_config={"disabled": True})
    reference = (
        "[1]J.A. Mesa, I.E. Esparragoza, and H.E. Maury.Sustainability in "
        "engineering education:A literature review.In 15th LACCEI International "
        "Multi-Conference for Engineering,Education, and Technology,Boca "
        "Raton,FL,2017."
    )
    parsed = checker._parse_quoted_numbered_references([reference])

    assert parsed[0]["authors"] == ["J.A. Mesa", "I.E. Esparragoza", "H.E. Maury"]
    assert parsed[0]["title"] == "Sustainability in engineering education:A literature review"
    assert parsed[0]["venue"] == "15th LACCEI International Multi-Conference for Engineering,Education, and Technology"
    assert parsed[0]["year"] == 2017


@pytest.mark.parametrize(
    ("reference", "title", "venue"),
    [
        (
            '[1] J. Bearman et al., "Effects of rubric quality on marker variation '
            'in higher education," Studies in Educational Evaluation, vol. 70, 101027, 2021.',
            "Effects of rubric quality on marker variation in higher education",
            "Studies in Educational Evaluation",
        ),
        (
            "[1] A. Calvo-Morata, C. Alonso-Fernández, B. Fernández-Manjón. "
            "(2025). Design of a Serious Game to Challenge Sexism. In: Entertainment "
            "Computing - ICEC 2025. Springer.",
            "Design of a Serious Game to Challenge Sexism",
            "In: Entertainment Computing - ICEC 2025. Springer",
        ),
        (
            '[1] Publications Office of the European Union, "Auditing the quality of '
            'datasets used in algorithmic decision-making systems," 2022. [Online]. '
            'Available: https://data.europa.eu/doi/10.2861/98930',
            "Auditing the quality of datasets used in algorithmic decision-making systems",
            "",
        ),
        (
            "[1] World Economic Forum, Future of Jobs Report 2025. Geneva, "
            "Switzerland: World Economic Forum, 2025. [Online]. "
            "Available: https://example.org/report",
            "Future of Jobs Report 2025",
            "World Economic Forum",
        ),
    ],
)
def test_source_patterns_do_not_capture_authors_or_quoted_titles_as_venues(
    reference, title, venue
):
    checker = ArxivReferenceChecker(llm_config={"disabled": True})
    parsed = checker.parse_references(
        reference + '\n[2] A. Author, "Another title," Journal, 2024.'
    )

    assert len(parsed) == 2
    assert parsed[0]["title"] == title
    assert parsed[0].get("venue", "") == venue


def test_uppercase_surname_citations_preserve_authors_title_and_venue():
    checker = ArxivReferenceChecker(llm_config={"disabled": True})
    bibliography = (
        "[1][1] ANDRADE, H.L., BENNETT, R.E., and CIZEK, G.J., 2019. "
        "Handbook of formative assessment in the disciplines. Routledge.\n"
        "[2][2] HSU, P.-S., LEE, E.M., SMITH, T.J., and KRAFT, C., 2023. "
        "Exploring youths' attitudes toward science in a Makerspace-infused "
        "after-school program. Interactive Learning Environments 31, 1, 355-369.\n"
        "[3][3] GRIZIOTI, M., 2025. Computational thinking beyond coding. "
        "Educational technology research and development, 1-28."
    )
    parsed = checker.parse_references(bibliography)

    assert parsed[0]["authors"] == ["H.L. ANDRADE", "R.E. BENNETT", "G.J. CIZEK"]
    assert parsed[0]["title"] == "Handbook of formative assessment in the disciplines"
    assert parsed[0]["venue"] == "Routledge"
    assert parsed[1]["authors"] == ["P.-S. HSU", "E.M. LEE", "T.J. SMITH", "C. KRAFT"]
    assert parsed[1]["title"] == (
        "Exploring youths' attitudes toward science in a Makerspace-infused after-school program"
    )
    assert parsed[1]["venue"] == "Interactive Learning Environments"
    assert parsed[2]["venue"] == "Educational technology research and development"


def test_spanish_guillemet_citations_ignore_access_and_doi_years():
    checker = ArxivReferenceChecker(llm_config={"disabled": True})
    bibliography = (
        "[1] D. Kumar, R. Jaipurkar, y A. Shekhar, «Item analysis of multiple "
        "choice questions», Medical Journal Armed Forces India, vol. 77, "
        "pp. S85-S89, feb. 2021, doi: 10.1016/j.mjafi.2020.11.007.\n"
        "[2] A. Akçay, y E. Altıner, «Sustaining Mathematics Education in the "
        "AI Era», https://example.org/10.4018/979-8-3373-1998-8.ch009. "
        "Accedido: 13 de enero de 2026. [En línea]."
    )
    parsed = checker.parse_references(bibliography)

    assert parsed[0]["authors"] == ["D. Kumar", "R. Jaipurkar", "A. Shekhar"]
    assert parsed[0]["title"] == "Item analysis of multiple choice questions"
    assert parsed[0]["venue"] == "Medical Journal Armed Forces India"
    assert parsed[0]["year"] == 2021
    assert parsed[1]["title"] == "Sustaining Mathematics Education in the AI Era"
    assert parsed[1]["year"] is None
    assert parsed[1]["venue"] == ""


def test_guillemet_book_series_is_not_mistaken_for_a_title():
    checker = ArxivReferenceChecker(llm_config={"disabled": True})
    bibliography = (
        "[1] Angel, P., Amar, P., Le coaching. Presses Universitaires de France, "
        "« Que sais-je ? », 2012, DOI: 10.3917/puf.angel.2012.01.\n"
        '[2] A. Smith, "A second work," Journal of Tests, vol. 1, 2020.'
    )
    parsed = checker.parse_references(bibliography)

    assert parsed[0]["title"] == "Le coaching"
    assert parsed[0]["venue"] == "Presses Universitaires de France"


def test_organization_report_without_a_publisher_preserves_source_fields():
    checker = ArxivReferenceChecker(llm_config={"disabled": True})
    bibliography = (
        "[1] Broadband Commission for Sustainable Development (UN). "
        "Combatting online violence against women and girls: A call to action "
        "for the world. 2015.\n"
        "[2] Standard Chartered and Cyber Women Community. "
        "Women in IT and Cybersecurity. 2022.\n"
        "[3] ENISA. ENISA Threat Landscape 2024. "
        "European Union Agency for Cybersecurity, 2024."
    )
    parsed = checker.parse_references(bibliography)

    assert parsed[0]["authors"] == ["Broadband Commission for Sustainable Development (UN)"]
    assert parsed[0]["title"] == (
        "Combatting online violence against women and girls: A call to action for the world"
    )
    assert parsed[0]["year"] == 2015
    assert parsed[0]["venue"] == ""
    assert parsed[1]["title"] == "Women in IT and Cybersecurity"
    assert parsed[2]["venue"] == "European Union Agency for Cybersecurity"


def test_inverted_authors_in_book_citations():
    checker = ArxivReferenceChecker(llm_config={"disabled": True})
    bibliography = (
        "[1] Christofferson, D. A. (Ed.). Women in security: Changing the face of "
        "technology and innovation. Springer. 2018\n"
        "[2] Núñez Puente, S., & Sánchez Hernández, M. F. Practices of Cyberfeminism: "
        "Use and creation of identities on the net. Women's Institute. 2011"
    )
    parsed = checker.parse_references(bibliography)

    assert parsed[0]["authors"] == ["Christofferson, D. A."]
    assert parsed[0]["title"] == "Women in security: Changing the face of technology and innovation"
    assert parsed[0]["venue"] == "Springer"
    assert parsed[1]["authors"] == ["Núñez Puente, S.", "Sánchez Hernández, M. F."]
    assert parsed[1]["venue"] == "Women's Institute"


def test_unquoted_online_citations_with_month_and_named_author():
    checker = ArxivReferenceChecker(llm_config={"disabled": True})
    bibliography = (
        "[1] QS, QS World University Rankings by Subject 2025: Engineering "
        "& Technology, Top Universities, Mar. 2025. [Online]. "
        "Available: https://example.org/rankings.\n"
        "[2] S. Jeans, Top 50 Universities for AI Education in 2024, "
        "EdTech Innovation Hub, 2024. [Online]. Available: https://example.org/ai."
    )
    parsed = checker.parse_references(bibliography)

    assert parsed[0]["authors"] == ["QS"]
    assert parsed[0]["title"] == "QS World University Rankings by Subject 2025: Engineering & Technology"
    assert parsed[0]["venue"] == "Top Universities"
    assert parsed[0]["year"] == 2025
    assert parsed[1]["authors"] == ["S. Jeans"]
    assert parsed[1]["venue"] == "EdTech Innovation Hub"


def test_online_acronym_report_without_publisher():
    checker = ArxivReferenceChecker(llm_config={"disabled": True})
    bibliography = (
        "[1] UNESCO, Recommendation on the Ethics of Artificial Intelligence, "
        "2021. [Online]. Available: https://example.org/recommendation.\n"
        '[2] A. Smith, "A second work," Journal of Tests, vol. 1, 2020.'
    )
    parsed = checker.parse_references(bibliography)

    assert parsed[0]["authors"] == ["UNESCO"]
    assert parsed[0]["title"] == "Recommendation on the Ethics of Artificial Intelligence"
    assert parsed[0]["venue"] == ""
    assert parsed[0]["year"] == 2021


def test_institution_report_location_is_not_a_venue():
    checker = ArxivReferenceChecker(llm_config={"disabled": True})
    bibliography = (
        "[1] European Commission, Digital Education Action Plan 2021-2027, Brussels, 2020.\n"
        "[2] American Association of Engineering Societies (AAES), "
        "Engineering Competency Model, Washington, DC, 2024."
    )
    parsed = checker.parse_references(bibliography)

    assert parsed[0]["authors"] == ["European Commission"]
    assert parsed[0]["title"] == "Digital Education Action Plan 2021-2027"
    assert parsed[0]["venue"] == ""
    assert parsed[1]["title"] == "Engineering Competency Model"
    assert parsed[1]["venue"] == ""


def test_unquoted_journal_citations_with_a_missing_opening_quote():
    checker = ArxivReferenceChecker(llm_config={"disabled": True})
    bibliography = (
        '[1] M. D. Merrill, Generative AI in education: Opportunities and challenges," '
        "IEEE Trans. Learn. Technol., vol. 17, no. 3, pp. 345-356, 2024.\n"
        "[2] Y. P. Hsu, D. F. Chiang, and I. Kehinde, Transforming engineering "
        "education in the digital era: Findings from a systematic review, "
        "Front. Educ., vol. 10, p. 1568917, May 2025. doi: 10.3389/feduc.2024.1568917."
    )
    parsed = checker.parse_references(bibliography)

    assert parsed[0]["authors"] == ["M. D. Merrill"]
    assert parsed[0]["title"] == "Generative AI in education: Opportunities and challenges"
    assert parsed[0]["venue"] == "IEEE Trans. Learn. Technol"
    assert parsed[1]["title"] == (
        "Transforming engineering education in the digital era: Findings from a systematic review"
    )
    assert parsed[1]["venue"] == "Front. Educ"
    assert parsed[1]["year"] == 2025


def test_single_quoted_website_title_with_nested_quotes_and_year_range():
    checker = ArxivReferenceChecker(llm_config={"disabled": True})
    reference = (
        "[1] Cabinet Office Japan, 'A \"Society\" Report 2025- 2026', "
        "Cabinet Office Home Page. Accessed: Nov. 17, 2025. "
        "[Online]. Available: https://example.com/report"
    )
    parsed = checker._parse_quoted_numbered_references([reference])

    assert parsed[0]["authors"] == ["Cabinet Office Japan"]
    assert parsed[0]["title"] == 'A "Society" Report 2025- 2026'
    assert parsed[0]["venue"] == "Cabinet Office Home Page"


def test_unquoted_books_preserve_title_and_publisher_in_mixed_bibliography():
    checker = ArxivReferenceChecker(llm_config={"disabled": True})
    bibliography = """
[1]L. Floridi, The Fourth Revolution: How the Infosphere is Reshaping Human
Reality. Oxford, U.K.: Oxford Univ. Press, 2014. pp. 6-12.
[2]I. Kant, Groundwork of the Metaphysics of Morals, M. Gregor, Trans.
Cambridge, U.K.: Cambridge Univ. Press, 1996. (Original work published 1785)
[3]M. Davis, Thinking Like an Engineer: Studies in the Ethics of a
Profession, Oxford University Press, 1998.
[4]S. Chance, T. Børsen, D. Martin, and G. Bombaerts, Eds., The Routledge
International Handbook of Engineering Ethics Education. London, U.K.:
Routledge, 2025. doi:
10.4324/9781003464259.
[5]A. Researcher, "A quoted article," Journal of Examples, vol. 2, 2024.
"""
    references = checker.parse_references(bibliography)

    assert references[0]["title"] == "The Fourth Revolution: How the Infosphere is Reshaping Human Reality"
    assert references[0]["venue"] == "Oxford Univ. Press"
    assert references[1]["title"] == "Groundwork of the Metaphysics of Morals"
    assert references[1]["venue"] == "Cambridge Univ. Press"
    assert references[2]["title"] == "Thinking Like an Engineer: Studies in the Ethics of a Profession"
    assert references[2]["venue"] == "Oxford University Press"
    assert references[3]["title"] == "The Routledge International Handbook of Engineering Ethics Education"
    assert references[3]["authors"] == ["S. Chance", "T. Børsen", "D. Martin", "G. Bombaerts"]
    assert references[3]["venue"] == "Routledge"


def test_page_range_is_not_reported_as_venue():
    from refchecker.utils.text_utils import normalize_reference_fields

    parsed = normalize_reference_fields({
        "title": "A study",
        "venue": "143-154",
        "journal": "143-154",
        "raw_text": "[1] A study, pp. 143-154.",
    })

    assert not parsed["venue"]
    assert not parsed["journal"]
    assert parsed["extraction_warnings"]


def test_supplemental_path_doi_is_repaired_only_with_repeated_source_doi():
    from refchecker.utils.text_utils import normalize_reference_fields

    raw = (
        "doi: 10.1073/pnas.1319030111/-\n"
        "/DCSupplemental.www.pnas.org/cgi/doi/10.1073/pnas.1319030111."
    )
    reference = {
        "doi": "10.1073/pnas.1319030111/-",
        "url": "https://doi.org/10.1073/pnas.1319030111/-",
        "raw_text": raw,
    }

    normalized = normalize_reference_fields(reference)
    assert normalized["doi"] == "10.1073/pnas.1319030111"
    assert normalized["url"] == "https://doi.org/10.1073/pnas.1319030111"

    reference = {
        "doi": "10.1073/pnas.1319030111/-",
        "url": "https://doi.org/10.1073/pnas.1319030111/-",
        "raw_text": raw.replace("/cgi/doi/10.1073/pnas.1319030111", "/other"),
    }
    assert normalize_reference_fields(reference)["doi"] == "10.1073/pnas.1319030111/-"

    reference["raw_text"] = raw.replace("1319030111.", "1319030111.extra.")
    assert normalize_reference_fields(reference)["doi"] == "10.1073/pnas.1319030111/-"


def test_numbered_citations_keep_source_order_after_url_normalization(monkeypatch):
    checker = ArxivReferenceChecker(llm_config={"disabled": True})
    monkeypatch.setattr(checker, "_parse_quoted_numbered_references", lambda entries: [])
    bibliography = """
[1]ERM, Salesforce, Planet, and NatureMetrics, "The Nature Tech
Revolution: The Tools to Move from 'Do No Harm' to 'Nature-Positive',"
NatureTech
Alliance,
Oct.
2024.
[Online].
Available: https://example.com/globalassets/insights/doc
uments/the-nature-tech-revolution
[2]H. Thomas, "Achieving 'nature positive' requires net-gain legislation,"
Science, 2024. DOI: 10.1126/science.adq0171.
[3]D. A. Martin, R. Bombaerts, and A. Johri, "A multi-level review of
engineering ethics education," Science and Engineering Ethics, 2021,
DOI: 10.1007/s11948-021-00333-6.
[4]IEEE Ethically Aligned Design, "Ethically Aligned Design: A Vision
for Prioritizing Human Well-being with Autonomous and Intelligent
Systems,"
IEEE,
2019.
[Online].
Available:
https://standards.ieee.org/industry-connections/ec/autonomous-
systems.html
"""
    references = checker._parse_references_regex(bibliography)

    assert len(references) == 4
    assert "Nature Tech Revolution" in references[0]["title"]
    assert "Achieving 'nature positive'" in references[1]["title"]
    assert "multi-level review" in references[2]["title"]
    assert "Ethically Aligned Design" in references[3]["title"]
    for number, reference in enumerate(references, 1):
        assert reference["raw_text"].lstrip().startswith(f"[{number}]")


def test_quoted_title_with_internal_comma_before_year_is_parsed():
    checker = ArxivReferenceChecker(llm_config={"disabled": True})
    reference = '[6]Prompt Engineering Guide, "Prompt chaining - nextra," 2023.'

    parsed = checker._parse_quoted_numbered_references([reference])

    assert len(parsed) == 1
    assert parsed[0]["title"] == "Prompt chaining - nextra"
    assert parsed[0]["authors"] == ["Prompt Engineering Guide"]
    assert parsed[0]["year"] == 2023


def test_quoted_title_followed_immediately_by_venue_is_parsed():
    checker = ArxivReferenceChecker(llm_config={"disabled": True})
    reference = '[1]An, X.et al."A study of teaching."Education and Information Technologies(2023).'

    parsed = checker._parse_quoted_numbered_references([reference])

    assert len(parsed) == 1
    assert parsed[0]["title"] == "A study of teaching"
    assert parsed[0]["venue"] == "Education and Information Technologies"
    assert parsed[0]["year"] == 2023


def test_author_year_title_containing_quotes_is_not_truncated():
    checker = ArxivReferenceChecker(llm_config={"disabled": True})
    reference = (
        '[1] Smith, J. (2015). The impact of design on "startup" initiatives. '
        'Journal of Testing.'
    )

    parsed = checker._parse_quoted_numbered_references([reference])

    assert parsed[0]["title"] == 'The impact of design on "startup" initiatives'
    assert parsed[0]["venue"] == "Journal of Testing"


def test_inverted_authors_are_not_mistaken_for_a_title():
    checker = ArxivReferenceChecker(llm_config={"disabled": True})
    reference = (
        '[1] Smith, J., Jones, A. (2023) Artificial Intelligence and Education. '
        'Journal of Testing.'
    )

    parsed = checker._parse_quoted_numbered_references([reference])

    assert parsed[0]["title"] == "Artificial Intelligence and Education"


def test_quoted_title_after_author_year_and_before_in_venue():
    checker = ArxivReferenceChecker(llm_config={"disabled": True})
    reference = (
        '[1] Smith, J., (2024) "A study of AI," in 2024 IEEE Conference, '
        '2024.'
    )

    parsed = checker._parse_quoted_numbered_references([reference])

    assert parsed[0]["title"] == "A study of AI"
    assert parsed[0]["authors"]
    assert all("2024" not in author for author in parsed[0]["authors"])


def test_generic_parser_recovers_wrapped_bare_doi():
    checker = ArxivReferenceChecker(llm_config={"disabled": True})
    bibliography = (
        "[1] A. Author. An unquoted article. Journal of Testing, 2024. "
        "doi:10.1007/s43621-024-\n00677-6.\n"
        "[2] B. Author. Another unquoted article. Journal of Testing, 2023."
    )

    parsed = checker._parse_references_regex(bibliography)

    assert parsed[0]["doi"] == "10.1007/s43621-024-00677-6"
    assert "024-\n00677-6" in parsed[0]["raw_text"]


@pytest.mark.parametrize(
    ("wrapped", "expected"),
    [
        ("10.1109/ICSE-\nSEET.2017.18", "10.1109/ICSE-SEET.2017.18"),
        ("10.1007/978-3-031- 67911-\n7_8", "10.1007/978-3-031-67911-7_8"),
        ("10.1007/s10734-022-00822-\ny", "10.1007/s10734-022-00822-y"),
        ("10.1088/2058- 9565/\nab4346", "10.1088/2058-9565/ab4346"),
    ],
)
def test_quoted_parser_recovers_alpha_and_multiple_wrapped_dois(wrapped, expected):
    checker = ArxivReferenceChecker(llm_config={"disabled": True})
    reference = f'[1] A. Smith, "A work," Journal, vol. 1, 2024, doi: {wrapped}.'

    parsed = checker._parse_quoted_numbered_references([reference])

    assert parsed[0]["doi"] == expected
    assert wrapped in parsed[0]["raw_text"]


def test_normalization_repairs_wrapped_source_doi_and_resolver_url():
    from refchecker.utils.text_utils import normalize_reference_fields

    ref = {
        "doi": "10.1109/ICSE-",
        "url": "https://doi.org/10.1109/ICSE-",
        "raw_text": "[1] A work. doi: 10.1109/ICSE-\nSEET.2017.18.",
    }

    result = normalize_reference_fields(ref)

    assert result["doi"] == "10.1109/ICSE-SEET.2017.18"
    assert result["url"].lower() == "https://doi.org/10.1109/icse-seet.2017.18"
    assert "-\n" in result["raw_text"]


def test_generic_parser_removes_access_date_from_url():
    checker = ArxivReferenceChecker(llm_config={"disabled": True})
    bibliography = (
        "[1] A. Author. An unquoted article. Journal of Testing, 2024. "
        "https://example.org/article,accessed:2025-01-20.\n"
        "[2] B. Author. Another unquoted article. Journal of Testing, 2023."
    )

    parsed = checker._parse_references_regex(bibliography)

    assert parsed[0]["url"] == "https://example.org/article"


def test_url_bearing_book_preserves_inverted_authors_title_and_publisher():
    checker = ArxivReferenceChecker(llm_config={"disabled": True})
    bibliography = (
        "[1] Angel, P., Amar, P., Le coaching. Presses Universitaires de France, "
        "2012. DOI: 10.3917/puf.angel.2012.01. URL: https://example.org/book.\n"
        '[2] A. Smith, "A second work," Journal of Tests, vol. 1, 2020.'
    )

    refs = checker.parse_references(bibliography)

    assert refs[0]["authors"] == ["Angel, P.", "Amar, P."]
    assert refs[0]["title"] == "Le coaching"
    assert refs[0]["venue"] == "Presses Universitaires de France"


@pytest.mark.parametrize(
    ("reference", "title", "venue"),
    [
        ("[1] P.Gardner-Chloros,Code-Switching.Cambridge University Press,2009.",
         "Code-Switching", "Cambridge University Press"),
        ("[1] J.P.Gee,What Video Games Have to Teach Us About Learning and Literacy,2003.",
         "What Video Games Have to Teach Us About Learning and Literacy", ""),
    ],
)
def test_unquoted_compact_book_fields(reference, title, venue):
    checker = ArxivReferenceChecker(llm_config={"disabled": True})

    parsed = checker._parse_quoted_numbered_references([reference])

    assert parsed[0]["title"] == title
    assert parsed[0]["venue"] == venue


def test_author_year_conference_entry_is_not_mistaken_for_merged_references():
    checker = ArxivReferenceChecker(llm_config={"disabled": True})
    reference = (
        "[1] Jones, A., Smith, B. (2025). Coaching and Engineering: "
        "Effective Tools. 2025 IEEE Global Engineering Education Conference, "
        "1-10. https://doi.org/10.1109/example.2025.123456."
    )

    parsed = checker._parse_quoted_numbered_references([reference])

    assert [author.rstrip(".") for author in parsed[0]["authors"]] == ["Jones, A", "Smith, B"]
    assert parsed[0]["title"] == "Coaching and Engineering: Effective Tools"
    assert parsed[0]["venue"].startswith("2025 IEEE Global Engineering Education Conference")


def test_numbered_author_year_chapter_with_conference_year_is_not_merged():
    checker = ArxivReferenceChecker(llm_config={"disabled": True})
    reference = (
        "[1] Jones, A., Smith, B. (2025). Engineering Education for Tomorrow. "
        "In: Auer, M. (ed) Futureproofing Engineering Education. ICL 2024. "
        "Lecture Notes in Networks and Systems. https://doi.org/10.1007/example."
    )

    parsed = checker._parse_quoted_numbered_references([reference])

    assert parsed[0]["title"] == "Engineering Education for Tomorrow"
    assert [author.rstrip(".") for author in parsed[0]["authors"]] == ["Jones, A", "Smith, B"]
    assert "Futureproofing Engineering Education" in parsed[0]["venue"]


def test_organization_web_citation_preserves_source_fields():
    checker = ArxivReferenceChecker(llm_config={"disabled": True})
    bibliography = (
        '[1] CERN. "Playing with Protons." CERN News, 2023. '
        '[Online]. Available: https://example.org/news.\n'
        '[2] A. Smith, "A second work," Journal of Tests, vol. 1, 2020.'
    )

    refs = checker.parse_references(bibliography)

    assert refs[0]["authors"] == ["CERN"]
    assert refs[0]["title"] == "Playing with Protons"
    assert refs[0]["venue"] == "CERN News"


def test_quoted_title_preserves_terminal_inner_quote():
    checker = ArxivReferenceChecker(llm_config={"disabled": True})
    reference = '[1] CERN. "Playing with \'Protons\'." CERN News, 2023.'

    parsed = checker._parse_quoted_numbered_references([reference])

    assert parsed[0]["title"] == "Playing with 'Protons'"


def test_authorless_quoted_citation_has_empty_authors_and_warning():
    checker = ArxivReferenceChecker(llm_config={"disabled": True})
    reference = '[1] "A standards page." Accessed: Oct. 28, 2025. https://example.org/page'

    parsed = checker._parse_quoted_numbered_references([reference])

    assert parsed[0]["authors"] == []
    assert parsed[0]["title"] == "A standards page"
    assert parsed[0]["extraction_warnings"]


def test_authorless_single_quoted_citation_preserves_contraction():
    checker = ArxivReferenceChecker(llm_config={"disabled": True})
    reference = "[1] 'Everyone can benefit from a student's perspective'. Accessed: 2025."

    parsed = checker._parse_quoted_numbered_references([reference])

    assert parsed[0]["authors"] == []
    assert parsed[0]["title"] == "Everyone can benefit from a student's perspective"
    assert parsed[0]["extraction_warnings"]


def test_editor_author_year_citation_preserves_book_fields():
    checker = ArxivReferenceChecker(llm_config={"disabled": True})
    reference = (
        "[1] Frodeman, R. (Ed.). (2017). The Oxford Handbook of Interdisciplinarity "
        "(2nd ed.). Oxford University Press. https://doi.org/10.1093/example."
    )

    parsed = checker._parse_quoted_numbered_references([reference])

    assert [author.replace(".", "") for author in parsed[0]["authors"]] == ["R Frodeman"]
    assert parsed[0]["title"].startswith("The Oxford Handbook of Interdisciplinarity")
    assert parsed[0]["venue"] == "Oxford University Press"


def test_quoted_title_and_initial_first_author_list_preserve_all_parts():
    checker = ArxivReferenceChecker(llm_config={"disabled": True})
    reference = (
        '[1] V. Callea, M. Ursache, I. Chiarotto, A. Matrisciano and R. Tempone, '
        '"A Case Study at University of Rome "Sapienza"," 2024 IEEE Conference.'
    )

    parsed = checker._parse_quoted_numbered_references([reference])

    assert parsed[0]["title"] == 'A Case Study at University of Rome "Sapienza"'
    assert parsed[0]["authors"] == [
        "V. Callea", "M. Ursache", "I. Chiarotto", "A. Matrisciano", "R. Tempone"
    ]


def test_organization_book_with_url_preserves_source_fields():
    checker = ArxivReferenceChecker(llm_config={"disabled": True})
    bibliography = (
        '[1] Example Accreditation Commission, Criteria for Accrediting Programs. '
        'Example Press, 2024. [Online]. Available: https://example.org/criteria.\n'
        '[2] A. Smith, "A second work," Journal of Tests, vol. 1, 2020.'
    )

    refs = checker.parse_references(bibliography)

    assert refs[0]["authors"] == ["Example Accreditation Commission"]
    assert refs[0]["title"] == "Criteria for Accrediting Programs"
    assert refs[0]["venue"] == "Example Press"


def test_organization_book_title_with_year_range_is_not_author_year():
    checker = ArxivReferenceChecker(llm_config={"disabled": True})
    reference = (
        "[1] Example Accreditation Commission, Criteria for Accrediting Programs, "
        "2025-2026. Example Press, 2024. [Online]. Available: https://example.org/criteria."
    )

    parsed = checker._parse_quoted_numbered_references([reference])

    assert parsed[0]["authors"] == ["Example Accreditation Commission"]
    assert parsed[0]["title"] == "Criteria for Accrediting Programs, 2025-2026"
    assert parsed[0]["venue"] == "Example Press"
    assert parsed[0]["year"] == 2024


def test_repeated_reference_label_with_unparenthesized_author_year():
    checker = ArxivReferenceChecker(llm_config={"disabled": True})
    bibliography = (
        "[1][1] BOSTON, C., 2002. The concept of formative assessment. "
        "Practical Assessment, Research, and Evaluation 8, 1, 9.\n"
        '[2][2] A. Smith, "A second work," Journal of Tests, vol. 1, 2020.'
    )

    refs = checker.parse_references(bibliography)

    assert len(refs) == 2
    assert refs[0]["authors"] == ["C. BOSTON"]
    assert refs[0]["title"] == "The concept of formative assessment"
    assert refs[0]["venue"].startswith("Practical Assessment")
    assert refs[0]["raw_text"].startswith("[1][1]")


def test_offline_fallback_handles_numbered_author_year_entries():
    bibliography = (
        '1.\nSmith, A. (2022). An informative title. Journal of Testing.\n'
        '2.\nJones, B. (2021). Another informative title. Research Quarterly.'
    )
    checker = ArxivReferenceChecker(llm_config={"disabled": True})

    refs = checker.parse_references(bibliography)

    assert len(refs) == 2
    assert refs[0]["title"] == "An informative title"
    assert refs[1]["title"] == "Another informative title"


def test_clean_url_punctuation_strips_next_reference_after_pdf_url():
    glued_url = (
        'https://www-cdn.anthropic.com/6d8a8055020700718b0c49369f60816ba2a7c285.pdf'
        '%20Shuai%20Bai,%20Wen%20Zhang,%20and%20Bo%20Jing.%20Deepseek-v3%20technical%20report,%202024.'
    )

    assert clean_url_punctuation(glued_url) == (
        'https://www-cdn.anthropic.com/6d8a8055020700718b0c49369f60816ba2a7c285.pdf'
    )


def test_clean_url_punctuation_preserves_encoded_spaces_before_pdf_suffix():
    url = 'https://example.com/reports/Claude%204%20System%20Card.pdf'

    assert clean_url_punctuation(url) == url


def test_bibliography_stops_before_split_word_appendix_heading():
    text = """
Introduction
This paper cites stochastic approximation literature.

References
David Aldous and James Allen Fill. Reversible markov chains and random walks on graphs, 2002.
Sihan Zeng, Thinh T Doan, and Justin Romberg. A two-time-scale stochastic optimization framework
with applications in control and reinforcement learning. arXiv preprint arXiv:2109.14756, 2021.
13
Published as a conference paper at ICLR 2024
A E XAMPLES OF STOCHASTIC ALGORITHMS OF THE FORM (2).
In the literature of stochastic optimizations, many SGD variants have been proposed.
"""

    bibliography = ArxivReferenceChecker().find_bibliography_section(text)

    assert 'two-time-scale stochastic optimization framework' in bibliography
    assert 'A E XAMPLES OF STOCHASTIC ALGORITHMS' not in bibliography
    assert 'many SGD variants' not in bibliography


def test_bibliography_stops_before_colon_appendix_heading():
    text = """
Introduction
This paper cites dimensionality reduction literature.

References
Peter Yianilos. Data structures and algorithms for nearest neighbor search in general metric spaces.
In Proceedings of the ACM-SIAM Symposium on Discrete Algorithms, pp. 311-321, 1993.
Shujian Yu, Hongmin Li, Sigurd Lokse, Robert Jenssen, and Jose Principe. The conditional
cauchy-schwarz divergence with applications to time-series data and sequential decision making.
arXiv preprint arXiv:2301.08970, 2023.
APPENDIX A: F URTHER PERSPECTIVES ON T -SNE, UMAP, P ACMAP, AND
VARIANTS
As mentioned in Section 1 of this paper, a large plethora of methods exists.
"""

    bibliography = ArxivReferenceChecker().find_bibliography_section(text)

    assert 'conditional' in bibliography
    assert 'APPENDIX A:' not in bibliography
    assert 'large plethora of methods' not in bibliography


def test_bibliography_strips_internal_pdf_page_headers():
    text = """
Introduction
This paper cites reinforcement learning literature.

REFERENCES
Yasin Abbasi-Yadkori, David Pal, and Csaba Szepesvari. Improved algorithms for linear stochastic
bandits. Advances in neural information processing systems, 24, 2011.
10
Published as a conference paper at ICLR 2024
Zihan Zhang and Qiaomin Xie. Sharper model-free reinforcement learning for average-reward
markov decision processes. In The Thirty Sixth Annual Conference on Learning Theory, pp.
5476-5477. PMLR, 2023.
11
Published as a conference paper at ICLR 2024
Dongruo Zhou, Jiafan He, and Quanquan Gu. Provably efficient reinforcement learning for dis-
counted mdps with feature mapping. In International Conference on Machine Learning, pp.
12793-12802. PMLR, 2021b.
A BACKGROUNDS AND TECHNICAL NOVELTIES
Appendix text should not be included.
"""

    bibliography = ArxivReferenceChecker().find_bibliography_section(text)

    assert 'Published as a conference paper' not in bibliography
    assert '10\n' not in bibliography
    assert '11\n' not in bibliography
    assert 'Improved algorithms for linear stochastic' in bibliography
    assert 'Provably efficient reinforcement learning' in bibliography
    assert 'A BACKGROUNDS AND TECHNICAL NOVELTIES' not in bibliography


def test_bibliography_keeps_numbered_reference_after_page_number():
    text = """
Introduction
This paper cites bibliometrics literature.

References
[1] A. Author, "First cited work," Journal of Tests, vol. 1, no. 1, pp. 1-9, 2020.
[2] J. H. Sweetland, "Errors in bibliographic citations: A continuing prob-
lem," The Library Quarterly, vol. 59, no. 4, pp. 291-304, 1989.
14
[3] M. V. Simkin and V. P. Roychowdhury, "Stochastic modeling of citation
slips," Scientometrics, vol. 62, no. 3, pp. 367-384, 2005.
[4] E. M. Bender, T. Gebru, A. McMillan-Major, and S. Shmitchell, "On the dangers
of stochastic parrots," in Proceedings of FAccT, 2021, pp. 610-623.
[5] B. Author, "Final cited work," Conference on Tests, 2022.
"""

    bibliography = ArxivReferenceChecker().find_bibliography_section(text)

    assert '[3] M. V. Simkin' in bibliography
    assert 'slips," Scientometrics' in bibliography
    assert '\n14\n' not in bibliography


def test_parse_references_falls_back_when_llm_skips_numbered_entries():
    bibliography = """
[1] A. Author, "First cited work," Journal of Tests, vol. 1, no. 1, pp. 1-9, 2020.
[2] B. Author, "Second cited work," Conference on Tests, pp. 10-19, 2021.
[3] C. Author, "Third cited work," Transactions on Tests, vol. 3, pp. 20-29, 2022.
[4] D. Author, "Fourth cited work," Symposium on Tests, pp. 30-39, 2023.
"""

    class SkippingLLMExtractor:
        def extract_references(self, bibliography_text, progress_callback=None):
            return [
                'A. Author#First cited work#Journal of Tests#2020#',
                'D. Author#Fourth cited work#Symposium on Tests#2023#',
            ]

    checker = ArxivReferenceChecker()
    checker.llm_extractor = SkippingLLMExtractor()

    references = checker.parse_references(bibliography)

    assert len(references) == 4
    assert [reference['year'] for reference in references] == [2020, 2021, 2022, 2023]


def test_bibliography_ignores_title_header_that_looks_like_appendix_heading():
    text = """
Introduction
This paper studies backtracking counterfactual explanations.

References
Ates, E., Aksar, B., Leung, V. J., and Coskun, A. K. Counterfactual explanations for multivariate time series. In
2021 International Conference on Applied Artificial In-

Improving Backtracking Counterfactual Definitions: The
current definition of backtracking counterfactuals does not
9

A Unified Causal Framework for Efficient Model Interpretability

telligence (ICAPAI), pp. 1-8. IEEE, 2021.

Chattopadhyay, A., Manupriya, P., Sarkar, A., and Balasubramanian, V. N. Neural network attributions: A causal
perspective. In International Conference on Machine Learning, pp. 981-990. PMLR, 2019.

Karimi, A.-H., Barthe, G., Balle, B., and Valera, I. Model-agnostic counterfactual explanations for consequential
decisions. In International Conference on Artificial Intelligence and Statistics, pp. 895-905. PMLR, 2020.

A. Formal Definition of Interventional and Backtracking Counterfactuals
This appendix content should not be included in the bibliography.
"""

    bibliography = ArxivReferenceChecker().find_bibliography_section(text)

    assert 'Counterfactual explanations for multivariate time series' in bibliography
    assert 'telligence (ICAPAI)' in bibliography
    assert 'Neural network attributions' in bibliography
    assert 'Model-agnostic counterfactual explanations' in bibliography
    assert 'Improving Backtracking Counterfactual Definitions' not in bibliography
    assert 'A Unified Causal Framework for Efficient Model Interpretability' not in bibliography
    assert 'Formal Definition of Interventional' not in bibliography
    assert 'appendix content' not in bibliography
    assert '\n9\n' not in bibliography


def test_bibliography_stops_before_split_question_appendix_heading():
    text = """
Introduction
This paper cites time series classification literature.

REFERENCES
Matthew D. Zeiler and Rob Fergus. Visualizing and understanding convolutional networks. In Computer
Vision-ECCV 2014: 13th European Conference, pp. 818-833. Springer, 2014.
Bolei Zhou, Aditya Khosla, Agata Lapedriza, Aude Oliva, and Antonio Torralba. Learning deep features
for discriminative localization. In Proceedings of the IEEE Conference on Computer Vision and Pattern
Recognition, pp. 2921-2929, 2016.
Yuansheng Zhu, Weishi Shi, Deep Shankar Pandey, Yang Liu, Xiaofan Que, Daniel E. Krutz, and Qi Yu.
Uncertainty-aware multiple instance learning from large-scale long time series data. In 2021 IEEE
International Conference on Big Data, pp. 1772-1778. IEEE, 2021.
A W HY MIL?
Multiple instance learning discussion should not be included.
"""

    bibliography = ArxivReferenceChecker().find_bibliography_section(text)

    assert 'Uncertainty-aware multiple instance learning' in bibliography
    assert 'A W HY MIL?' not in bibliography
    assert 'Multiple instance learning discussion' not in bibliography


def test_bibliography_stops_before_neurips_checklist_template():
    text = """
Introduction
This paper cites reinforcement learning literature.

References
Jane Researcher and John Scientist. A useful offline reinforcement learning method.
In International Conference on Machine Learning, pages 1-10. PMLR, 2023.
Zoe Zhang and Quinn Gu. Energy-weighted flow matching for offline reinforcement learning.
arXiv preprint arXiv:2503.04975, 2025.
addressing issues of reproducibility, transparency, research ethics, and societal impact. Do not remove
the checklist: The papers not including the checklist will be desk rejected. The checklist should
follow the references and follow the optional supplemental material.
1. Claims
Question: Do the main claims made in the abstract and introduction accurately reflect the paper's contributions?
"""

    bibliography = ArxivReferenceChecker().find_bibliography_section(text)

    assert 'Energy-weighted flow matching' in bibliography
    assert 'Do not remove' not in bibliography
    assert 'desk rejected' not in bibliography
    assert '1. Claims' not in bibliography


def test_bibliography_stops_before_single_letter_colon_appendix_heading_without_cutting_colon_reference():
    text = """
Introduction
This paper cites stochastic differential equations literature.

References
Michail D. Vrettas, Dan Cornford, and Manfred Opper. Estimating parameters in stochastic systems:
a variational bayesian approach. Physica D: Nonlinear Phenomena, 240(23):1877-1900, 2011.
Sebastian Zeng, Florian Graf, and Roland Kwitt. Latent sdes on homogeneous spaces.
Advances in Neural Information Processing Systems, 36, 2024.
B Background: Stochastic Differential Equations
In this section we provide background information for stochastic differential equations.
"""

    bibliography = ArxivReferenceChecker().find_bibliography_section(text)

    assert 'Estimating parameters in stochastic systems:' in bibliography
    assert 'Latent sdes on homogeneous spaces' in bibliography
    assert 'B Background:' not in bibliography
    assert 'background information' not in bibliography


def test_bibliography_stops_after_final_bracket_reference_when_heading_is_lost():
    text = """
Introduction
This paper cites out-of-distribution detection literature.

References
[1] Anh Nguyen, Jason Yosinski, and Jeff Clune. Deep neural networks are easily fooled:
High confidence predictions for unrecognizable images, 2015. URL https://arxiv.org/abs/1412.1897.
[2] Dan Hendrycks and Kevin Gimpel. A baseline for detecting misclassified and out-of-distribution
examples in neural networks. CoRR, abs/1610.02136, 2016. URL https://arxiv.org/abs/1610.02136.
[3] Kaiming He, Xiangyu Zhang, Shaoqing Ren, and Jian Sun. Delving deep into rectifiers.
In Proceedings of ICCV, pages 1026-1034, 2015.
[4] Alex Krizhevsky, Ilya Sutskever, and Geoffrey Hinton. Imagenet classification with deep
convolutional neural networks. Communications of the ACM, 60(6):84-90, 2017.
[5] Jingkang Yang, Kaiyang Zhou, Yixuan Li, and Ziwei Liu. Generalized out-of-distribution
detection: A survey. CoRR, abs/2110.11334, 2021. URL https://arxiv.org/abs/2110.
11334.
16
A Theoretical Analysis of SPROD
SPROD employs a two-step prototype refinement strategy to approximate group-specific prototypes.
"""

    bibliography = ArxivReferenceChecker().find_bibliography_section(text)

    assert 'Generalized out-of-distribution' in bibliography
    assert '11334.' in bibliography
    assert 'A Theoretical Analysis' not in bibliography
    assert 'prototype refinement' not in bibliography
    assert '\n16\n' not in bibliography


def test_author_year_bibliography_stops_before_appendix_after_page_number():
    text = """
Introduction
This paper cites offline reinforcement learning literature.

References
David H Ackley, Geoffrey E Hinton, and Terrence J Sejnowski. A learning algorithm for boltzmann
machines. Cognitive science, 9(1):147-169, 1985.
Peter Auer, Nicolò Cesa-Bianchi, and Paul Fischer. Finite-time analysis of the multiarmed bandit
problem. Machine learning, 47:235-256, 2002.
Andras Gyorgy and Csaba Szepesvari. Minimax regret of finite partial-monitoring games in
stochastic environments. In Conference on Learning Theory, pages 133-154, 2007.
Yifei Zhou, Andrea Zanette, Jiayi Pan, Sergey Levine, and Aviral Kumar. Archer: Training language
model agents via hierarchical multi-turn rl. arXiv preprint arXiv:2402.19446, 2024.
Brian D Ziebart. Modeling purposeful adaptive behavior with the principle of maximum causal
entropy. PhD thesis, Carnegie Mellon University, 2010.
13
A Presentation of other variation of ShiQ
ShiQ/init: We can skip the reward shaping used in the theorem.
a better initialization, and do the other steps.
"""

    bibliography = ArxivReferenceChecker().find_bibliography_section(text)

    assert 'Modeling purposeful adaptive behavior' in bibliography
    assert 'A Presentation of other variation' not in bibliography
    assert 'a better initialization' not in bibliography
    assert '\n13\n' not in bibliography


def test_author_year_bibliography_preserves_continuation_with_reference_evidence():
    text = """
Introduction
This paper cites backdoor attack literature.

References
Jiawang Bai and Chen Chen. Sample reference one. arXiv preprint arXiv:2201.00001, 2022.
Alice Chen and Bob Davis. Sample reference two. In International Conference on Machine Learning,
pages 11-20. PMLR, 2021.
Olga Russakovsky, Jia Deng, Hao Su, Jonathan Krause, Sanjeev Satheesh, Sean Ma, Zhiheng Huang,
Andrej Karpathy, Aditya Khosla, Michael Bernstein, et al. Imagenet large scale visual recognition
challenge. International journal of computer vision, 115:211-252, 2015.
Karen Simonyan and Andrew Zisserman. Very deep convolutional networks for large-scale image
recognition. arXiv preprint arXiv:1409.1556, 2014.
itors, Advances in Neural Information Processing Systems, volume 31. Curran Associates,
Inc., 2018. URL https://proceedings.neurips.cc/paper_files/paper/2018/file/example-Paper.pdf.
Mingxing Tan and Quoc Le. EfficientNet: Rethinking model scaling for convolutional neural networks.
In Proceedings of the 36th International Conference on Machine Learning, pages 6105-6114.
PMLR, 2019. URL https://proceedings.mlr.press/v97/tan19a.html.
Zihao Zhu, Mingda Zhang, Shaokui Wei, Li Shen, Yanbo Fan, and Baoyuan Wu. Boosting backdoor
attack with a learnable poisoning sample selection strategy. arXiv preprint arXiv:2307.07328,
2023.
1. Claims
Question: Do the main claims made in the abstract and introduction accurately reflect the paper's contributions?
"""

    bibliography = ArxivReferenceChecker().find_bibliography_section(text)

    assert 'EfficientNet' in bibliography
    assert 'learnable poisoning sample selection strategy' in bibliography
    assert '1. Claims' not in bibliography
    assert 'Question: Do the main claims' not in bibliography


def test_author_year_bibliography_preserves_author_initial_reference():
    text = """
Introduction
This paper cites neural network literature.

References
Michael Tangermann, Klaus-Robert Müller, Ad Aertsen, Niels Birbaumer, Christoph Braun, Clemens
Brunner, Robert Leeb, Carsten Mehring, Kai J Miller, Gernot R Müller-Putz, et al. Review of the
BCI Competition IV. Frontiers in Neuroscience, 6:55, 2012.
Jack E. Taylor, Rasmus Sinn, Cosimo Iaia, and Christian J. Fiebach. Alphabetic Decision Task,
2024.
Hugo Touvron, Thibaut Lavril, Gautier Izacard, Xavier Martinet, Marie-Anne Lachaux, Timothée
Lacroix, Baptiste Rozière, Naman Goyal, Eric Hambro, Faisal Azhar, et al. Llama: Open and
Efficient Foundation Language Models. arXiv preprint arXiv:2302.13971, 2023.
Hanneke Van Dijk, Guido Van Wingen, Damiaan Denys, Sebastian Olbrich, Rosalinde Van Ruth, and
Martijn Arns. The Two Decades Brainclinics Research Archive for Insights in Neurophysiology
Database. Scientific Data, 9(1):333, 2022.
A Vaswani. Attention Is All You Need. Advances in Neural Information Processing Systems, 2017.
J. Veillette, S. Heald, B. Wittenbrink, and H. Nusbaum. EEG-Neuroforecasting, 2022.
"""

    bibliography = ArxivReferenceChecker().find_bibliography_section(text)

    assert 'The Two Decades Brainclinics Research Archive' in bibliography
    assert 'Attention Is All You Need' in bibliography
    assert 'EEG-Neuroforecasting' in bibliography


def test_author_year_bibliography_preserves_wrapped_doi_url_fragment():
    text = """
Introduction
This paper cites machine learning software literature.

References
Philipp Moritz, Robert Nishihara, Stephanie Wang, Alexey Tumanov, Richard Liaw, Eric Liang,
Melih Elibol, Zongheng Yang, William Paul, Michael I Jordan, et al. Ray: A distributed framework
for emerging AI applications. In 13th USENIX symposium on operating systems design and
implementation, pages 561-577, 2018.
Rhys Newbury, Jack Collins, Kerry He, Jiahe Pan, Ingmar Posner, David Howard, and Akansel
Cosgun. A review of differentiable simulators. IEEE Access, 12:97581-97604, 2024. doi:
10.1109/ACCESS.2024.3425448.
The pandas development team. pandas-dev/pandas: Pandas, February 2020. URL https://doi.
org/10.5281/zenodo.3509134.
Adam Paszke, Sam Gross, Francisco Massa, Adam Lerer, James Bradbury, Gregory Chanan, Trevor
Killeen, Zeming Lin, Natalia Gimelshein, Luca Antiga, Alban Desmaison, Andreas Kopf, Edward
Yang, Zachary DeVito, Martin Raison, Alykhan Tejani, Sasank Chilamkurthy, Benoit Steiner,
Lu Fang, Junjie Bai, and Soumith Chintala. PyTorch: An imperative style, high-performance deep
learning library. In Advances in Neural Information Processing Systems, volume 32. Curran
Associates, Inc., 2019. URL https://proceedings.neurips.cc/paper_files/paper/2019/file/example.pdf.
"""

    bibliography = ArxivReferenceChecker().find_bibliography_section(text)

    assert 'URL https://doi.' in bibliography
    assert 'org/10.5281/zenodo.3509134' in bibliography
    assert 'PyTorch: An imperative style' in bibliography


def test_author_year_bibliography_preserves_initial_author_without_period():
    text = """
Introduction
This paper cites mixture modeling literature.

References
Pierre Del Moral and Angele Niclas. A Taylor expansion of the square root matrix functional,
January 2018. URL http://arxiv.org/abs/1705.08561.
Kevin P Murphy. Conjugate bayesian analysis of the gaussian distribution. def, 1(2σ2):16, 2007.
Atsumi Ohara, Nobuhide Suda, and Shun-ichi Amari. Dualistic differential geometry of positive def-
inite matrices and its applications to related problems. Linear Algebra and its Applications, 247:
31-53, November 1996. ISSN 0024-3795. doi: 10.1016/0024-3795(94)00348-3. URL https:
//www.sciencedirect.com/science/article/pii/0024379594003483.
D Peel and G J Mclachlan. Robust mixture modelling using the t distribution. Statistics and Com-
puting, 10(4):339-348, 2000.
William D Penny. Kullback-liebler divergences of normal, gamma, dirichlet and wishart densities.
Wellcome Department of Cognitive Neurology, 2001.
"""

    bibliography = ArxivReferenceChecker().find_bibliography_section(text)

    assert 'Dualistic differential geometry' in bibliography
    assert 'Robust mixture modelling' in bibliography
    assert 'Kullback-liebler divergences' in bibliography


def test_author_year_bibliography_preserves_long_lowercase_author_continuation():
    text = """
Introduction
This paper cites vision-language-action literature.

References
Anthony Brohan, Noah Brown, Justice Carbajal, Yevgen Chebotar, Joseph Dabis, Chelsea Finn,
Keerthana Gopalakrishnan, Karol Hausman, Alex Herzog, Jasmine Hsu, Julian Ibarz, Brian Ichter,
Alex Irpan, Tomas Jackson, Sally Jesmonth, Nikhil J Joshi, Ryan Julian, Dmitry Kalashnikov,
Yuheng Kuang, Isabel Leal, Kuang-Huei Lee, Sergey Levine, Yao Lu, Utsav Malla, Deeksha
Manjunath, Igor Mordatch, Ofir Nachum, Carolina Parada, Jodilyn Peralta, Emily Perez, Karl
Pertsch, Jornell Quiambao, Kanishka Rao, Michael Ryoo, Grecia Salazar, Pannag Sanketi, Kevin
Sayed, Jaspiar Singh, Sumedh Sontakke, Austin Stone, Clayton Tan, Huong Tran, Vincent Van-
houcke, Steve Vega, Quan Vuong, Fei Xia, Ted Xiao, Peng Xu, Sichun Xu, Tianhe Yu, and
Brianna Zitkovich. Rt-1: Robotics transformer for real-world control at scale, 2023. URL
https://arxiv.org/abs/2212.06817.
Chi-Lam Cheang, Guangzeng Chen, Ya Jing, Tao Kong, Hang Li, Yifeng Li, Yuxiao Liu, Hongtao
Wu, Jiafeng Xu, Yichu Yang, Hanbo Zhang, and Minzhao Zhu. Gr-2: A generative video-language-
action model with web-scale knowledge for robot manipulation. arXiv preprint arXiv:2410.06158,
2024.
los Riquelme Ruiz, Sebastian Goodman, Xiao Wang, Yi Tay, Siamak Shakeri, Mostafa Dehghani,
Daniel Salz, Mario Lucic, Michael Tschannen, Arsha Nagrani, Hexiang Hu, Mandar Joshi, Bo Pang,
Ceslee Montgomery, Paulina Pietrzyk, Marvin Ritter, AJ Piergiovanni, Matthias Minderer, Filip
Pavetic, Austin Waters, Gang Li, Ibrahim Alabdulmohsin, Lucas Beyer, Julien Amelot, Kenton
Lee, Andreas Peter Steiner, Yang Li, Daniel Keysers, Anurag Arnab, Yuanzhong Xu, Keran Rong,
Alexander Kolesnikov, Mojtaba Seyedhosseini, Anelia Angelova, Xiaohua Zhai, Neil Houlsby,
and Radu Soricut. Pali-x: On scaling up a multilingual vision and language model, 2023. URL
https://arxiv.org/abs/2305.18565.
"""

    bibliography = ArxivReferenceChecker().find_bibliography_section(text)

    assert 'Gr-2: A generative video-language' in bibliography
    assert 'Pali-x: On scaling up' in bibliography
    assert 'https://arxiv.org/abs/2305.18565' in bibliography


def test_author_year_bibliography_preserves_bare_domain_url_continuation():
    text = """
Introduction
This paper cites item response theory literature.

References
R. Ostini and M.L. Nering. Polytomous Item Response Theory Models. SAGE Publications, 2006.
ISBN 9780761930686. URL https://books.google.com.hk/books?id=wS8VEMtJ3UYC.
Tal Reiss, Niv Cohen, and Yedid Hoshen. No free lunch: The hazards of over-expressive representa-
tions in anomaly detection. arXiv preprint arXiv:2306.07284, 2023.
Klaas Sijtsma and Ivo Molenaar. The monotone homogeneity model: Scalability coefficients. In
Introduction to Nonparametric Item Response Theory, pages 49-64. SAGE Publications, Inc.,
Thousand Oaks, California, 2002a. doi: 10.4135/9781412984676.n4. URL https://methods.
sagepub.com/book/mono/introduction-to-nonparametric-item-response-theory/
chpt/monotone-homogeneity-model-scalability-coefficients.
Klaas Sijtsma and Ivo W. Molenaar. Introduction to Nonparametric Item Response Theory. Sage,
Thousand Oaks, CA, 2002b.
"""

    bibliography = ArxivReferenceChecker().find_bibliography_section(text)

    assert 'URL https://methods.' in bibliography
    assert 'sagepub.com/book/mono' in bibliography
    assert 'Introduction to Nonparametric Item Response Theory. Sage' in bibliography


def test_bracket_bibliography_stops_before_document_appendix_heading():
    text = """
Introduction
This paper cites fair representation learning literature.

References
[1] Solon Barocas and Andrew Selbst. Big data's disparate impact. California Law Review, 104:671, 2016.
[2] Cynthia Dwork, Moritz Hardt, Toniann Pitassi, Omer Reingold, and Richard Zemel. Fairness
through awareness. In Innovations in Theoretical Computer Science, pages 214-226, 2012.
[3] Moritz Hardt, Eric Price, and Nati Srebro. Equality of opportunity in supervised learning.
In Advances in Neural Information Processing Systems, 2016.
[4] Faisal Kamiran and Toon Calders. Data preprocessing techniques for classification without
discrimination. Knowledge and Information Systems, 33(1):1-33, 2012.
[5] David Madras, Elliot Creager, Toniann Pitassi, and Richard S. Zemel. Learning adversarially
fair and transferable representations. In Proceedings of the 35th International Conference on
Machine Learning, pages 3384-3393, 2018.
A Document empirical inconsistency
The appendix discussion should not be included in the bibliography.
"""

    bibliography = ArxivReferenceChecker().find_bibliography_section(text)

    assert 'Learning adversarially' in bibliography
    assert 'A Document empirical inconsistency' not in bibliography
    assert 'appendix discussion' not in bibliography


def test_bracket_bibliography_preserves_final_reference_continuation_after_year():
    text = """
Introduction
This paper cites pharmacokinetics literature.

References
[1] Author One. First cited work. Journal of Examples, 2020.
[2] Author Two. Second cited work. In Conference on Examples, 2021.
[3] Author Three. Third cited work. arXiv preprint arXiv:2201.00001, 2022.
[4] Author Four. Fourth cited work. Briefings in Bioinformatics, 2024.
[5] Yuxuan Zhao and Samuel W. K. Wong. Manifold-constrained gaussian processes for inference
of mixed-effects ordinary differential equations with application to pharmacokinetics. arXiv
preprint arXiv:2506.22313, 2025.
neural ODE causal modeling and an application to glycemic response. In Proceedings of the
41st International Conference on Machine Learning, 2024.
"""

    bibliography = ArxivReferenceChecker().find_bibliography_section(text)

    assert 'Manifold-constrained gaussian processes' in bibliography
    assert 'neural ODE causal modeling' in bibliography
    assert '41st International Conference on Machine Learning' in bibliography


def test_repair_truncated_arxiv_doi_from_source_bibliography():
    refs = [
        'a*Ying Tang*et al.#DeepSeek-R1: Incentivizing Reasoning Capability in LLMs via Reinforcement Learning#arXiv preprint#2025#https://doi.org/10.48550/ARXIV.25'
    ]
    bibliography_text = (
        'DeepSeek-AI, Daya Guo, Dejian Yang, Haowei Zhang, Junxiao Song, et al. '
        'DeepSeek-R1: Incentivizing Reasoning Capability in LLMs via Reinforcement Learning. '
        'arXiv preprint arXiv:2501.12948, 2025. DOI: 10.48550/ARXIV.2501.12948\n'
        'Other Team. Another 2025 arXiv paper. DOI: 10.48550/arXiv.2502.00001'
    )

    repaired = LLMProvider._repair_truncated_arxiv_dois(refs, bibliography_text)

    assert '10.48550/ARXIV.2501.12948' in repaired[0]
    assert '10.48550/ARXIV.25' not in repaired[0].replace('10.48550/ARXIV.2501.12948', '')


def test_repair_truncated_arxiv_doi_leaves_complete_doi_unchanged():
    refs = [
        'DeepSeek-AI#DeepSeek-R1: Incentivizing Reasoning Capability in LLMs via Reinforcement Learning#arXiv preprint#2025#https://doi.org/10.48550/ARXIV.2501.12948'
    ]
    bibliography_text = (
        'DeepSeek-R1: Incentivizing Reasoning Capability in LLMs via Reinforcement Learning. '
        'DOI: 10.48550/ARXIV.2501.12948'
    )

    assert LLMProvider._repair_truncated_arxiv_dois(refs, bibliography_text) == refs