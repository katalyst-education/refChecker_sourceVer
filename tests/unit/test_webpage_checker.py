from refchecker.checkers.webpage_checker import (
    WebPageChecker,
    detect_authentication_interstitial,
)


class DummyResponse:
    def __init__(self, html, url="https://example.com/page", status_code=200):
        self.content = html.encode("utf-8")
        self.url = url
        self.status_code = status_code
        self.headers = {"content-type": "text/html; charset=utf-8"}


def test_ai_vendor_model_docs_are_web_page_urls():
    checker = WebPageChecker()

    assert checker.is_web_page_url(
        "https://www.llama.com/docs/model-cards-and-prompt-formats/llama3_3/"
    )
    assert checker.is_web_page_url(
        "https://ai.meta.com/blog/llama-4-multimodal-intelligence/"
    )
    assert checker.is_web_page_url(
        "https://platform.openai.com/docs/models#gpt-4-1-mini"
    )
    assert checker.is_web_page_url(
        "https://www.anthropic.com/news/claude-4"
    )
    assert checker.is_web_page_url(
        "https://hkunlp.github.io/blog/2025/Polaris"
    )
    assert checker.is_web_page_url(
        "https://ai.gitcode.com/ascend-tribe/openPangu-Embedded-7B-DeepDiver"
    )


def test_any_cited_web_url_is_an_explicit_web_reference():
    checker = WebPageChecker()

    assert checker.is_explicit_web_reference({
        "title": "Periodensystem der Elemente",
        # Extracted references commonly retain the original link in
        # ``cited_url`` rather than normalising it to ``url``.
        "cited_url": "http://www.periodensystem.info/",
    })


def test_academic_source_url_is_reserved_for_scholarly_checker():
    checker = WebPageChecker()

    assert not checker.is_explicit_web_reference({
        "title": "Some paper",
        "venue": "arxiv.org",
        "url": "https://arxiv.org/abs/2402.07314",
    })


def test_scholarly_hosts_are_not_treated_as_organization_authored_pages():
    checker = WebPageChecker()

    urls = [
        "https://arxiv.org/abs/arXiv:1709.09657",
        "https://doi.org/10.1145/1234.5678",
        "https://dl.acm.org/doi/10.1145/1234.5678",
        "https://ieeexplore.ieee.org/document/1234567",
        "https://link.springer.com/article/10.1007/example",
        "https://pubmed.ncbi.nlm.nih.gov/12345678/",
    ]

    for url in urls:
        assert checker.is_scholarly_source_url(url)
        assert not checker.is_explicit_web_reference({"title": "Paper", "url": url})


def test_unrecognised_cited_site_is_fetched_before_title_search(monkeypatch):
    checker = WebPageChecker(request_delay=0)
    html = """
    <html><head><title>A useful reference page</title></head>
    <body><main><p>A useful reference page.</p></main></body></html>
    """
    monkeypatch.setattr(
        checker,
        "_respectful_request",
        lambda url: DummyResponse(html, url=url),
    )

    data, errors, url = checker.verify_reference({
        "title": "A useful reference page",
        "url": "https://ordinary-example.invalid/source",
    })

    assert data is not None
    assert errors == []
    assert url == "https://ordinary-example.invalid/source"


def test_model_card_and_release_venues_are_web_content():
    checker = WebPageChecker()

    assert checker._is_web_content_venue(
        "Model cards and prompt formats",
        "https://www.llama.com/docs/model-cards-and-prompt-formats/llama3_3/",
    )
    assert checker._is_web_content_venue(
        "Meta AI Blog",
        "https://ai.meta.com/blog/llama-4-multimodal-intelligence/",
    )
    assert checker._is_web_content_venue(
        "Technical report, Anthropic PBC",
        "https://www.anthropic.com/news/claude-4",
    )


def test_academic_arxiv_url_is_not_web_content_venue():
    checker = WebPageChecker()

    assert not checker._is_web_content_venue(
        "arXiv preprint arXiv:2402.07314",
        "https://arxiv.org/abs/2402.07314",
    )


