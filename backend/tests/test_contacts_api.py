"""HTTP-level tests for POST/GET/PATCH /api/v1/contacts and
/api/v1/teams (app/api/v1/contacts.py, app/api/v1/teams.py). Goes through
the conftest.py-provided in-memory repository override, exactly like a
real request would hit the module-level singleton in production.
"""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


# --- Contacts --------------------------------------------------------------


def test_create_contact():
    response = client.post("/api/v1/contacts", json={"name": "Adarsh", "email": "adarsh@example.com"})

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Adarsh"
    assert body["email"] == "adarsh@example.com"
    assert isinstance(body["id"], int)


def test_create_contact_rejects_invalid_email():
    response = client.post("/api/v1/contacts", json={"name": "Adarsh", "email": "not-an-email"})
    assert response.status_code == 422


def test_retrieve_contact():
    created = client.post(
        "/api/v1/contacts", json={"name": "Adarsh", "email": "adarsh@example.com"}
    ).json()

    response = client.get(f"/api/v1/contacts/{created['id']}")

    assert response.status_code == 200
    assert response.json()["email"] == "adarsh@example.com"


def test_retrieve_unknown_contact_returns_404():
    response = client.get("/api/v1/contacts/999999")
    assert response.status_code == 404


def test_update_contact():
    created = client.post(
        "/api/v1/contacts", json={"name": "Adarsh", "email": "adarsh@example.com"}
    ).json()

    response = client.patch(f"/api/v1/contacts/{created['id']}", json={"name": "Adarsh K"})

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Adarsh K"
    assert body["email"] == "adarsh@example.com"


def test_create_duplicate_contact_email_returns_the_existing_contact():
    first = client.post(
        "/api/v1/contacts", json={"name": "Adarsh", "email": "adarsh@example.com"}
    ).json()
    second = client.post(
        "/api/v1/contacts", json={"name": "Someone Else", "email": "adarsh@example.com"}
    ).json()

    assert second["id"] == first["id"]


def test_list_contacts_includes_created_contacts():
    client.post("/api/v1/contacts", json={"name": "Adarsh", "email": "adarsh@example.com"})

    response = client.get("/api/v1/contacts")

    assert response.status_code == 200
    assert any(c["email"] == "adarsh@example.com" for c in response.json())


# --- Teams -------------------------------------------------------------


def test_create_team():
    response = client.post("/api/v1/teams", json={"name": "AI Team"})
    assert response.status_code == 200
    assert response.json()["name"] == "AI Team"


def test_retrieve_team_with_no_members():
    team = client.post("/api/v1/teams", json={"name": "Empty Team"}).json()

    response = client.get(f"/api/v1/teams/{team['id']}")

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Empty Team"
    assert body["members"] == []


def test_retrieve_unknown_team_returns_404():
    response = client.get("/api/v1/teams/999999")
    assert response.status_code == 404


def test_add_team_member_by_inline_name_and_email():
    team = client.post("/api/v1/teams", json={"name": "AI Team"}).json()

    response = client.post(
        f"/api/v1/teams/{team['id']}/members",
        json={"name": "Adarsh", "email": "adarsh@example.com"},
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["members"]) == 1
    assert body["members"][0]["email"] == "adarsh@example.com"


def test_add_multiple_team_members():
    team = client.post("/api/v1/teams", json={"name": "AI Team"}).json()
    client.post(
        f"/api/v1/teams/{team['id']}/members",
        json={"name": "Adarsh", "email": "adarsh@example.com"},
    )

    response = client.post(
        f"/api/v1/teams/{team['id']}/members",
        json={"name": "Rahul", "email": "rahul@example.com"},
    )

    assert response.status_code == 200
    emails = {m["email"] for m in response.json()["members"]}
    assert emails == {"adarsh@example.com", "rahul@example.com"}


def test_add_team_member_by_existing_contact_id():
    team = client.post("/api/v1/teams", json={"name": "AI Team"}).json()
    contact = client.post(
        "/api/v1/contacts", json={"name": "Adarsh", "email": "adarsh@example.com"}
    ).json()

    response = client.post(
        f"/api/v1/teams/{team['id']}/members", json={"contact_id": contact["id"]}
    )

    assert response.status_code == 200
    assert response.json()["members"][0]["id"] == contact["id"]


def test_adding_duplicate_team_member_does_not_duplicate():
    team = client.post("/api/v1/teams", json={"name": "AI Team"}).json()
    payload = {"name": "Adarsh", "email": "adarsh@example.com"}

    client.post(f"/api/v1/teams/{team['id']}/members", json=payload)
    response = client.post(f"/api/v1/teams/{team['id']}/members", json=payload)

    assert response.status_code == 200
    assert len(response.json()["members"]) == 1


def test_add_member_requires_contact_id_or_name_and_email():
    team = client.post("/api/v1/teams", json={"name": "AI Team"}).json()

    response = client.post(f"/api/v1/teams/{team['id']}/members", json={})

    assert response.status_code == 422


def test_add_member_to_unknown_team_returns_404():
    response = client.post(
        "/api/v1/teams/999999/members", json={"name": "Adarsh", "email": "adarsh@example.com"}
    )
    assert response.status_code == 404


def test_creating_duplicate_team_name_reuses_existing_team():
    first = client.post("/api/v1/teams", json={"name": "AI Team"}).json()
    second = client.post("/api/v1/teams", json={"name": "ai team"}).json()

    assert second["id"] == first["id"]
