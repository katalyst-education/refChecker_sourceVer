from fastapi.testclient import TestClient

from app import main


def test_health() -> None:
    client = TestClient(main.app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_extract_text_endpoint(monkeypatch) -> None:
    class FakeService:
        def __init__(self, *args, **kwargs):
            pass

        async def extract(self, paper_source, source_type):
            assert source_type == "text"
            assert "Doe" in paper_source
            return {
                "paper_title": "Pasted Text",
                "paper_source": paper_source,
                "extraction_method": "text",
                "bibliography_source_kind": "text",
                "references": [
                    {
                        "title": "A Study",
                        "authors": ["Jane Doe"],
                        "year": 2024,
                        "venue": "TestConf",
                        "url": None,
                    }
                ],
                "summary": {"total_refs": 1},
            }

    monkeypatch.setattr(main, "_get_service_class", lambda: FakeService)

    client = TestClient(main.app)
    response = client.post(
        "/extract/text",
        json={"source_text": "Doe. A Study. 2024.", "use_llm": False},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["summary"]["total_refs"] == 1
    assert data["references"][0]["title"] == "A Study"



