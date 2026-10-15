"""Create the four demo accounts (admin, attorney, analyst, viewer). Safe to run again.

    uv run --project backend python scripts/seed_demo_users.py
    uv run --project backend python scripts/seed_demo_users.py --password-prefix "My-Own-Phrase"

The passwords are public in the README and exist only for demonstrations. Change them, or remove
the accounts, before any real deployment. Existing accounts keep their password unless --reset is given.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy import select  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db.models import Role, User  # noqa: E402
from app.db.session import make_engine, make_session_factory  # noqa: E402
from app.security import passwords  # noqa: E402

ACCOUNTS = (
    ("admin", "Ada Admin"),
    ("attorney", "Alex Attorney"),
    ("analyst", "Ana Analyst"),
    ("viewer", "Vic Viewer"),
)
DOMAIN = "priorart-demo.example.com"


WORDS = {"admin": "Quartz", "attorney": "Lantern", "analyst": "Meadow", "viewer": "Cobalt"}


def demo_password(role: str, prefix: str) -> str:
    # The policy rejects passwords that contain the role-based email name, so each role gets its own word.
    return f"{prefix}-{WORDS[role]}-2026"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--password-prefix", default="Atlas-Demo-Harbor")
    parser.add_argument("--reset", action="store_true", help="set the password again for existing accounts")
    args = parser.parse_args()

    settings = get_settings()
    sessions = make_session_factory(make_engine(settings.database_url))
    with sessions() as session:
        roles = {r.name: r.id for r in session.scalars(select(Role))}
        for role, name in ACCOUNTS:
            email = f"{role}@{DOMAIN}"
            password = demo_password(role, args.password_prefix)
            try:
                passwords.validate_password(password, settings, email=email, full_name=name)
            except passwords.PasswordPolicyError as error:
                sys.exit(f"The password for {role} is not accepted by the policy: {error}")
            user = session.scalar(select(User).where(User.email == email))
            if user is None:
                session.add(User(email=email, full_name=name, role_id=roles[role], is_active=True,
                                 password_hash=passwords.hash_password(password, settings)))  # fmt: skip
                action = "created"
            elif args.reset:
                user.password_hash = passwords.hash_password(password, settings)
                user.is_active = True
                action = "password reset"
            else:
                action = "kept"
            print(f"{action:<15} {email:<34} {password if action != 'kept' else '(unchanged)'}")
        session.commit()


if __name__ == "__main__":
    main()