def test_non_academic_url_can_verify_even_with_academic_venue(monkeypatch):
    checker = WebPageChecker(request_delay=0)

    html = """
    <html>
      <head><title>Introducing Claude</title></head>
      <body><main><p>Introducing Claude, Anthropic's helpful AI assistant.</p></main></body>
    </html>
    """
    monkeypatch.setattr(
        checker,
        "_respectful_request",
        lambda url: DummyResponse(html, url="https://www.anthropic.com/news/introducing-claude"),
    )

    verified_data, errors, url = checker.verify_raw_url_for_unverified_reference({
        "title": "Introducing Claude",
        "authors": ["Anthropic"],
        "year": 2023,
        "venue": "arXiv preprint arXiv:2301.00000",
        "url": "https://www.anthropic.com/index/introducing-claude/",
    })

    assert verified_data is not None
    assert errors == []
    assert url == "https://www.anthropic.com/index/introducing-claude/"


def test_institutional_sign_in_is_access_required_not_metadata_mismatch(monkeypatch):
    checker = WebPageChecker(request_delay=0)
    url = "http://search.ebscohost.com/login.aspx?direct=true&db=nlebk&AN=979090"
    html = """
    <html><head><title>Provider Sign In</title></head>
    <body><h1>Sign in</h1><p>Let's find your institution</p></body></html>
    """
    monkeypatch.setattr(
        checker,
        "_respectful_request",
        lambda requested: DummyResponse(
            html,
            url="https://login.provider.example/?requestIdentifier=example",
        ),
    )

    data, issues, checked_url = checker.verify_reference({
        "title": "Big Data - Fluch oder Segen?",
        "authors": ["Ronald Bachmann", "Guido Kemper", "Thomas Gerzer"],
        "year": 2014,
        "url": url,
    })

    assert data is None
    assert checked_url == url
    assert len(issues) == 1
    assert issues[0]["warning_type"] == "authentication"
    assert issues[0]["requires_authentication"] is True
    assert issues[0]["authentication_domain"] == "search.ebscohost.com"
    assert "Title mismatch" not in issues[0]["warning_details"]
    assert "Author mismatch" not in issues[0]["warning_details"]


def test_shibboleth_authentication_request_is_access_required(monkeypatch):
    checker = WebPageChecker(request_delay=0)
    url = "https://proxy.example.org/record/978-3-7643-7421-1"
    html = "<html><head><title>Shibboleth Authentication Request</title></head><body></body></html>"
    monkeypatch.setattr(
        checker,
        "_respectful_request",
        lambda requested: DummyResponse(html, url=url),
    )

    data, issues, checked_url = checker.verify_reference({
        "title": "Grundlagen der allgemeinen und anorganischen Chemie",
        "authors": ["Alfons Hädener", "Heinz Kaufmann"],
        "year": 2006,
        "url": url,
    })

    assert data is None
    assert checked_url == url
    assert len(issues) == 1
    assert issues[0]["warning_type"] == "authentication"
    assert issues[0]["requires_authentication"] is True


def test_authentication_title_is_access_required():
    from bs4 import BeautifulSoup

    assert detect_authentication_interstitial(
        BeautifulSoup("<html><head><title>Authentication</title></head><body></body></html>", "html.parser"),
        "https://identity.example.org/login",
    ) == "The source requires an authenticated browser session."


def test_login_shaped_permalink_needs_page_evidence_before_classification():
    html = """
    <html><head><title>Big Data - Fluch oder Segen?</title></head>
    <body><h1>Big Data - Fluch oder Segen?</h1><p>Ronald Bachmann</p></body></html>
    """
    from bs4 import BeautifulSoup

    assert detect_authentication_interstitial(
        BeautifulSoup(html, "html.parser"),
        "https://search.ebscohost.com/login.aspx?direct=true&AN=979090",
    ) is None


def test_article_about_login_is_not_an_authentication_interstitial():
    html = """
    <html><head><title>How to log in securely</title></head>
    <body><article><p>This guide explains account security for administrators.</p></article></body></html>
    """
    from bs4 import BeautifulSoup

    assert detect_authentication_interstitial(
        BeautifulSoup(html, "html.parser"),
        "https://docs.example.org/how-to-login",
    ) is None


