from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from httpx import Headers
from pytest_mock import MockerFixture
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.bootstrap import ALL_PERMISSIONS, PERMISSION_DESCRIPTIONS
from src.foundation.models.organization import Organization
from src.foundation.models.user import User
from tests.conftest import TestSessionLocal
from tests.utils import (
    assert_filtering_of_items_list,
    assert_pagination,
    assert_sorting_of_items_list,
)

_descriptions_by_name = {str(k): v for k, v in PERMISSION_DESCRIPTIONS.items()}


def test_get_authenticated_user(admin_authenticated: TestClient) -> None:
    response = admin_authenticated.get("/v1/users/me")
    assert response.status_code == 200
    rs = response.json()
    assert rs["id"] == 1
    assert rs["name"] == "Alice Owner"
    assert rs["email"] == "admin@example.org"

    assert len(rs["roles"]) == 1
    assert rs["roles"][0]["id"] == 1
    assert rs["roles"][0]["name"] == "Owner"
    assert rs["roles"][0]["is_protected"] is True
    assert (
        rs["roles"][0]["description"]
        == "Full access to all system features and settings."
    )

    permissions = rs["roles"][0]["permissions"]
    assert len(permissions) == len(ALL_PERMISSIONS)

    permission_names = {p["name"] for p in permissions}
    assert permission_names == {p.value for p in ALL_PERMISSIONS}

    for p in permissions:
        assert p["name"] in _descriptions_by_name
        assert p["description"] == _descriptions_by_name[p["name"]]

    assert rs["created_at"]
    assert rs["updated_at"]


def test_invite_a_user(admin_authenticated: TestClient, mocker: MockerFixture) -> None:
    mocker.patch("src.foundation.services.user.send_email")
    response = admin_authenticated.post(
        "/v1/users/invite",
        json={"email": "new@testing.com", "role_ids": [2]},
    )
    assert response.status_code == 204


def test_patch_authenticated_user_profile(admin_authenticated: TestClient) -> None:
    response = admin_authenticated.patch("/v1/users/me", json={"name": "Admin Patched"})
    assert response.status_code == 200
    rs = response.json()
    assert rs["id"] == 1
    assert rs["name"] == "Admin Patched"
    assert rs["email"] == "admin@example.org"
    assert rs["created_at"]
    assert rs["updated_at"]


def test_patch_authenticated_user_profile_with_partial_body(
    admin_authenticated: TestClient,
) -> None:
    response = admin_authenticated.patch("/v1/users/me", json={})
    assert response.status_code == 200
    rs = response.json()
    assert rs["id"] == 1
    assert rs["name"] == "Alice Owner"
    assert rs["email"] == "admin@example.org"


