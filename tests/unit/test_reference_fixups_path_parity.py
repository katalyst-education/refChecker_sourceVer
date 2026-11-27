"""Post-parse fixups must run on every path, not just the CLI.

``_fixup_reference_fields`` lived on ``ArxivReferenceChecker`` and was invoked
from ``verify_reference_standard``. The WebUI never calls either: its wrapper
calls ``self.checker.verify_reference(...)`` on the hybrid checker directly. So
the venue-as-title, author-list-as-title and citation-tail-as-venue repairs were
silently skipped in the WebUI, which is why the user still saw the citation
title duplicated into the venue after the fix shipped.

The fixups now live in a shared module and are applied at the hybrid checker's
entry point — the one place all three paths funnel through.
"""

import pytest

from refchecker.utils.reference_fixups import (
    fixup_reference_fields,
    is_suspicious_venue,
    recover_missing_venue_from_source,
    recover_acronym_year_venue,
    strip_citation_tail_from_venue,
)

# Real production string from the user's paper (reference 74).
CONTAMINATED_VENUE = (
    'Tian, "BioProBench: a benchmark for biological protocols," '
    'in International Conference on Machine Learning (ICML) , 2026'
)
CLEAN_VENUE = 'International Conference on Machine Learning (ICML)'


def _ref(**over):
    base = {'title': 'BioProBench', 'authors': ['Y. Tian'], 'year': 2026,
            'venue': CONTAMINATED_VENUE}
    base.update(over)
    return base


