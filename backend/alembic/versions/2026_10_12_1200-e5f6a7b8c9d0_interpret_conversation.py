"""interpret product: conversation table and turn limits

Revision ID: e5f6a7b8c9d0
Revises: c2d3e4f5a6b7
Create Date: 2026-10-12 12:00:00.000000

"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa

from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: str | None = "c2d3e4f5a6b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_billing_plan_setting_table = sa.table(
    "billing_plan_setting",
    sa.column("plan_id", sa.Integer),
    sa.column("key", sa.String),
    sa.column("value", sa.Integer),
    sa.column("created_at", sa.DateTime),
    sa.column("updated_at", sa.DateTime),
    sa.column("deleted_at", sa.DateTime),
)

# Translated turns per billing period for each seeded plan (plan ids from the
# billing migration). Seeded only when billing is installed; without it, turns
# are unlimited.
_TURN_LIMITS = {1: 50, 2: 1000, 3: 5000, 4: None}


def _billing_installed() -> bool:
    return sa.inspect(op.get_bind()).has_table("billing_plan_setting")


def upgrade() -> None:
    op.create_table(
        "interpret_conversation",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("staff_language", sa.String(length=8), nullable=False),
        sa.Column("citizen_language", sa.String(length=8), nullable=False),
        sa.Column("turn_count", sa.Integer(), nullable=False),
        sa.Column("audio_ms", sa.Integer(), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_interpret_conversation_organization_id",
        "interpret_conversation",
        ["organization_id"],
    )
    op.create_index(
        "ix_interpret_conversation_user_id",
        "interpret_conversation",
        ["user_id"],
    )

    if not _billing_installed():
        return
    now = datetime.now(UTC)
    op.bulk_insert(
        _billing_plan_setting_table,
        [
            {
                "plan_id": plan_id,
                "key": "interpret_turns",
                "value": value,
                "created_at": now,
                "updated_at": now,
                "deleted_at": None,
            }
            for plan_id, value in _TURN_LIMITS.items()
        ],
    )


def downgrade() -> None:
    if _billing_installed():
        op.execute(
            sa.delete(_billing_plan_setting_table).where(
                _billing_plan_setting_table.c.key == "interpret_turns"
            )
        )
    op.drop_index(
        "ix_interpret_conversation_user_id", table_name="interpret_conversation"
    )
    op.drop_index(
        "ix_interpret_conversation_organization_id",
        table_name="interpret_conversation",
    )
    op.drop_table("interpret_conversation")
