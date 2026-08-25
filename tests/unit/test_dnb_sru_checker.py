import logging
from unittest.mock import Mock, patch

from refchecker.checkers.dnb_sru import (
    DnbSruReferenceChecker,
    TibSruReferenceChecker,
    ZdbSruReferenceChecker,
    _has_substantial_contiguous_title,
)


MARC_RESPONSE = b"""<?xml version="1.0" encoding="UTF-8"?>
<searchRetrieveResponse xmlns="http://www.loc.gov/zing/srw/">
  <version>1.1</version>
  <numberOfRecords>1</numberOfRecords>
  <records><record><recordData>
    <marc:record xmlns:marc="http://www.loc.gov/MARC21/slim">
      <marc:leader>00000nam a2200000 c 4500</marc:leader>
      <marc:controlfield tag="001">123456789</marc:controlfield>
      <marc:controlfield tag="008">240101s2024    gw ||||| |||| 00||||eng c</marc:controlfield>
      <marc:datafield tag="016" ind1="7" ind2=" "><marc:subfield code="a">1234-5</marc:subfield></marc:datafield>
      <marc:datafield tag="020" ind1=" " ind2=" "><marc:subfield code="a">978-3-16-148410-0</marc:subfield></marc:datafield>
      <marc:datafield tag="022" ind1=" " ind2=" "><marc:subfield code="a">1234-5678</marc:subfield></marc:datafield>
      <marc:datafield tag="024" ind1="7" ind2=" "><marc:subfield code="a">10.1000/example</marc:subfield><marc:subfield code="2">doi</marc:subfield></marc:datafield>
      <marc:datafield tag="100" ind1="1" ind2=" "><marc:subfield code="a">Doe, Jane</marc:subfield></marc:datafield>
      <marc:datafield tag="245" ind1="1" ind2="0"><marc:subfield code="a">Reliable reference checking</marc:subfield><marc:subfield code="b">methods and systems</marc:subfield></marc:datafield>
      <marc:datafield tag="264" ind1=" " ind2="1"><marc:subfield code="b">Example Press</marc:subfield><marc:subfield code="c">2024</marc:subfield></marc:datafield>
    </marc:record>
  </recordData></record></records>
</searchRetrieveResponse>"""


@patch("refchecker.checkers.dnb_sru.requests.get")
def test_dnb_sru_uses_supported_endpoint_schema_and_page_size(mock_get, monkeypatch):
    response = Mock(status_code=200, content=MARC_RESPONSE, headers={})
    response.raise_for_status.return_value = None
    mock_get.return_value = response
    checker = DnbSruReferenceChecker(email="maintainer@example.org")
    monkeypatch.setattr(checker, "_wait_for_slot", lambda: None)

    results = checker.search('tit all "Reliable reference checking"', limit=1000)

    assert results[0]["title"] == "Reliable reference checking: methods and systems"
    assert results[0]["authors"] == [{"name": "Doe, Jane"}]
    assert results[0]["publication_year"] == 2024
    assert results[0]["doi"] == "10.1000/example"
    assert results[0]["isbn"] == "978-3-16-148410-0"
    assert mock_get.call_args.args[0] == "https://services.dnb.de/sru/dnb"
    params = mock_get.call_args.kwargs["params"]
    assert params["version"] == "1.1"
    assert params["recordSchema"] == "MARC21-xml"
    assert params["maximumRecords"] == 100


@patch("refchecker.checkers.dnb_sru.requests.get")
def test_tib_sru_uses_k10plus_endpoint_and_marcxml_schema(mock_get, monkeypatch):
    response = Mock(status_code=200, content=MARC_RESPONSE, headers={})
    response.raise_for_status.return_value = None
    mock_get.return_value = response
    checker = TibSruReferenceChecker(email="maintainer@example.org")
    monkeypatch.setattr(checker, "_wait_for_slot", lambda: None)

    results = checker.search('pica.ppn="123456789"')

    assert results[0]["ppn"] == "123456789"
    assert "idn" not in results[0]
    assert mock_get.call_args.args[0] == "https://sru.k10plus.de/opac-de-89"
    params = mock_get.call_args.kwargs["params"]
    assert params["version"] == "1.1"
    assert params["recordSchema"] == "marcxml"


def test_tib_maps_tibkat_url_to_ppn_and_returns_public_record_url(monkeypatch):
    checker = TibSruReferenceChecker()
    queries = []

    def fake_search(query, limit=10):
        queries.append(query)
        return [{
            "title": "Kostenrechnungs-Praxis: krp; Zeitschrift für Controlling, Accounting & System-Anwendungen",
            "authors": [],
            "publication_year": 1957,
            "ppn": "129529559",
            "issn": "0931-9077",
        }]

    monkeypatch.setattr(checker, "search", fake_search)
    data, errors, url = checker.verify_reference({
        "title": "Kostenrechnungs-Praxis",
        "url": "https://www.tib.eu/de/suchen/id/TIBKAT:129529559/example",
    })

    assert queries == ['pica.ppn="129529559"']
    assert data["ppn"] == "129529559"
    assert errors == []
    assert url == "https://www.tib.eu/de/suchen/id/TIBKAT:129529559"