class TestSharedImplementation:
    def test_citation_tail_removed(self):
        ref = _ref()
        fixup_reference_fields(ref)
        assert ref['venue'] == CLEAN_VENUE

    def test_is_idempotent(self):
        """Safe to apply at more than one point in a pipeline."""
        ref = _ref()
        fixup_reference_fields(ref)
        once = ref['venue']
        fixup_reference_fields(ref)
        assert ref['venue'] == once

    @pytest.mark.parametrize('venue', [
        'ICLR 2024',
        'Proceedings of the 2024 Conference on EMNLP',
        'Nature',
        '',
    ])
    def test_legitimate_venues_survive(self, venue):
        ref = _ref(venue=venue)
        fixup_reference_fields(ref)
        assert ref['venue'] == venue

    def test_unsalvageable_venue_is_blanked(self):
        """A blank venue beats one that fails every comparison."""
        ref = _ref(venue='"A title," in ab, 2024')
        strip_citation_tail_from_venue(ref)
        assert ref['venue'] == ''

    @pytest.mark.parametrize('venue', [
        r'08\)',
        "'24)",
        '7]',
        '---',
    ])
    def test_impossible_venue_fragments_are_detected_and_blanked(self, venue):
        assert is_suspicious_venue(venue)
        ref = _ref(venue=venue)
        fixup_reference_fields(ref)
        assert ref['venue'] == ''

    @pytest.mark.parametrize(('venue', 'expected'), [
        ("ICML'24", 'ICML'),
        ('ACL\u201923', 'ACL'),
        (r'LREC\`08', 'LREC'),
        ('(NeurIPS`9)', 'NeurIPS'),
    ])
    def test_generic_acronym_year_venue_is_normalized(self, venue, expected):
        ref = _ref(venue=venue)
        fixup_reference_fields(ref)
        assert ref['venue'] == expected

    def test_acronym_year_is_recovered_from_raw_text(self):
        ref = _ref(
            venue=r'08\)',
            raw_text=r"Councill et al. ParsCit. In (LREC\`08), 2008.",
        )
        fixup_reference_fields(ref)
        assert ref['venue'] == 'LREC'

    def test_full_parenthesized_venue_wins_over_damaged_prefix(self):
        ref = _ref(venue=r'08\)(International Conference on Language Resources and Evaluation)')
        fixup_reference_fields(ref)
        assert ref['venue'] == 'International Conference on Language Resources and Evaluation'

    def test_recovers_quoted_venue_from_source_tail(self):
        ref = {
            'title': 'Developing a model for AI Across the curriculum',
            'venue': '',
            'journal': '',
            'raw_text': (
                '[20] J. Southworth, "Developing a model for AI Across the '
                'curriculum," Computers and Education: Artificial Intelligence, '
                'no. 4, p. 100127, 2023.'
            ),
        }

        recover_missing_venue_from_source(ref)

        assert ref['venue'] == 'Computers and Education: Artificial Intelligence'
        assert ref['journal'] == ref['venue']

    def test_recovers_quoted_venue_before_bare_volume_and_year(self):
        ref = {
            'title': 'Generative artificial intelligence in higher education',
            'venue': '',
            'journal': '',
            'raw_text': (
                '[1] N. McDonald, "Generative artificial intelligence in higher '
                'education," Computers in Human Behavior: Artificial Humans, '
                '3, 2025.'
            ),
        }

        recover_missing_venue_from_source(ref)

        assert ref['venue'] == 'Computers in Human Behavior: Artificial Humans'
        assert ref['journal'] == ref['venue']

    @pytest.mark.parametrize('raw_text', [
        '[1] A. Smith, "A study," New York, 2019.',
        '[1] A. Smith, "A study," Journal Name, vol. XX, pp. 1-3.',
    ])
    def test_does_not_promote_locations_or_placeholder_venues(self, raw_text):
        ref = {'title': 'A study', 'venue': '', 'raw_text': raw_text}

        recover_missing_venue_from_source(ref)

        assert ref['venue'] == ''

    def test_recovers_unquoted_venue_after_single_quoted_title(self):
        ref = {
            'title': (
                'Collaborative online learning in higher education-quality '
                'of digital interaction and associations with individual and '
                'group-related factors'
            ),
            'venue': '',
            'journal': '',
            'raw_text': (
                "[17] A. Bach and F. Thiel, 'Collaborative online learning in "
                "higher education-quality of digital interaction and "
                "associations with individual and group-related factors', in "
                'Frontiers in Education, Frontiers Media SA, 2024, p. 1356271.'
            ),
        }

        recover_missing_venue_from_source(ref)

        assert ref['venue'] == 'Frontiers in Education, Frontiers Media SA'
        assert ref['journal'] == ref['venue']

    def test_recovers_unquoted_venue_after_period_before_container_marker(self):
        ref = {
            'title': (
                'A cyber-physical digital twin approach to replicating realistic '
                'multi-stage cyberattacks on smart grids'
            ),
            'venue': '',
            'journal': '',
            'raw_text': (
                '[9] Sen, N., Bleser, N., Henze, M., and Ulbig, A. A cyber-physical '
                'digital twin approach to replicating realistic multi-stage '
                'cyberattacks on smart grids. In IET Conference Proceedings CP823 '
                '(Vol. 2023, No. 6, pp. 995-999). Stevenage, UK: The Institution '
                'of Engineering and Technology.'
            ),
        }

        recover_missing_venue_from_source(ref)

        assert ref['venue'] == 'IET Conference Proceedings CP823'
        assert ref['journal'] == ref['venue']

    @pytest.mark.parametrize(
        ('title', 'authors', 'raw_text'),
        [
            (
                'Deci and R',
                ['E. L. Deci', 'R. M. Ryan'],
                '[22] E. L. Deci and R. M. Ryan, Intrinsic Motivation and '
                'Self-Determination in Human Behavior. Springer Science & '
                'Business Media, June 2013.',
            ),
            (
                'Tekbıyık, A',
                ['Tekbıyık, A.', 'Bulut, D. B.', 'Sandalcı, Y.'],
                '[18] Tekbıyık, A., Bulut, D. B., Sandalcı, Y.: Effects of a '
                'summer robotics camp on students STEM career interest and '
                'knowledge structure. Journal of Pedagogical Research 6(2), '
                '91-109 (2022).',
            ),
            (
                'A preprint',
                ['A. Author'],
                '[1] A. Author. A preprint. 2024. arXiv:2402.07927.',
            ),
            (
                'Lee Boonstra',
                ['Lee Boonstra'],
                '[11] Lee Boonstra. Prompt Engineering. Tech. rep. Google, 2024.',
            ),
        ],
    )
    def test_does_not_promote_author_fragments_or_preprint_ids_to_venue(
        self, title, authors, raw_text
    ):
        ref = {
            'title': title,
            'authors': authors,
            'venue': '',
            'raw_text': raw_text,
        }

        recover_missing_venue_from_source(ref)

        assert ref['venue'] == ''

    @pytest.mark.parametrize(
        ('title', 'raw_text', 'expected_venue'),
        [
            (
                'Designing human-centered learning analytics and artificial '
                'intelligence in education solutions: a systematic literature review',
                '[29] Paraskevi Topali, Alejandro Ortega-Arranz, Mar ́ıa Jes ́us '
                'Rodr ́ıguez-Triana, Erkan Er, Mohammad Khalil, and Gökhan '
                'Akc ̧apınar. Designing human-centered learning analytics and '
                'artificial intelligence in education solutions: a systematic '
                'literature review. Behaviour & Information Technology, '
                '44(5):1071-1098, 2025.',
                'Behaviour & Information Technology',
            ),
            (
                "Mosaic-f: A framework for enhancing students' oral presentation "
                'skills through personalized feedback',
                '[40] Alvaro Becerra, Daniel Andres, Pablo Villegas, Roberto '
                'Daza, and Ruth Cobos. Mosaic-f: A framework for enhancing '
                "students' oral presentation skills through personalized "
                'feedback. In Ainhoa Alvarez, Rebeca Cerezo, and Mikel '
                'Larra ̃naga, editors, Proceedings of the Learning Analytics '
                'Summer Institute Spain 2025, volume 4148 of CEUR Workshop '
                'Proceedings, pages 1-10, Vitoria-Gasteiz, Spain, 2025.',
                'Proceedings of the Learning Analytics Summer Institute Spain 2025',
            ),
        ],
    )
    def test_recovers_venue_after_unquoted_source_title(
        self, title, raw_text, expected_venue
    ):
        ref = {
            'title': title,
            'venue': '',
            'journal': '',
            'raw_text': raw_text,
        }

        recover_missing_venue_from_source(ref)

        assert ref['venue'] == expected_venue
        assert ref['journal'] == expected_venue

    @pytest.mark.parametrize(
        ('title', 'venue', 'raw_text', 'expected_venue'),
        [
            (
                'Formative assessment and feedback for learning in higher '
                'education: A systematic review',
                'Review of Education, 9(3):e3292',
                '[1] Rebecca Morris, Thomas Perry, and Lindsey Wardle. '
                'Formative assessment and feedback for learning in higher '
                'education: A systematic review. Review of Education, '
                '9(3):e3292, 2021.',
                'Review of Education',
            ),
            (
                'Enhancing online learning by integrating biosensors and '
                'multimodal learning analytics for detecting and predicting '
                'student behaviour: a review',
                'Behaviour & Information Technology, pages 1-26',
                '[41] Alvaro Becerra, Ruth Cobos, and Charles Lang. Enhancing '
                'online learning by integrating biosensors and multimodal '
                'learning analytics for detecting and predicting student '
                'behaviour: a review. Behaviour & Information Technology, '
                'pages 1-26, 2025.',
                'Behaviour & Information Technology',
            ),
        ],
    )
    def test_strips_source_confirmed_metadata_from_venue(
        self, title, venue, raw_text, expected_venue
    ):
        ref = {'title': title, 'venue': venue, 'journal': venue, 'raw_text': raw_text}

        recover_missing_venue_from_source(ref)

        assert ref['venue'] == expected_venue
        assert ref['journal'] == expected_venue

    def test_recovers_book_container_without_editor_or_publisher_tail(self):
        ref = {
            'title': (
                'The convention on the rights of the child: Reflections from '
                'a historical, social policy and educational perspective'
            ),
            'venue': '',
            'raw_text': (
                '[14] E. Verhellen, "The convention on the rights of the child: '
                'Reflections from a historical, social policy and educational '
                'perspective," in Routledge International Handbook of Children\'s '
                'Rights Studies, W. Vandenhole, E. Desmet, D. Reynaert, and '
                'S. Lembrechts, Eds. London / New York: Routledge, 2015.'
            ),
        }

        recover_missing_venue_from_source(ref)

        assert ref['venue'] == "Routledge International Handbook of Children's Rights Studies"

    @pytest.mark.parametrize(
        ('title', 'raw_text', 'expected_venue'),
        [
            (
                'Utvikling av førsteårsstudenters tilbakemeldingskompetanse '
                'gjennom egen-vurdering',
                '[5] O. Mirmotahari and Y. Berg, "Utvikling av '
                'førsteårsstudenters tilbakemeldingskompetanse gjennom '
                'egen-vurdering," in Norsk IKT-konferanse for forskning og '
                'utdanning, no. 4 in 1, 2023.',
                'Norsk IKT-konferanse for forskning og utdanning',
            ),
            (
                'The PRISMA 2020 statement: an updated guideline for reporting '
                'systematic reviews',
                '[16] M. J. Page et al., "The PRISMA 2020 statement: an '
                'updated guideline for reporting systematic reviews," BMJ, '
                'p. n71, Mar. 2021.',
                'BMJ',
            ),
            (
                "A taxonomy for learning, teaching, and assessing: A revision "
                "of bloom's taxonomy of educational objectives",
                '[51] L. W. Anderson and D. R. Krathwohl, "A taxonomy for '
                "learning, teaching, and assessing: A revision of bloom's "
                'taxonomy of educational objectives," in A Taxonomy for '
                'Learning, Teaching, and Assessing. Longman, 2001.',
                'A Taxonomy for Learning, Teaching, and Assessing',
            ),
            (
                'Integrating entrepreneurial mindset into first-year '
                'engineering curriculum through active learning exercises',
                '[24] C. S. Korach and J. Gargac, "Integrating entrepreneurial '
                'mindset into first-year engineering curriculum through active '
                'learning exercises," in Proc. ASEE Annual Conf. & Exposition, '
                'Tampa, FL, USA, June 2019, Paper ID #27319.',
                'Proc. ASEE Annual Conf. & Exposition, Tampa, FL, USA',
            ),
            (
                'Situating Constructionism',
                '[5] S. Papert, "Situating Constructionism," in Constructionism: '
                'Research Reports and Essays, Ablex, 1991.',
                'Constructionism: Research Reports and Essays',
            ),
            (
                'In defense of advance organizers: a reply to the critics.',
                '[18] D. Ausubel, "In defense of advance organizers: a reply to '
                'the critics.," Rev. Educ. Res. 48,251e257. B, 1978.',
                'Rev. Educ. Res',
            ),
            (
                'Understanding Policy Responses to Generative AI in Private '
                'Higher Education: Insights from Japan and the United States',
                '[7] L. Mack and A. Byanjankar, "Understanding Policy Responses '
                'to Generative AI in Private Higher Education: Insights from '
                'Japan and the United States". J Acad Ethics 23, 2357-2377, '
                '2025. Available: https://doi.org/10.1007/s10805-025-09655-7',
                'J Acad Ethics',
            ),
            (
                'Keeping up with the demand for programmers and IT professionals',
                '[14] B. Skinner, "Keeping up with the demand for programmers '
                'and IT professionals," Breakout Mentors, Jun. 09 2011. '
                '[Online]. Available: https://breakoutmentors.com/keeping-up-'
                'with-the-demand-for-programmers-and-it-professionals/',
                'Breakout Mentors',
            ),
            (
                'Nobel Lecture',
                '[35] J. Rotblat, "Nobel Lecture," NobelPrize.org, Dec. 11, '
                '1995. [Online]. Available: '
                'https://www.nobelprize.org/prizes/peace/1995/rotblat/lecture/',
                'NobelPrize.org',
            ),
            (
                'The 3A Assessment Framework',
                '[13] Y. Chen, K. K. Chai, and Y. Alfadhl, "The 3A Assessment '
                'Framework" Acadmic Committee Report, QMUL, 2024.',
                'Acadmic Committee Report, QMUL',
            ),
            (
                'Industry 5.0 - Towards a sustainable, human-centric and '
                'resilient European industry',
                '[4] Publications Office of the European Union, "Industry 5.0 - '
                'Towards a sustainable, human-centric and resilient European '
                'industry," Publication Office of the EU, Luxembourg, 2021.',
                'Publication Office of the EU, Luxembourg',
            ),
            (
                'Generative agents: Interactive simulacra of human behavior',
                '[7] J. S. Park, C. J. Cai, "Generative agents: Interactive '
                'simulacra of human behavior," arXiv:2304.03442 [cs], 04 2023. '
                '[Online]. Available: https://arxiv.org/abs/2304.03442',
                'arXiv:2304.03442 [cs]',
            ),
            (
                'Closing the Gender Gap in Engineering: Students Role Model '
                'Program',
                '[9] E. Vidal, E. Castro, "Closing the Gender Gap in Engineering: '
                'Students Role Model Program," 2020 43rd International Convention '
                'on Information, Communication and Electronic Technology (MIPRO), '
                'Opatija, Croatia, 2020, pp. 1493-1496.',
                '2020 43rd International Convention on Information, '
                'Communication and Electronic Technology (MIPRO), Opatija, Croatia',
            ),
        ],
    )
    def test_recovers_quoted_venues_without_standard_venue_cues(
        self, title, raw_text, expected_venue
    ):
        ref = {'title': title, 'venue': '', 'journal': '', 'raw_text': raw_text}

        recover_missing_venue_from_source(ref)

        assert ref['venue'] == expected_venue
        assert ref['journal'] == expected_venue

    def test_splits_journal_suffix_from_title_before_year(self):
        ref = {
            'title': (
                'Self, peer and teacher assessments: What is the level of '
                'relationship between them? European Journal of Education Studies'
            ),
            'venue': '',
            'journal': '',
            'raw_text': (
                '[37] Fatma Sasmaz Oren. Self, peer and teacher assessments: '
                'What is the level of relationship between them? European '
                'Journal of Education Studies, 2018.'
            ),
        }

        recover_missing_venue_from_source(ref)

        assert ref['title'] == (
            'Self, peer and teacher assessments: What is the level of '
            'relationship between them?'
        )
        assert ref['venue'] == 'European Journal of Education Studies'
        assert ref['journal'] == 'European Journal of Education Studies'

    def test_does_not_split_a_title_with_education_before_year(self):
        ref = {
            'title': 'Self-directed learning in education',
            'venue': '',
            'journal': '',
            'raw_text': '[1] A. Smith. Self-directed learning in education, 2018.',
        }

        recover_missing_venue_from_source(ref)

        assert ref['title'] == 'Self-directed learning in education'
        assert ref['venue'] == ''

    def test_does_not_strip_publisher_without_container_marker(self):
        ref = {
            'title': (
                'Designing Embedded Systems with PIC Microcontrollers Principles '
                'and applications'
            ),
            'venue': '',
            'raw_text': (
                '[2] G. Rao, "Designing Embedded Systems with PIC '
                'Microcontrollers Principles and applications," 1st ed., '
                'Elsevier, 2006.'
            ),
        }

        recover_missing_venue_from_source(ref)

        assert ref['venue'] == '1st ed., Elsevier'

    def test_does_not_promote_date_or_mismatched_title_to_venue(self):
        date_only = {
            'title': 'INVEST Alliance',
            'venue': '',
            'raw_text': '[7] "INVEST Alliance," Jul. 2021. Accessed: Oct. 2025.',
        }
        online_date_only = {
            'title': 'INVEST Alliance',
            'venue': '',
            'raw_text': (
                '[7] "INVEST Alliance," Jul. 2021. [Online]. Available: '
                'https://example.org/invest.'
            ),
        }
        online_url_domain = {
            'title': (
                'Malaysia Education Blueprint 2013-2025: Preschool to '
                'Post-Secondary Education,'
            ),
            'venue': '',
            'raw_text': (
                '[29] Ministry of Education Malaysia (MOE), Malaysia Education '
                'Blueprint 2013-2025: Preschool to Post-Secondary Education, '
                '2013. [Online]. Available: '
                'http://linkinghub.elsevier.com/retrieve/pii/S0742051X10001435'
            ),
        }
        mismatched = {
            'title': 'A different paper title',
            'venue': '',
            'raw_text': (
                '[1] A. Smith, "A useful paper," Journal of Testing, 2020.'
            ),
        }

        recover_missing_venue_from_source(date_only)
        recover_missing_venue_from_source(online_date_only)
        recover_missing_venue_from_source(online_url_domain)
        recover_missing_venue_from_source(mismatched)

        assert date_only['venue'] == ''
        assert online_date_only['venue'] == ''
        assert online_url_domain['venue'] == ''
        assert mismatched['venue'] == ''

    @pytest.mark.parametrize('venue', [
        '3DV',
        '2024 Conference on Empirical Methods in Natural Language Processing',
        'ICML 2024',
    ])
    def test_numbered_legitimate_venues_are_not_suspicious(self, venue):
        assert not is_suspicious_venue(venue)
        assert recover_acronym_year_venue(venue) == ''


