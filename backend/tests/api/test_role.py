from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from src.bootstrap import ALL_PERMISSIONS, PERMISSION_DESCRIPTIONS
from src.foundation.enums import Permission
from src.foundation.models.permission import Permission as PermissionModel
from tests.conftest import TestSessionLocal
from tests.utils import (
    assert_filtering_of_items_list,
    assert_pagination,
    assert_sorting_of_items_list,
)

_descriptions_by_name = {str(k): v for k, v in PERMISSION_DESCRIPTIONS.items()}

TOTAL_PERMISSIONS = len(ALL_PERMISSIONS)


def _assert_all_permissions(permissions: list[dict]) -> None:
    assert len(permissions) == TOTAL_PERMISSIONS
    perm_names = {p["name"] for p in permissions}
    assert perm_names == {p.value for p in ALL_PERMISSIONS}
    for p in permissions:
        assert p["description"] == _descriptions_by_name[p["name"]]


def test_get_all_roles(admin_authenticated: TestClient) -> None:
    response = admin_authenticated.get("/v1/roles")
    assert response.status_code == 200
    rs = response.json()
    assert rs["page_number"] == 1
    assert rs["page_size"] == 10
    assert rs["total"] == 2

    assert len(rs["items"]) == 2
    assert rs["items"][0]["id"] == 1
    assert rs["items"][0]["name"] == "Owner"
    assert (
        rs["items"][0]["description"]
        == "Full access to all system features and settings."
    )
    assert rs["items"][0]["is_protected"] is True

    _assert_all_permissions(rs["items"][0]["permissions"])
    assert rs["items"][0]["created_at"]
    assert rs["items"][0]["updated_at"]

    # The Member role is a generic, non-owner example role seeded for dev/tests;
    # newly created organizations get only the Owner role.
    assert rs["items"][1]["id"] == 2
    assert rs["items"][1]["name"] == "Member"
    assert (
        rs["items"][1]["description"] == "Work with the organization's data day to day."
    )
    assert rs["items"][1]["is_protected"] is False
    assert len(rs["items"][1]["permissions"]) == 5
    member_perm_names = {p["name"] for p in rs["items"][1]["permissions"]}
    assert member_perm_names == {
        "read:user",
        "read:role",
        "read:permission",
        "manage:api_token",
        "use:interpret",
    }
    assert rs["items"][1]["created_at"]
    assert rs["items"][1]["updated_at"]


@pytest.mark.parametrize(
    ("page_number", "page_size", "page_total", "total"),
    [
        (1, 10, 2, 2),
        (2, 10, 0, 2),
    ],
)
def test_paginate_roles(
    page_number: int,
    page_size: int,
    page_total: int,
    total: int,
    admin_authenticated: TestClient,
) -> None:
    response = admin_authenticated.get(
        f"/v1/roles?page_number={page_number}&page_size{page_size}",
    )
    assert response.status_code == 200
    rs = response.json()

    assert_pagination(rs, page_number, page_size, page_total, total)


@pytest.mark.parametrize(
    "sort",
    [
        ("id"),
        ("-id"),
        ("name"),
        ("-name"),
        ("description"),
        ("-description"),
        ("name,description"),
        ("-name,-description"),
        ("-name,description"),
        ("name,-description"),
        ("created_at"),
        ("-created_at"),
        ("updated_at"),
        ("-updated_at"),
    ],
)
def test_sort_roles(sort: str, admin_authenticated: TestClient) -> None:
    response = admin_authenticated.get(f"/v1/roles?sort={sort}")
    assert response.status_code == 200
    rs = response.json()

    assert_sorting_of_items_list(rs["items"], sort.split(","))


@pytest.mark.parametrize(
    ("fields", "values", "operators", "total"),
    [
        # Single field, single value (org 1 has Owner id=1, Member id=2)
        (["id"], [[1]], ["eq"], 1),
        (["name"], [["Owner"]], ["eq"], 1),
        (["name"], [["member"]], ["ico"], 1),
        (["name"], [["e"]], ["co"], 2),  # Owner, Member both contain 'e'
        (["description"], [["access"]], ["ico"], 1),  # Owner only
        (["id"], [[2]], ["gte"], 1),  # Member (org 2 roles are not visible)
        # Single field, multiple values
        (["id"], [[0, 1]], ["between"], 1),
        (["id"], [[1, 2]], ["between"], 2),
        (["id"], [[1, 2, 3]], ["in"], 2),
        (["name"], [["Owner", "Member"]], ["in"], 2),
        # Other meaningful
        (
            ["created_at"],
            [["2025-04-22T14:04:38.586226", "2050-09-22T14:04:38.586226"]],
            ["between"],
            2,
        ),
    ],
)
def test_filter_roles(
    fields: list[str],
    values: list[list],
    operators: list[str],
    total: int,
    admin_authenticated: TestClient,
) -> None:
    params = "&".join(
        f"{field}__{op}={','.join(str(v) for v in value)}"
        for field, value, op in zip(fields, values, operators, strict=False)
    )
    response = admin_authenticated.get(f"/v1/roles?{params}&page_size=50")
    assert response.status_code == 200
    rs = response.json()

    assert len(rs["items"]) == total

    filter_data = list(zip(fields, values, operators, strict=False))
    assert_filtering_of_items_list(rs["items"], filter_data)


