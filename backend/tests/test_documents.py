from backend.database import split_sections


def test_split_sections():
    text = "# Title\n\nIntro.\n\n## 1. First\n\nOne.\n\n## 2. Second part\n\nTwo.\n"
    assert split_sections(text) == [
        (0, "Title", "# Title\n\nIntro."),
        (1, "First", "## 1. First\n\nOne."),
        (2, "Second part", "## 2. Second part\n\nTwo."),
    ]


def test_list_sections(client):
    manual = client.get("/api/documents/claims_manual/sections").json()
    assert [s["section"] for s in manual] == list(range(15))
    assert manual[0]["title"] == "UnderCover Claims Handling Manual"
    assert manual[9] == {
        "document": "claims_manual",
        "section": 9,
        "title": "Repeat claims",
    }
    assert manual[14]["title"] == "Records"

    wording = client.get("/api/documents/policy_wording/sections").json()
    assert [s["section"] for s in wording] == list(range(13))
    assert wording[10]["title"] == "How we work out your payment"


def test_read_section(client):
    section = client.get("/api/documents/claims_manual/sections/10").json()
    assert section["title"] == "Meals without receipts"
    assert section["text"].startswith("## 10. Meals without receipts\n")
    assert "$35 per traveler" in section["text"]
    assert "## 11." not in section["text"]


def test_search_documents(client):
    for query in ("monkey", "MONKEY"):
        results = client.get("/api/documents/search", params={"query": query}).json()
        assert len(results) == 1
        assert results[0]["document"] == "claims_manual"
        assert results[0]["section"] == 7
        assert results[0]["title"] == "Interpretation notes"
        assert len(results[0]["lines"]) == 1
        assert results[0]["lines"][0].startswith("**Wild animals.**")


def test_search_finds_every_matching_line(client):
    results = client.get(
        "/api/documents/search", params={"query": "third claim"}
    ).json()
    assert [(r["document"], r["section"]) for r in results] == [("claims_manual", 9)]
    assert len(results[0]["lines"]) == 2


def test_search_in_both_documents(client):
    results = client.get("/api/documents/search", params={"query": "receipts"}).json()
    assert {r["document"] for r in results} == {"policy_wording", "claims_manual"}


def test_search_with_no_match(client):
    assert client.get("/api/documents/search", params={"query": "zebra"}).json() == []


def test_unknown_documents_and_sections(client):
    response = client.get("/api/documents/handbook/sections")
    assert response.status_code == 404
    assert response.json()["detail"] == "Document handbook not found"
    response = client.get("/api/documents/claims_manual/sections/99")
    assert response.status_code == 404
    assert response.json()["detail"] == "Section 99 of claims_manual not found"
    assert client.get("/api/documents/handbook/sections/1").status_code == 404


def test_search_needs_a_query(client):
    assert client.get("/api/documents/search", params={"query": ""}).status_code == 422
    assert client.get("/api/documents/search").status_code == 422