class TestPathParity:
    """The CLI and the WebUI must produce the same corrected reference."""

    def test_cli_entry_point_applies_fixups(self):
        from refchecker.core.refchecker import ArxivReferenceChecker

        checker = ArxivReferenceChecker.__new__(ArxivReferenceChecker)
        ref = _ref()
        checker._fixup_reference_fields(ref)
        assert ref['venue'] == CLEAN_VENUE

    def test_hybrid_checker_applies_fixups(self):
        """The WebUI reaches this method directly, bypassing the CLI wrapper."""
        from refchecker.checkers.enhanced_hybrid_checker import (
            EnhancedHybridReferenceChecker,
        )

        checker = EnhancedHybridReferenceChecker.__new__(EnhancedHybridReferenceChecker)
        seen = {}

        def _core(reference):
            # Capture the venue as the verification logic actually sees it.
            seen['venue'] = reference.get('venue')
            return None, [], None

        checker._verify_reference_core = _core
        checker._postprocess_verification = lambda vd, e, u, ref: (vd, e, u)

        ref = _ref()
        try:
            checker.verify_reference(ref)
        except Exception:
            # Later stages need a fully constructed instance; the fixup has
            # already run by then, which is all this test asserts.
            pass

        assert seen.get('venue') == CLEAN_VENUE, (
            'The hybrid checker must repair fields before verifying, otherwise '
            'the WebUI skips the fixups entirely'
        )
        assert ref['venue'] == CLEAN_VENUE

    def test_both_paths_agree(self):
        from refchecker.core.refchecker import ArxivReferenceChecker

        cli_ref = _ref()
        ArxivReferenceChecker.__new__(ArxivReferenceChecker)._fixup_reference_fields(cli_ref)

        shared_ref = _ref()
        fixup_reference_fields(shared_ref)

        assert cli_ref == shared_ref


class TestNoDuplicateImplementation:
    """One implementation, so a fix can't reach some paths and miss others."""

    def test_core_delegates_rather_than_reimplementing(self):
        import inspect

        from refchecker.core.refchecker import ArxivReferenceChecker

        source = inspect.getsource(ArxivReferenceChecker._fixup_reference_fields)
        assert 'fixup_reference_fields(reference)' in source
        # The venue-as-title pattern list must exist in exactly one place.
        assert 'Proceedings of the' not in source