@pytest.mark.parametrize(
    ("params", "total"),
    [
        # AND: name contains "n" (Owner) AND description contains "access"
        # (Owner) > 1 overlap
        ("name__co=n&description__ico=access", 1),
        # AND: id >= 1 (Owner, Member) AND name contains "er" (Owner, Member)
        ("id__gte=1&name__co=er", 2),
        # AND: name="Owner" AND description contains "full" > 1
        ("name__eq=Owner&description__ico=full", 1),
        # AND: id between 1 and 2 AND name ico "member" > 1
        ("id__between=1,2&name__ico=member", 1),
    ],
)
def test_filter_roles_multi_field(
    params: str,
    total: int,
    admin_authenticated: TestClient,
) -> None:
    response = admin_authenticated.get(f"/v1/roles?{params}&page_size=50")
    assert response.status_code == 200
    assert response.json()["total"] == total


@pytest.mark.parametrize(
    ("q", "expected_count"),
    [
        ("owner", 1),
        ("OWNER", 1),
        ("full access", 1),
        ("access", 1),
        ("xyznonexistent", 0),
    ],
)
def test_search_roles(
    q: str,
    expected_count: int,
    admin_authenticated: TestClient,
) -> None:
    response = admin_authenticated.get(f"/v1/roles?q={q}&page_size=50")
    assert response.status_code == 200
    rs = response.json()
    assert rs["total"] == expected_count
    assert len(rs["items"]) == expected_count


def test_search_roles_returns_empty_for_blank_query(
    admin_authenticated: TestClient,
) -> None:
    response = admin_authenticated.get("/v1/roles?q=&page_size=50")
    assert response.status_code == 200
    assert response.json()["total"] == 2


def test_cannot_filter_roles_by_invalid_operator(
    admin_authenticated: TestClient,
) -> None:
    response = admin_authenticated.get("/v1/roles?name__notanop=owner")
    assert response.status_code == 422
    assert "notanop" in response.json()["msg"]


def test_cannot_sort_roles_by_invalid_field(admin_authenticated: TestClient) -> None:
    response = admin_authenticated.get("/v1/roles?sort=email")
    assert response.status_code == 422
    assert "email" in response.json()["msg"]


def test_create_a_role(admin_authenticated: TestClient) -> None:
    response = admin_authenticated.post(
        "/v1/roles",
        json={
            "name": "test role",
            "description": "description of test role",
        },
    )
    assert response.status_code == 201
    rs = response.json()
    assert rs["id"] == 5
    assert rs["name"] == "test role"
    assert rs["description"] == "description of test role"
    assert rs["organization_id"] == 1

    assert rs["permissions"] == []

    assert rs["created_at"]
    assert rs["updated_at"]


def test_patch_a_role(admin_authenticated: TestClient) -> None:
    response = admin_authenticated.patch(
        "/v1/roles/2",
        json={
            "name": "Basic",
            "description": "Basic Access",
        },
    )
    assert response.status_code == 200
    rs = response.json()
    assert rs["id"] == 2
    assert rs["name"] == "Basic"
    assert rs["description"] == "Basic Access"
    assert rs["created_at"]
    assert rs["updated_at"]


def test_patch_a_role_with_partial_body(admin_authenticated: TestClient) -> None:
    response = admin_authenticated.patch("/v1/roles/2", json={})
    assert response.status_code == 200
    rs = response.json()
    assert rs["id"] == 2
    assert rs["name"] == "Member"
    assert rs["description"] == "Work with the organization's data day to day."


def test_retrieve_a_role(admin_authenticated: TestClient) -> None:
    response = admin_authenticated.get("/v1/roles/1")
    assert response.status_code == 200
    rs = response.json()

    assert rs["id"] == 1
    assert rs["name"] == "Owner"
    assert rs["description"] == "Full access to all system features and settings."
    assert rs["is_protected"] is True

    _assert_all_permissions(rs["permissions"])

    assert rs["created_at"]
    assert rs["updated_at"]


def test_manage_permissions_of_a_role(admin_authenticated: TestClient) -> None:
    response = admin_authenticated.get("/v1/permissions?page_size=50")
    all_perms = response.json()["items"]
    user_perm_ids = [
        p["id"]
        for p in all_perms
        if "user" in p["name"] or "role" in p["name"] or "permission" in p["name"]
    ]

    response = admin_authenticated.post(
        "/v1/roles/2/permissions",
        json={
            "permission_ids": user_perm_ids,
        },
    )
    assert response.status_code == 200
    rs = response.json()
    assert rs["id"] == 2
    assert rs["name"] == "Member"
    assert len(rs["permissions"]) == len(user_perm_ids)

    assert rs["created_at"]
    assert rs["updated_at"]

    update_organization_id = next(
        p["id"] for p in all_perms if p["name"] == "update:organization"
    )
    response = admin_authenticated.post(
        "/v1/roles/2/permissions",
        json={
            "permission_ids": [update_organization_id],
        },
    )
    assert response.status_code == 200
    rs = response.json()
    assert rs["id"] == 2
    assert rs["name"] == "Member"

    assert len(rs["permissions"]) == 1
    assert rs["permissions"][0]["name"] == "update:organization"
    assert (
        rs["permissions"][0]["description"]
        == "Allows the user to update organization accounts."
    )

    assert rs["created_at"]
    assert rs["updated_at"]