@patch("refchecker.checkers.dnb_sru.requests.get")
def test_tib_trace_includes_query_result_candidates_and_match(mock_get, monkeypatch, caplog):
    response = Mock(status_code=200, content=MARC_RESPONSE, headers={})
    response.raise_for_status.return_value = None
    mock_get.return_value = response
    checker = TibSruReferenceChecker()
    monkeypatch.setattr(checker, "_wait_for_slot", lambda: None)

    with caplog.at_level(logging.INFO, logger="refchecker.checkers.dnb_sru"):
        data, errors, _ = checker.verify_reference({
            "title": "Reliable reference checking",
            "ppn": "123456789",
            "year": 2024,
        })

    messages = [record.getMessage() for record in caplog.records]
    assert any("stage=query_plan database=tib" in message for message in messages)
    assert any(
        "stage=search_result database=tib" in message
        and "result_count=1" in message
        and "Reliable reference checking" in message
        for message in messages
    )
    assert any("stage=match_result database=tib status=matched" in message for message in messages)
    assert data["ppn"] == "123456789"
    assert errors == []


def test_zdb_prefers_issn_query_and_returns_zdb_resource_url(monkeypatch):
    checker = ZdbSruReferenceChecker()
    queries = []

    def fake_search(query, limit=10):
        queries.append(query)
        return [{
            "title": "Journal of Reliable Reference Checking",
            "authors": [],
            "publication_year": 2020,
            "zdb_id": "1234-5",
            "issn": "1234-5678",
        }]

    monkeypatch.setattr(checker, "search", fake_search)
    data, errors, url = checker.verify_reference({
        "title": "Journal of Reliable Reference Checking",
        "issn": "1234-5678",
        "year": 2020,
    })

    assert queries == ['iss="1234-5678"']
    assert data["issn"] == "1234-5678"
    assert errors == []
    assert url == "https://ld.zdb-services.de/resource/1234-5"


def test_dnb_falls_back_from_missing_identifier_to_title(monkeypatch):
    checker = DnbSruReferenceChecker()
    queries = []

    def fake_search(query, limit=10):
        queries.append(query)
        if query.startswith("num="):
            return []
        return [{
            "title": "Reliable reference checking",
            "authors": [{"name": "Jane Doe"}],
            "publication_year": 2024,
            "idn": "123456789",
        }]

    monkeypatch.setattr(checker, "search", fake_search)
    data, errors, url = checker.verify_reference({
        "title": "Reliable reference checking",
        "authors": ["Jane Doe"],
        "year": 2024,
        "doi": "10.1000/example",
    })

    assert queries[0] == 'num="10.1000/example"'
    assert queries[1].startswith('tit all "Reliable reference checking"')
    assert data["idn"] == "123456789"
    assert errors == []
    assert url == "https://d-nb.info/123456789"


def test_dnb_accepts_cited_title_as_exact_segment_of_catalogue_title(monkeypatch):
    checker = DnbSruReferenceChecker()

    monkeypatch.setattr(checker, "search", lambda query, limit=10: [{
        "title": (
            "Deutschlands Zukunft als Produktionsstandort sichern - "
            "Umsetzungsempfehlungen für das Zukunftsprojekt Industrie 4.0: "
            "Abschlußbericht des Arbeitskreises Industrie 4.0"
        ),
        "authors": [{"name": "Hellinger, Ariane"}],
        "publication_year": 2013,
        "idn": "1155179897",
    }])

    data, errors, url = checker.verify_reference({
        "title": "Umsetzungsempfehlungen fuer das Zukunftsprojekt Industrie 4.0",
        "year": 2013,
    })

    assert data["idn"] == "1155179897"
    assert errors == []
    assert url == "https://d-nb.info/1155179897"


def test_dnb_delimited_segment_override_accepts_stale_low_fuzzy_score(monkeypatch):
    checker = DnbSruReferenceChecker()
    candidate = {
        "title": (
            "Deutschlands Zukunft als Produktionsstandort sichern - "
            "Umsetzungsempfehlungen für das Zukunftsprojekt Industrie 4.0: "
            "Abschlußbericht des Arbeitskreises Industrie 4.0"
        ),
        "authors": [{"name": "Hellinger, Ariane"}],
        "publication_year": 2013,
        "idn": "1155179897",
    }

    monkeypatch.setattr(checker, "search", lambda query, limit=10: [candidate])
    monkeypatch.setattr(
        "refchecker.checkers.dnb_sru.find_best_match",
        lambda records, cleaned_title, year, authors: (candidate, 0.562),
    )

    data, errors, url = checker.verify_reference({
        "title": "Umsetzungsempfehlungen für das Zukunftsprojekt Industrie 4.0",
        "year": 2013,
    })

    assert data["idn"] == "1155179897"
    assert errors == []
    assert url == "https://d-nb.info/1155179897"


def test_dnb_contiguous_title_fallback_is_substantial_and_conservative():
    assert _has_substantial_contiguous_title(
        "Umsetzungsempfehlungen für das Zukunftsprojekt Industrie 4.0",
        "Deutschlands Zukunft als Produktionsstandort sichern - "
        "Umsetzungsempfehlungen für das Zukunftsprojekt Industrie 4.0: Abschlussbericht",
    ) is True
    assert _has_substantial_contiguous_title(
        "Industrial production",
        "Germany's future industrial production final report",
    ) is False