def test_authenticated_catalogue_prefers_structured_record_metadata(monkeypatch):
    checker = WebPageChecker(request_delay=0)
    url = "https://search.ebscohost.com/login.aspx?direct=true&AN=979090"
    html = """
    <html><head>
      <title>EBSCOhost</title>
      <meta name="citation_title" content="Big Data - Fluch oder Segen?">
      <meta name="citation_author" content="Ronald Bachmann">
      <meta name="citation_author" content="Guido Kemper">
      <meta name="citation_author" content="Thomas Gerzer">
    </head><body><main>
      <p>Big Data - Fluch oder Segen? Ronald Bachmann, Guido Kemper, Thomas Gerzer.</p>
    </main></body></html>
    """
    monkeypatch.setattr(
        checker,
        "_respectful_request",
        lambda requested: DummyResponse(html, url=url),
    )

    data, issues, _ = checker.verify_reference({
        "title": "Big Data - Fluch oder Segen?",
        "authors": ["Ronald Bachmann", "Guido Kemper", "Thomas Gerzer"],
        "year": 2014,
        "url": url,
    })

    assert data["title"] == "Big Data - Fluch oder Segen?"
    assert data["authors"] == ["Ronald Bachmann", "Guido Kemper", "Thomas Gerzer"]
    assert issues == []


def test_dynamic_catalogue_uses_record_heading_and_visible_author_line(monkeypatch):
    checker = WebPageChecker(request_delay=0)
    url = "https://catalogue.example.org/record/979090"
    html = """
    <html><head><title>Research Databases</title></head><body><main>
      <h1>Big Data - Fluch oder Segen? Unternehmen im Spiegel gesellschaftlichen Wandels</h1>
      <div>Von: Ronald Bachmann; Guido Kemper; Thomas Gerzer</div>
      <p>Big Data, Datenmanagement und gesellschaftlicher Wandel.</p>
    </main></body></html>
    """
    monkeypatch.setattr(
        checker,
        "_respectful_request",
        lambda requested: DummyResponse(html, url=url),
    )

    data, issues, _ = checker.verify_reference({
        "title": "Big Data - Fluch oder Segen? Unternehmen im Spiegel des gesellschaftlichen Wandels",
        "authors": ["Ronald Bachmann", "Guido Kemper", "Thomas Gerzer"],
        "year": 2014,
        "url": url,
    })

    assert data["title"].startswith("Big Data - Fluch oder Segen?")
    assert data["authors"] == ["Ronald Bachmann", "Guido Kemper", "Thomas Gerzer"]
    assert not any(issue.get("warning_type") in {"title", "author"} for issue in issues)


def test_footer_project_credit_is_used_as_webpage_author(monkeypatch):
    checker = WebPageChecker(request_delay=0)
    url = "https://www.periodensystem.info/elemente/sauerstoff/"
    html = """
    <html><head><title>Sauerstoff</title></head><body>
      <main><h1>Sauerstoff</h1><p>Kenndaten zu Sauerstoff.</p></main>
      <footer>© 1995-2026 periodensystem.info. Ein Projekt von Andy Hoppe. Rendered in XHTML 1.0 Strict.</footer>
    </body></html>
    """
    monkeypatch.setattr(
        checker,
        "_respectful_request",
        lambda requested: DummyResponse(html, url=url),
    )

    data, issues, _ = checker.verify_reference({
        "title": "Sauerstoff",
        "authors": ["Andy Hoppe"],
        "year": 2020,
        "url": url,
    })

    assert data["authors"] == ["Andy Hoppe"]
    assert not any(issue.get("warning_type") == "author" for issue in issues)


def test_academic_url_with_academic_venue_still_requires_paper_verification(monkeypatch):
    checker = WebPageChecker(request_delay=0)

    html = """
    <html>
      <head><title>Some arXiv paper title</title></head>
      <body><main><p>Some arXiv paper title.</p></main></body>
    </html>
    """
    monkeypatch.setattr(
        checker,
        "_respectful_request",
        lambda url: DummyResponse(html, url="https://arxiv.org/abs/2402.07314"),
    )

    verified_data, errors, url = checker.verify_raw_url_for_unverified_reference({
        "title": "Some arXiv paper title",
        "authors": ["Example Author"],
        "year": 2024,
        "venue": "arXiv preprint arXiv:2402.07314",
        "url": "https://arxiv.org/abs/2402.07314",
    })

    assert verified_data is None
    assert errors == [{"error_type": "unverified", "error_details": "paper not verified but URL references paper"}]
    assert url == "https://arxiv.org/abs/2402.07314"
