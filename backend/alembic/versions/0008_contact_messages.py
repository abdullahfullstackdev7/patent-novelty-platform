"""contact messages from the public website

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-14 09:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "contact_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("organization", sa.String(length=200), nullable=True),
        sa.Column("topic", sa.String(length=16), server_default="demo", nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("topic IN ('demo', 'sales', 'support', 'other')", name=op.f("ck_contact_messages_topic_valid")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contact_messages")),
    )


def downgrade() -> None:
    op.drop_table("contact_messages")
