import asyncio
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

from alembic.command import downgrade, upgrade
from alembic.config import Config
from sqlalchemy import select

from src import sync_permissions
from src.bootstrap import ALL_PERMISSIONS, bootstrap
from src.foundation.core.database import ASYNC_SESSION_LOCAL
from src.foundation.core.hooks import HookEvent, emit
from src.foundation.core.logging import setup_logging
from src.foundation.core.security import hash_secret
from src.foundation.enums import OWNER_ROLE_NAME
from src.foundation.models.api_token import ApiToken  # noqa: F401
from src.foundation.models.organization import Organization
from src.foundation.models.permission import Permission as PermissionModel
from src.foundation.models.role import Role
from src.foundation.models.user import User
from src.foundation.models.user_organization import UserOrganization
from src.foundation.repositories.repository_manager import RepositoryManager

setup_logging("init_db")
log = logging.getLogger(__name__)


alembic_cfg = Config(str(Path.cwd()) + "/alembic.ini")

# Newly registered organizations are seeded with only the protected Owner role
# (DEFAULT_ROLES is empty). The dev/test fixtures below additionally create one
# generic, non-owner "Member" role per organization so the seed exercises
# limited-permission users; it is plain example data, not a default role.
_MEMBER_ROLE_NAME = "Member"
_MEMBER_ROLE_DESCRIPTION = "Work with the organization's data day to day."
_MEMBER_ROLE_PERMISSIONS: list = [
    "read:user",
    "read:role",
    "read:permission",
    "manage:api_token",
    "use:interpret",
]

INIT_AUTH_DATA: dict = {
    "organizations": [
        {"name": "Acme Corp", "owner": "admin@example.org"},
        {"name": "Globex Ltd", "owner": "admin2@example.org"},
    ],
    "roles": [
        # Org 1 - index 1
        {
            "name": OWNER_ROLE_NAME,
            "description": "Full access to all system features and settings.",
            "permissions": list(ALL_PERMISSIONS),
            "organization": 1,
            "is_protected": True,
        },
        # Org 1 - index 2
        {
            "name": _MEMBER_ROLE_NAME,
            "description": _MEMBER_ROLE_DESCRIPTION,
            "permissions": _MEMBER_ROLE_PERMISSIONS,
            "organization": 1,
        },
        # Org 2 - index 3
        {
            "name": OWNER_ROLE_NAME,
            "description": "Full access to all system features and settings.",
            "permissions": list(ALL_PERMISSIONS),
            "organization": 2,
            "is_protected": True,
        },
        # Org 2 - index 4
        {
            "name": _MEMBER_ROLE_NAME,
            "description": _MEMBER_ROLE_DESCRIPTION,
            "permissions": _MEMBER_ROLE_PERMISSIONS,
            "organization": 2,
        },
    ],
    "users": [
        {
            "name": "Alice Owner",
            "email": "admin@example.org",
            "password": "password",
            "organization": 1,
            "roles": [1],
        },
        {
            "name": "Bob Member",
            "email": "standard@example.org",
            "password": "password",
            "organization": 1,
            "roles": [2],
        },
        {
            "name": "Carol (No Roles)",
            "email": "no_roles@example.org",
            "password": "password",
            "organization": 1,
            "roles": [],
        },
        {
            "name": "Dave Owner",
            "email": "admin2@example.org",
            "password": "password",
            "organization": 2,
            "roles": [3],
        },
    ],
}


async def up() -> None:
    upgrade(alembic_cfg, "head")
    bootstrap()
    await sync_permissions.run()

    async with ASYNC_SESSION_LOCAL() as session:
        organizations = [
            Organization(name=organization["name"])
            for organization in INIT_AUTH_DATA["organizations"]
        ]
        session.add_all(organizations)

        result = await session.execute(select(PermissionModel))
        permissions = list(result.scalars().all())

        roles = [
            Role(
                name=role["name"],
                description=role["description"],
                is_protected=role.get("is_protected", False),
                organization=organizations[role["organization"] - 1],
                permissions=[
                    permission
                    for permission in permissions
                    if permission.name in role["permissions"]
                ],
            )
            for role in INIT_AUTH_DATA["roles"]
        ]
        session.add_all(roles)

        users = [
            User(
                name=user["name"],
                email=user["email"],
                password=hash_secret(user["password"]),
                roles=[
                    role for idx, role in enumerate(roles, 1) if idx in user["roles"]
                ],
            )
            for user in INIT_AUTH_DATA["users"]
        ]
        session.add_all(users)

        await session.flush()

        user_organizations = [
            UserOrganization(
                user_id=user.id,
                organization_id=organizations[user_data["organization"] - 1].id,
                last_active_at=datetime.now(UTC),
            )
            for user_data, user in zip(INIT_AUTH_DATA["users"], users, strict=False)
        ]
        session.add_all(user_organizations)

        # What the installed modules set up for a new organization (billing:
        # its account and free subscription), as registration would.
        owners = {user.email: user for user in users}
        for data, organization in zip(
            INIT_AUTH_DATA["organizations"],
            organizations,
            strict=True,
        ):
            await emit(
                HookEvent.ORGANIZATION_CREATED,
                repos=RepositoryManager(session),
                organization_id=organization.id,
                user_id=owners[data["owner"]].id,
            )

        await session.commit()


async def main(*, drop: bool = False) -> None:
    if not drop:
        log.info("Creating tables and initial data")
        await up()
        log.info("Created tables and initial data")
    else:
        log.info("Dropping tables")
        downgrade(alembic_cfg, "base")
        log.info("Dropped tables")


if __name__ == "__main__":
    asyncio.run(main(drop="drop" in sys.argv))