def test_delete_a_role(admin_authenticated: TestClient) -> None:
    response = admin_authenticated.delete("/v1/roles/2")
    assert response.status_code == 204

    response = admin_authenticated.get("/v1/roles/2")
    assert response.status_code == 404


def test_cannot_get_non_existent_role(admin_authenticated: TestClient) -> None:
    response = admin_authenticated.get("/v1/roles/0")
    assert response.status_code == 404
    rs = response.json()
    assert rs["msg"] == "Role not found. [identifier=0]"


def test_cannot_create_a_role_with_already_existing_name(
    admin_authenticated: TestClient,
) -> None:
    response = admin_authenticated.post(
        "/v1/roles",
        json={
            "name": "Owner",
            "description": "description of test role",
        },
    )
    assert response.status_code == 409
    rs = response.json()
    assert rs["msg"] == "Role already exists. [name=Owner]"


def test_cannot_patch_protected_role(admin_authenticated: TestClient) -> None:
    response = admin_authenticated.patch("/v1/roles/1", json={"name": "Hacked"})
    assert response.status_code == 403
    rs = response.json()
    assert rs["error_code"] == "protected_role_modification"


def test_cannot_delete_protected_role(admin_authenticated: TestClient) -> None:
    response = admin_authenticated.delete("/v1/roles/1")
    assert response.status_code == 403
    rs = response.json()
    assert rs["error_code"] == "protected_role_modification"


def test_cannot_manage_permissions_of_protected_role(
    admin_authenticated: TestClient,
) -> None:
    response = admin_authenticated.post(
        "/v1/roles/1/permissions",
        json={"permission_ids": [1]},
    )
    assert response.status_code == 403
    rs = response.json()
    assert rs["error_code"] == "protected_role_modification"


def test_cannot_patch_a_role_while_unauthorized(
    standard_authenticated: TestClient,
) -> None:
    response = standard_authenticated.patch(
        "/v1/roles/1",
        json={"name": "Administrator"},
    )
    assert response.status_code == 403
    rs = response.json()
    assert rs["msg"] == "You are not authorized to perform this action"


def test_cannot_get_roles_while_unauthorized(
    no_roles_authenticated: TestClient,
) -> None:
    response = no_roles_authenticated.get("/v1/roles")
    assert response.status_code == 403
    rs = response.json()
    assert rs["msg"] == "You are not authorized to perform this action"


def test_cannot_retrieve_a_role_while_unauthorized(
    no_roles_authenticated: TestClient,
) -> None:
    response = no_roles_authenticated.get("/v1/roles/1")
    assert response.status_code == 403
    rs = response.json()
    assert rs["msg"] == "You are not authorized to perform this action"


def test_cannot_delete_a_role_while_unauthorized(
    standard_authenticated: TestClient,
) -> None:
    response = standard_authenticated.delete("/v1/roles/1")
    assert response.status_code == 403
    rs = response.json()
    assert rs["msg"] == "You are not authorized to perform this action"


def test_cannot_manage_a_role_while_unauthorized(
    standard_authenticated: TestClient,
) -> None:
    response = standard_authenticated.post(
        "/v1/roles/1/permissions",
        json={
            "permission_ids": [1],
        },
    )
    assert response.status_code == 403
    rs = response.json()
    assert rs["msg"] == "You are not authorized to perform this action"


async def test_deleted_permission_excluded_from_role_permissions(
    admin_authenticated: TestClient,
) -> None:
    # Role 2 "Member" starts with read:user among its permissions
    response = admin_authenticated.get("/v1/roles/2")
    assert response.status_code == 200
    perm_names = {p["name"] for p in response.json()["permissions"]}
    assert Permission.READ_USER.value in perm_names

    # Soft-delete read:user directly via DB (no API endpoint exists for this)
    async with TestSessionLocal() as session:
        result = await session.execute(
            select(PermissionModel).where(
                PermissionModel.name == Permission.READ_USER.value,
            ),
        )
        permission = result.scalar_one()
        permission.deleted_at = datetime.now(UTC)
        await session.commit()

    # The soft-deleted permission must not appear in the role's permissions
    response = admin_authenticated.get("/v1/roles/2")
    assert response.status_code == 200
    perm_names = {p["name"] for p in response.json()["permissions"]}
    assert Permission.READ_USER.value not in perm_names