def test_change_authenticated_user_password(
    admin_authenticated: TestClient,
    client: TestClient,
) -> None:
    response = admin_authenticated.post(
        "/v1/users/me/change-password",
        json={
            "password": "password",
            "new_password": "new password",
            "confirm_password": "new password",
        },
    )
    assert response.status_code == 200
    rs = response.json()
    assert rs["id"] == 1
    assert rs["name"] == "Alice Owner"
    assert rs["email"] == "admin@example.org"

    response = client.post(
        "/v1/auth/token",
        data={"username": "admin@example.org", "password": "new password"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    rs = response.json()
    access_token = rs["access_token"]

    response = client.get(
        "/v1/users/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert response.status_code == 200
    rs = response.json()
    assert rs["id"] == 1
    assert rs["name"] == "Alice Owner"
    assert rs["email"] == "admin@example.org"


def test_retrieve_a_user(admin_authenticated: TestClient) -> None:
    response = admin_authenticated.get("/v1/users/2")
    assert response.status_code == 200
    rs = response.json()

    assert rs["id"] == 2
    assert rs["name"] == "Bob Member"
    assert rs["email"] == "standard@example.org"
    assert len(rs["roles"]) == 1
    assert rs["roles"][0]["id"] == 2
    assert rs["roles"][0]["name"] == "Member"
    assert (
        rs["roles"][0]["description"] == "Work with the organization's data day to day."
    )

    permissions = rs["roles"][0]["permissions"]
    assert len(permissions) == 5

    permission_names = {p["name"] for p in permissions}
    assert permission_names == {
        "read:user",
        "read:role",
        "read:permission",
        "manage:api_token",
        "use:interpret",
    }

    for p in permissions:
        assert p["name"] in _descriptions_by_name
        assert p["description"] == _descriptions_by_name[p["name"]]

    assert rs["created_at"]
    assert rs["updated_at"]


def test_manage_roles_of_a_user(admin_authenticated: TestClient) -> None:
    # Assign the Member role to user 3 (who currently has no roles)
    response = admin_authenticated.post(
        "/v1/users/3/roles",
        json={"role_ids": [2]},
    )
    assert response.status_code == 200
    rs = response.json()
    assert rs["id"] == 3
    assert len(rs["roles"]) == 1
    assert rs["roles"][0]["id"] == 2
    assert rs["roles"][0]["name"] == "Member"

    # Remove all roles from user 3
    response = admin_authenticated.post(
        "/v1/users/3/roles",
        json={"role_ids": []},
    )
    assert response.status_code == 200
    rs = response.json()
    assert rs["id"] == 3
    assert len(rs["roles"]) == 0


def test_cannot_manage_own_roles(admin_authenticated: TestClient) -> None:
    response = admin_authenticated.post(
        "/v1/users/1/roles",
        json={
            "role_ids": [1, 2],
        },
    )

    assert response.status_code == 403
    rs = response.json()
    assert rs["msg"] == "You are not allowed to manage your own roles"


def test_cannot_invite_a_user_while_unauthorized(client: TestClient) -> None:
    rs = client.post(
        "/v1/auth/token",
        data={"username": "no_roles@example.org", "password": "password"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    ).json()

    response = client.post(
        "/v1/users/invite",
        json={"email": "new@testing.com", "role_ids": []},
        headers={"Authorization": f"Bearer {rs['access_token']}"},
    )
    assert response.status_code == 403
    rs = response.json()
    assert rs["msg"] == "You are not authorized to perform this action"


def test_patch_a_user(admin_authenticated: TestClient) -> None:
    response = admin_authenticated.patch(
        "/v1/users/2",
        json={"name": "Standard Patched"},
    )
    assert response.status_code == 200
    rs = response.json()
    assert rs["id"] == 2
    assert rs["name"] == "Standard Patched"
    assert rs["email"] == "standard@example.org"
    assert rs["created_at"]
    assert rs["updated_at"]


def test_patch_a_user_with_partial_body(admin_authenticated: TestClient) -> None:
    response = admin_authenticated.patch("/v1/users/2", json={"name": "Only Name"})
    assert response.status_code == 200
    rs = response.json()
    assert rs["id"] == 2
    assert rs["name"] == "Only Name"
    assert rs["email"] == "standard@example.org"


def test_admin_cannot_change_member_email(admin_authenticated: TestClient) -> None:
    # The email is the member's login across all their orgs - not org-editable.
    response = admin_authenticated.patch(
        "/v1/users/2",
        json={"email": "patched@example.org"},
    )
    assert response.status_code == 422
    member = admin_authenticated.get("/v1/users/2").json()
    assert member["email"] == "standard@example.org"


def test_cannot_patch_own_email_directly(admin_authenticated: TestClient) -> None:
    # Own email changes go through POST /users/me/email (re-auth + confirm).
    response = admin_authenticated.patch(
        "/v1/users/me",
        json={"email": "patched@example.org"},
    )
    assert response.status_code == 422
    assert admin_authenticated.get("/v1/users/me").json()["email"] == (
        "admin@example.org"
    )


def test_cannot_patch_a_user_while_unauthorized(
    standard_authenticated: TestClient,
) -> None:
    response = standard_authenticated.patch("/v1/users/1", json={"name": "Hacked"})
    assert response.status_code == 403
    rs = response.json()
    assert rs["msg"] == "You are not authorized to perform this action"


def test_cannot_remove_last_owner_via_manage_roles(
    admin_authenticated: TestClient,
    client: TestClient,
) -> None:
    # Get the MANAGE_USER_ROLE permission ID
    rs = admin_authenticated.get("/v1/permissions?page_size=50").json()
    manage_role_perm_id = next(
        p["id"] for p in rs["items"] if p["name"] == "manage:user_role"
    )

    # Create a role with only MANAGE_USER_ROLE (not Owner)
    rs = admin_authenticated.post(
        "/v1/roles",
        json={"name": "Manager", "description": "Role manager"},
    ).json()
    manager_role_id = rs["id"]
    admin_authenticated.post(
        f"/v1/roles/{manager_role_id}/permissions",
        json={"permission_ids": [manage_role_perm_id]},
    )

    # Assign Manager role to user 2 (standard user)
    admin_authenticated.post("/v1/users/2/roles", json={"role_ids": [manager_role_id]})

    # Login as user 2 (has MANAGE_USER_ROLE but not Owner role)
    rs = client.post(
        "/v1/auth/token",
        data={"username": "standard@example.org", "password": "password"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    ).json()

    client.headers = Headers({"Authorization": f"Bearer {rs['access_token']}"})

    # Try to remove Owner from user 1 (the only Owner) > should fail
    response = client.post("/v1/users/1/roles", json={"role_ids": []})
    assert response.status_code == 403
    rs = response.json()
    assert rs["error_code"] == "owner_role_assignment"


# --- GET /v1/users ---


def test_get_all_users(admin_authenticated: TestClient) -> None:
    response = admin_authenticated.get("/v1/users")
    assert response.status_code == 200
    rs = response.json()
    assert rs["page_number"] == 1
    assert rs["page_size"] == 10
    assert rs["total"] == 3
    assert len(rs["items"]) == 3
    emails = {u["email"] for u in rs["items"]}
    assert emails == {
        "admin@example.org",
        "standard@example.org",
        "no_roles@example.org",
    }


@pytest.mark.parametrize(
    ("page_number", "page_size", "page_total", "total"),
    [
        (1, 10, 3, 3),
        (2, 10, 0, 3),
    ],
)
def test_paginate_users(
    page_number: int,
    page_size: int,
    page_total: int,
    total: int,
    admin_authenticated: TestClient,
) -> None:
    response = admin_authenticated.get(
        f"/v1/users?page_number={page_number}&page_size={page_size}",
    )
    assert response.status_code == 200
    assert_pagination(response.json(), page_number, page_size, page_total, total)


@pytest.mark.parametrize(
    "sort",
    ["id", "-id", "name", "-name", "created_at", "-created_at"],
)
def test_sort_users(sort: str, admin_authenticated: TestClient) -> None:
    response = admin_authenticated.get(f"/v1/users?sort={sort}&page_size=50")
    assert response.status_code == 200
    assert_sorting_of_items_list(response.json()["items"], [sort])


@pytest.mark.parametrize(
    ("fields", "values", "operators", "total"),
    [
        # Single field, single value
        (["name"], [["Alice Owner"]], ["eq"], 1),
        (["name"], [["alice owner"]], ["eq"], 0),  # case-sensitive: no match
        (["email"], [["admin@example.org"]], ["eq"], 1),
        (["name"], [["alice"]], ["ico"], 1),
        (["email"], [["example"]], ["ico"], 3),  # all users share the domain
        (["id"], [[2]], ["gte"], 2),  # Bob, Carol
        # Single field, multiple values
        (["id"], [[1, 2]], ["in"], 2),
        (["name"], [["Alice Owner", "Bob Member"]], ["in"], 2),
        (["id"], [[1, 2]], ["between"], 2),
        (["id"], [[1, 3]], ["between"], 3),
    ],
)
def test_filter_users(
    fields: list,
    values: list,
    operators: list,
    total: int,
    admin_authenticated: TestClient,
) -> None:
    params = "&".join(
        f"{field}__{op}={','.join(str(v) for v in value)}"
        for field, value, op in zip(fields, values, operators, strict=False)
    )
    response = admin_authenticated.get(f"/v1/users?{params}&page_size=50")
    assert response.status_code == 200
    rs = response.json()

    assert len(rs["items"]) == total

    filter_data = list(zip(fields, values, operators, strict=False))
    assert_filtering_of_items_list(rs["items"], filter_data)


@pytest.mark.parametrize(
    ("params", "total"),
    [
        # AND: name ico "alice" AND email contains "admin" > 1 (Alice)
        ("name__ico=alice&email__ico=admin", 1),
        # AND: id >= 2 (Bob, Carol) AND email ico "standard" (Bob) > 1
        ("id__gte=2&email__ico=standard", 1),
        # AND: id between 1 and 2 AND name ico "bob" > 1
        ("id__between=1,2&name__ico=bob", 1),
    ],
)
def test_filter_users_multi_field(
    params: str,
    total: int,
    admin_authenticated: TestClient,
) -> None:
    response = admin_authenticated.get(f"/v1/users?{params}&page_size=50")
    assert response.status_code == 200
    assert response.json()["total"] == total


@pytest.mark.parametrize(
    ("q", "expected_count", "matched_field", "matched_value"),
    [
        ("alice", 1, "name", "Alice Owner"),
        ("ALICE", 1, "name", "Alice Owner"),
        ("example.org", 3, None, None),
        ("standard@", 1, "email", "standard@example.org"),
        ("xyznonexistent", 0, None, None),
    ],
)
def test_search_users(
    q: str,
    expected_count: int,
    matched_field: str | None,
    matched_value: str | None,
    admin_authenticated: TestClient,
) -> None:
    response = admin_authenticated.get(f"/v1/users?q={q}&page_size=50")
    assert response.status_code == 200
    rs = response.json()
    assert rs["total"] == expected_count
    assert len(rs["items"]) == expected_count
    if matched_field and matched_value:
        assert all(
            q.casefold() in item[matched_field].casefold() for item in rs["items"]
        )


def test_search_users_returns_empty_for_blank_query(
    admin_authenticated: TestClient,
) -> None:
    response = admin_authenticated.get("/v1/users?q=&page_size=50")
    assert response.status_code == 200
    assert response.json()["total"] == 3


def test_cannot_filter_users_by_invalid_operator(
    admin_authenticated: TestClient,
) -> None:
    response = admin_authenticated.get("/v1/users?name__notanop=alice")
    assert response.status_code == 422
    assert "notanop" in response.json()["msg"]


def test_cannot_sort_users_by_invalid_field(admin_authenticated: TestClient) -> None:
    response = admin_authenticated.get("/v1/users?sort=description")
    assert response.status_code == 422
    assert "description" in response.json()["msg"]


def test_cannot_get_users_while_unauthorized(client: TestClient) -> None:
    rs = client.post(
        "/v1/auth/token",
        data={"username": "no_roles@example.org", "password": "password"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    ).json()
    response = client.get(
        "/v1/users",
        headers={"Authorization": f"Bearer {rs['access_token']}"},
    )
    assert response.status_code == 403
    assert response.json()["msg"] == "You are not authorized to perform this action"


def test_cannot_assign_owner_role_via_manage_roles(
    admin_authenticated: TestClient,
) -> None:
    response = admin_authenticated.post("/v1/users/3/roles", json={"role_ids": [1]})
    assert response.status_code == 403
    rs = response.json()
    assert rs["error_code"] == "owner_role_assignment"


def test_cannot_remove_owner_role_via_manage_roles(
    admin_authenticated: TestClient,
    client: TestClient,
) -> None:
    # Give user 2 a role with MANAGE_USER_ROLE so they can call manage_roles
    rs = admin_authenticated.get("/v1/permissions?page_size=50").json()
    manage_role_perm_id = next(
        p["id"] for p in rs["items"] if p["name"] == "manage:user_role"
    )
    rs = admin_authenticated.post(
        "/v1/roles",
        json={"name": "Manager", "description": "Role manager"},
    ).json()
    manager_role_id = rs["id"]
    admin_authenticated.post(
        f"/v1/roles/{manager_role_id}/permissions",
        json={"permission_ids": [manage_role_perm_id]},
    )
    admin_authenticated.post("/v1/users/2/roles", json={"role_ids": [manager_role_id]})

    # Login as user 2 and try to strip user 1's Owner role
    rs = client.post(
        "/v1/auth/token",
        data={"username": "standard@example.org", "password": "password"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    ).json()
    client.headers = Headers({"Authorization": f"Bearer {rs['access_token']}"})

    response = client.post("/v1/users/1/roles", json={"role_ids": []})
    assert response.status_code == 403
    rs = response.json()
    assert rs["error_code"] == "owner_role_assignment"


def test_export_my_data(standard_authenticated: TestClient) -> None:
    response = standard_authenticated.get("/v1/users/me/export")
    assert response.status_code == 200
    rs = response.json()
    assert rs["user"]["email"] == "standard@example.org"
    assert "organizations" in rs
    assert "api_tokens" in rs
    assert "audit_logs" in rs


def test_cannot_export_data_while_unauthorized(client: TestClient) -> None:
    response = client.get("/v1/users/me/export")
    assert response.status_code == 401


def test_delete_my_account(standard_authenticated: TestClient) -> None:
    response = standard_authenticated.request(
        "DELETE",
        "/v1/users/me",
        json={"current_password": "password"},
    )
    assert response.status_code == 204


def test_cannot_delete_account_with_wrong_password(
    standard_authenticated: TestClient,
) -> None:
    response = standard_authenticated.request(
        "DELETE",
        "/v1/users/me",
        json={"current_password": "wrongpassword"},
    )
    assert response.status_code == 401


def test_owner_cannot_delete_account(admin_authenticated: TestClient) -> None:
    response = admin_authenticated.request(
        "DELETE",
        "/v1/users/me",
        json={"current_password": "password"},
    )
    assert response.status_code == 403
    assert response.json()["error_code"] == "owner_removal"


def test_cannot_delete_account_while_unauthorized(client: TestClient) -> None:
    response = client.request(
        "DELETE",
        "/v1/users/me",
        json={"current_password": "password"},
    )
    assert response.status_code == 401


def test_deleted_role_excluded_from_user_roles(admin_authenticated: TestClient) -> None:
    # Standard user (id=2) starts with the "Member" role
    response = admin_authenticated.get("/v1/users/2")
    assert response.status_code == 200
    assert len(response.json()["roles"]) == 1
    assert response.json()["roles"][0]["name"] == "Member"

    # Admin soft-deletes the role
    response = admin_authenticated.delete("/v1/roles/2")
    assert response.status_code == 204

    # The soft-deleted role must not appear in the user's roles
    response = admin_authenticated.get("/v1/users/2")
    assert response.status_code == 200
    assert response.json()["roles"] == []


async def test_deleted_user_excluded_from_organization_users() -> None:
    # Soft-delete the standard user (id=2) directly
    async with TestSessionLocal() as session:
        user = await session.get(User, 2)
        assert user is not None
        user.deleted_at = datetime.now(UTC)
        await session.commit()

    # Load org 1 via the relationship and verify the soft-deleted user is excluded
    async with TestSessionLocal() as session:
        result = await session.execute(
            select(Organization)
            .where(Organization.id == 1)
            .options(selectinload(Organization.users)),
        )
        org = result.scalar_one()
        user_ids = {u.id for u in org.users}
        assert 1 in user_ids  # admin still present
        assert 2 not in user_ids  # soft-deleted user excluded
