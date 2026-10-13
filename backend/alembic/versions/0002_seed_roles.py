"""seed the four RBAC roles

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLES = [
    ("admin", "Manages users, billing and analytics, and can see all cases"),
    ("attorney", "Owns and reviews cases, approves reports"),
    ("analyst", "Creates cases and runs searches, cannot approve reports"),
    ("viewer", "Read-only access to shared cases"),
]


def upgrade() -> None:
    for name, description in ROLES:
        op.execute(
            "INSERT INTO roles (name, description) VALUES "
            f"('{name}', '{description}') ON CONFLICT (name) DO NOTHING"
        )


def downgrade() -> None:
    op.execute("DELETE FROM roles WHERE name IN ('admin', 'attorney', 'analyst', 'viewer')")
