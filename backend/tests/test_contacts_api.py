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


# --- Week 5 Day 2: delete/rename/remove-member ------------------------


def test_delete_contact():
    created = client.post(
        "/api/v1/contacts", json={"name": "Adarsh", "email": "adarsh@example.com"}
    ).json()

    response = client.delete(f"/api/v1/contacts/{created['id']}")

    assert response.status_code == 204
    assert client.get(f"/api/v1/contacts/{created['id']}").status_code == 404


def test_delete_unknown_contact_returns_404():
    response = client.delete("/api/v1/contacts/999999")
    assert response.status_code == 404


def test_update_contact_email_to_a_duplicate_returns_409():
    client.post("/api/v1/contacts", json={"name": "Adarsh", "email": "adarsh@example.com"})
    rahul = client.post(
        "/api/v1/contacts", json={"name": "Rahul", "email": "rahul@example.com"}
    ).json()

    response = client.patch(f"/api/v1/contacts/{rahul['id']}", json={"email": "adarsh@example.com"})

    assert response.status_code == 409


def test_deleting_a_contact_removes_them_from_their_team():
    team = client.post("/api/v1/teams", json={"name": "AI Team"}).json()
    add_response = client.post(
        f"/api/v1/teams/{team['id']}/members", json={"name": "Adarsh", "email": "adarsh@example.com"}
    ).json()
    contact_id = add_response["members"][0]["id"]

    client.delete(f"/api/v1/contacts/{contact_id}")

    members = client.get(f"/api/v1/teams/{team['id']}/members").json()
    assert members == []


def test_list_teams():
    client.post("/api/v1/teams", json={"name": "AI Team"})
    response = client.get("/api/v1/teams")
    assert response.status_code == 200
    assert any(t["name"] == "AI Team" for t in response.json())


def test_rename_team():
    team = client.post("/api/v1/teams", json={"name": "AI Team"}).json()

    response = client.patch(f"/api/v1/teams/{team['id']}", json={"name": "AI Research Team"})

    assert response.status_code == 200
    assert response.json()["name"] == "AI Research Team"


def test_rename_unknown_team_returns_404():
    response = client.patch("/api/v1/teams/999999", json={"name": "New Name"})
    assert response.status_code == 404


def test_rename_team_to_a_name_already_in_use_returns_409():
    client.post("/api/v1/teams", json={"name": "AI Team"})
    sales = client.post("/api/v1/teams", json={"name": "Sales Team"}).json()

    response = client.patch(f"/api/v1/teams/{sales['id']}", json={"name": "AI Team"})

    assert response.status_code == 409


def test_delete_team():
    team = client.post("/api/v1/teams", json={"name": "AI Team"}).json()

    response = client.delete(f"/api/v1/teams/{team['id']}")

    assert response.status_code == 204
    assert client.get(f"/api/v1/teams/{team['id']}").status_code == 404


def test_delete_unknown_team_returns_404():
    response = client.delete("/api/v1/teams/999999")
    assert response.status_code == 404


def test_get_team_members_endpoint():
    team = client.post("/api/v1/teams", json={"name": "AI Team"}).json()
    client.post(
        f"/api/v1/teams/{team['id']}/members", json={"name": "Adarsh", "email": "adarsh@example.com"}
    )

    response = client.get(f"/api/v1/teams/{team['id']}/members")

    assert response.status_code == 200
    assert response.json()[0]["email"] == "adarsh@example.com"


def test_get_members_of_unknown_team_returns_404():
    response = client.get("/api/v1/teams/999999/members")
    assert response.status_code == 404


def test_remove_team_member():
    team = client.post("/api/v1/teams", json={"name": "AI Team"}).json()
    added = client.post(
        f"/api/v1/teams/{team['id']}/members", json={"name": "Adarsh", "email": "adarsh@example.com"}
    ).json()
    contact_id = added["members"][0]["id"]

    response = client.delete(f"/api/v1/teams/{team['id']}/members/{contact_id}")

    assert response.status_code == 200
    assert response.json()["members"] == []


def test_remove_team_member_not_on_team_returns_404():
    team = client.post("/api/v1/teams", json={"name": "AI Team"}).json()
    contact = client.post(
        "/api/v1/contacts", json={"name": "Adarsh", "email": "adarsh@example.com"}
    ).json()

    response = client.delete(f"/api/v1/teams/{team['id']}/members/{contact['id']}")

    assert response.status_code == 404


def test_remove_member_from_unknown_team_returns_404():
    contact = client.post(
        "/api/v1/contacts", json={"name": "Adarsh", "email": "adarsh@example.com"}
    ).json()
    response = client.delete(f"/api/v1/teams/999999/members/{contact['id']}")
    assert response.status_code == 404


def test_remove_unknown_contact_from_team_returns_404():
    team = client.post("/api/v1/teams", json={"name": "AI Team"}).json()
    response = client.delete(f"/api/v1/teams/{team['id']}/members/999999")
    assert response.status_code == 404


# --- Week 5 Day 2: direct recipient resolution endpoint -----------------


def test_resolve_endpoint_resolves_a_team_to_all_members():
    team = client.post("/api/v1/teams", json={"name": "AI Team"}).json()
    client.post(f"/api/v1/teams/{team['id']}/members", json={"name": "Alice", "email": "alice@example.com"})
    client.post(f"/api/v1/teams/{team['id']}/members", json={"name": "Bob", "email": "bob@example.com"})

    response = client.get("/api/v1/recipients/resolve", params={"reference": "AI Team"})

    assert response.status_code == 200
    body = response.json()
    assert body["resolved"] is True
    assert {r["email"] for r in body["recipients"]} == {"alice@example.com", "bob@example.com"}


def test_resolve_endpoint_resolves_a_direct_email():
    response = client.get("/api/v1/recipients/resolve", params={"reference": "someone@example.com"})
    assert response.status_code == 200
    body = response.json()
    assert body["resolved"] is True
    assert body["recipients"][0]["email"] == "someone@example.com"


def test_resolve_endpoint_never_invents_an_email_for_an_unknown_reference():
    response = client.get("/api/v1/recipients/resolve", params={"reference": "unknown"})

    assert response.status_code == 200
    body = response.json()
    assert body["resolved"] is False
    assert body["recipients"] == []
    assert body["reason"]
