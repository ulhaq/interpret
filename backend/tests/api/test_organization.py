from fastapi.testclient import TestClient


def test_user_organizations_list_only_shows_own_organization(
    organization2_admin_authenticated: TestClient,
) -> None:
    response = organization2_admin_authenticated.get("/v1/organizations")
    assert response.status_code == 200
    rs = response.json()
    assert len(rs) == 1
    assert rs[0]["name"] == "Globex Ltd"


def test_create_an_organization(admin_authenticated: TestClient) -> None:
    response = admin_authenticated.post(
        "/v1/organizations",
        json={
            "name": "test organization",
        },
    )
    assert response.status_code == 201
    rs = response.json()
    assert rs["id"] == 3
    assert rs["name"] == "test organization"
    assert rs["created_at"]
    assert rs["updated_at"]

    # Creator should be a member and have owner access
    response = admin_authenticated.get("/v1/organizations/3")
    assert response.status_code == 200

    response = admin_authenticated.get("/v1/organizations/3/users")
    assert response.status_code == 200
    rs = response.json()
    assert rs["total"] == 1
    assert rs["items"][0]["roles"][0]["name"] == "Owner"


def test_cannot_create_an_organization_with_already_existing_name(
    admin_authenticated: TestClient,
) -> None:
    response = admin_authenticated.post(
        "/v1/organizations",
        json={
            "name": "Acme Corp",
        },
    )
    assert response.status_code == 409
    rs = response.json()
    assert rs["msg"] == "Organization already exists. [name=Acme Corp]"


def test_patch_an_organization(admin_authenticated: TestClient) -> None:
    response = admin_authenticated.patch(
        "/v1/organizations/1",
        json={"name": "Patched Organization"},
    )
    assert response.status_code == 200
    rs = response.json()
    assert rs["id"] == 1
    assert rs["name"] == "Patched Organization"
    assert rs["created_at"]
    assert rs["updated_at"]


def test_patch_an_organization_with_partial_body(
    admin_authenticated: TestClient,
) -> None:
    response = admin_authenticated.patch("/v1/organizations/1", json={})
    assert response.status_code == 200
    rs = response.json()
    assert rs["id"] == 1
    assert rs["name"] == "Acme Corp"


def test_retrieve_an_organization(admin_authenticated: TestClient) -> None:
    response = admin_authenticated.get("/v1/organizations/1")
    assert response.status_code == 200
    rs = response.json()

    assert rs["id"] == 1
    assert rs["name"] == "Acme Corp"
    assert rs["created_at"]
    assert rs["updated_at"]


def test_delete_an_organization(admin_authenticated: TestClient) -> None:
    response = admin_authenticated.delete("/v1/organizations/1")
    assert response.status_code == 204
    # admin is the only member of org 1, so they are soft-deleted along with the org


def test_cannot_access_other_organization(admin_authenticated: TestClient) -> None:
    response = admin_authenticated.get("/v1/organizations/2")
    assert response.status_code == 403

    response = admin_authenticated.patch("/v1/organizations/2", json={"name": "Hacked"})
    assert response.status_code == 403

    response = admin_authenticated.delete("/v1/organizations/2")
    assert response.status_code == 403


def test_cannot_patch_an_organization_while_unauthorized(
    standard_authenticated: TestClient,
) -> None:
    response = standard_authenticated.patch(
        "/v1/organizations/1",
        json={"name": "Patched Organization"},
    )
    assert response.status_code == 403
    rs = response.json()
    assert rs["msg"] == "You are not authorized to perform this action"


def test_cannot_delete_an_organization_while_unauthorized(
    standard_authenticated: TestClient,
) -> None:
    response = standard_authenticated.delete("/v1/organizations/1")
    assert response.status_code == 403
    rs = response.json()
    assert rs["msg"] == "You are not authorized to perform this action"


def test_cannot_remove_owner_from_organization(admin_authenticated: TestClient) -> None:
    # User 1 is the Owner of org 1
    # removing the owner is blocked
    response = admin_authenticated.delete("/v1/users/1")
    assert response.status_code == 403
    rs = response.json()
    assert rs["error_code"] == "owner_removal"


async def test_transfer_ownership_success(admin_authenticated: TestClient) -> None:
    # Transfer ownership from user 1 (admin) to user 2 (standard)
    response = admin_authenticated.post(
        "/v1/organizations/1/transfer-ownership",
        json={"user_id": 2},
    )
    assert response.status_code == 204

    # Former owner (user 1) no longer has permissions
    # verify via 403 on org users endpoint
    assert admin_authenticated.get("/v1/organizations/1/users").status_code == 403


async def test_transfer_ownership_to_self_rejected(
    admin_authenticated: TestClient,
) -> None:
    response = admin_authenticated.post(
        "/v1/organizations/1/transfer-ownership",
        json={"user_id": 1},
    )
    assert response.status_code == 403


async def test_transfer_ownership_non_member_rejected(
    admin_authenticated: TestClient,
) -> None:
    # User 4 is in org 2, not org 1
    response = admin_authenticated.post(
        "/v1/organizations/1/transfer-ownership",
        json={"user_id": 4},
    )
    assert response.status_code == 404


def test_transfer_ownership_requires_owner(standard_authenticated: TestClient) -> None:
    response = standard_authenticated.post(
        "/v1/organizations/1/transfer-ownership",
        json={"user_id": 3},
    )
    assert response.status_code == 403


async def test_a_deleted_organizations_name_creates_a_new_organization(
    admin_authenticated: TestClient,
    organization2_admin_authenticated: TestClient,
) -> None:
    """Reusing a deleted organization's name never revives it: its data (here a
    conversation, the audit log and roles) must not reach whoever picks the name."""
    admin_authenticated.post(
        "/v1/interpret/conversations",
        json={"citizen_language": "ar"},
    )
    assert admin_authenticated.delete("/v1/organizations/1").status_code == 204

    other = organization2_admin_authenticated
    response = other.post("/v1/organizations", json={"name": "Acme Corp"})
    assert response.status_code == 201
    new_id = response.json()["id"]
    assert new_id != 1

    switched = other.post(
        "/v1/auth/switch-organization",
        json={"organization_id": new_id},
    )
    other.headers["Authorization"] = f"Bearer {switched.json()['access_token']}"
    assert other.get("/v1/interpret/conversations").json()["items"] == []
    assert [r["name"] for r in other.get("/v1/roles").json()["items"]] == ["Owner"]
    actions = {e["action"] for e in other.get("/v1/audit-logs").json()["items"]}
    assert actions <= {"org.create"}
