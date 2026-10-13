"""Authentication flows: login, lockout, refresh rotation, invitations, passwords, TOTP."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pyotp
from conftest import PASSWORD, ROLE_USERS, add_user
from sqlalchemy import text

from app.db.models import RefreshToken, User, UserToken

API = "/api/v1"
STRONG = "Violet-Harbor-Quartz-4821"


def refresh_cookie(response) -> str:
    """Raw refresh token from a Set-Cookie header."""
    for header in response.headers.get_list("set-cookie"):
        if header.startswith("refresh_token="):
            return header.split(";", 1)[0].split("=", 1)[1]
    raise AssertionError("no refresh cookie")


def login(client, email, password=PASSWORD, **extra):
    return client.post(f"{API}/auth/login", json={"email": email, "password": password, **extra})


def audit_actions(session_factory) -> list[str]:
    with session_factory() as session:
        return [r[0] for r in session.execute(text("SELECT action FROM audit_log ORDER BY id"))]


# ---- login --------------------------------------------------------------------


def test_login_returns_token_user_and_a_hardened_refresh_cookie(client, users):
    response = login(client, ROLE_USERS["attorney"])
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer" and body["expires_in"] == 900
    assert body["user"]["role"] == "attorney" and "password" not in str(body)
    cookie = next(
        h for h in response.headers.get_list("set-cookie") if h.startswith("refresh_token=")
    )
    lowered = cookie.lower()
    assert "httponly" in lowered and "secure" in lowered and "samesite=strict" in lowered
    assert "path=/api/v1/auth" in lowered and "max-age=604800" in lowered
    assert body["access_token"] not in cookie


def test_login_failures_are_indistinguishable(client, users):
    wrong = login(client, ROLE_USERS["attorney"], "Wrong-Password-12345")
    unknown = login(client, "nobody@example.com", "Wrong-Password-12345")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json() == {"detail": "Invalid credentials"}
    assert "set-cookie" not in wrong.headers


def test_email_is_case_insensitive(client, users):
    assert login(client, ROLE_USERS["viewer"].upper()).status_code == 200


def test_bearer_token_authenticates_and_garbage_does_not(client, auth):
    assert (
        client.get(f"{API}/auth/me", headers=auth["analyst"]).json()["email"]
        == ROLE_USERS["analyst"]
    )
    missing = client.get(f"{API}/auth/me")
    assert missing.status_code == 401 and missing.headers["www-authenticate"] == "Bearer"
    bad = client.get(f"{API}/auth/me", headers={"Authorization": "Bearer abc.def.ghi"})
    assert bad.status_code == 401


def test_tampered_forged_and_foreign_tokens_are_rejected(client, auth, users):
    import jwt

    token = auth["viewer"]["Authorization"].split()[1]
    header, payload, signature = token.split(".")
    forged_payload = jwt.encode({"sub": str(users["admin"].id)}, "x" * 40, algorithm="HS256").split(
        "."
    )[1]
    for candidate in (
        f"{header}.{forged_payload}.{signature}",
        jwt.encode({"sub": str(users["admin"].id), "typ": "access"}, key=None, algorithm="none"),
        token[:-3] + ("AAA" if not token.endswith("AAA") else "BBB"),
    ):
        response = client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {candidate}"})
        assert response.status_code == 401


def test_deactivated_user_loses_access_immediately(client, auth, users):
    assert (
        client.patch(
            f"{API}/users/{users['analyst'].id}", json={"is_active": False}, headers=auth["admin"]
        ).status_code
        == 200
    )
    assert client.get(f"{API}/auth/me", headers=auth["analyst"]).status_code == 401
    assert login(client, ROLE_USERS["analyst"]).status_code == 401


def test_role_change_takes_effect_on_the_next_request(client, auth, users):
    assert (
        client.post(f"{API}/cases", json={"title": "t"}, headers=auth["analyst"]).status_code == 201
    )
    response = client.patch(
        f"{API}/users/{users['analyst'].id}", json={"role": "viewer"}, headers=auth["admin"]
    )
    assert response.status_code == 200 and response.json()["role"] == "viewer"
    # same access token, new role from the database
    assert (
        client.post(f"{API}/cases", json={"title": "t"}, headers=auth["analyst"]).status_code == 403
    )


# ---- lockout ------------------------------------------------------------------


def test_lockout_after_five_failures_with_growing_backoff(client, users, session_factory):
    email = ROLE_USERS["analyst"]
    for _ in range(5):
        assert login(client, email, "Wrong-Password-12345").status_code == 401
    # locked: even the right password is refused, with the same generic answer
    locked = login(client, email)
    assert locked.status_code == 401 and locked.json() == {"detail": "Invalid credentials"}

    with session_factory() as session:
        user = session.get(User, users["analyst"].id)
        assert user.failed_login_count == 5
        first_lock = user.locked_until - datetime.now(UTC)
        assert timedelta(seconds=30) < first_lock <= timedelta(minutes=1)
        user.locked_until = datetime.now(UTC) - timedelta(seconds=1)  # time passes
        session.commit()

    assert login(client, email, "Wrong-Password-12345").status_code == 401  # 6th failure
    with session_factory() as session:
        second_lock = session.get(User, users["analyst"].id).locked_until - datetime.now(UTC)
        assert timedelta(seconds=90) < second_lock <= timedelta(minutes=2)
        session.get(User, users["analyst"].id).locked_until = datetime.now(UTC) - timedelta(
            seconds=1
        )
        session.commit()

    assert login(client, email).status_code == 200
    with session_factory() as session:
        user = session.get(User, users["analyst"].id)
        assert user.failed_login_count == 0 and user.locked_until is None
    actions = audit_actions(session_factory)
    assert actions.count("login_failed") >= 6 and "login_success" in actions


# ---- refresh rotation ---------------------------------------------------------


def test_refresh_rotates_the_token_and_issues_a_new_access_token(client, users):
    first = login(client, ROLE_USERS["attorney"])
    old_cookie = refresh_cookie(first)
    rotated = client.post(f"{API}/auth/refresh")
    assert rotated.status_code == 200
    new_cookie = refresh_cookie(rotated)
    assert new_cookie != old_cookie
    assert rotated.json()["access_token"] != first.json()["access_token"]
    assert (
        client.get(
            f"{API}/auth/me", headers={"Authorization": f"Bearer {rotated.json()['access_token']}"}
        ).status_code
        == 200
    )


def test_reusing_a_rotated_refresh_token_revokes_the_whole_family(client, users, session_factory):
    old_cookie = refresh_cookie(login(client, ROLE_USERS["attorney"]))
    new_cookie = refresh_cookie(client.post(f"{API}/auth/refresh"))

    client.cookies.clear()
    replay = client.post(f"{API}/auth/refresh", headers={"Cookie": f"refresh_token={old_cookie}"})
    assert replay.status_code == 401
    assert "max-age=0" in replay.headers["set-cookie"].lower()  # cookie cleared

    # the legitimate newest token of the same family is now dead too
    client.cookies.clear()
    follow_up = client.post(
        f"{API}/auth/refresh", headers={"Cookie": f"refresh_token={new_cookie}"}
    )
    assert follow_up.status_code == 401
    with session_factory() as session:
        assert session.query(RefreshToken).filter(RefreshToken.revoked_at.is_(None)).count() == 0
    assert "refresh_reuse_detected" in audit_actions(session_factory)


def test_refresh_requires_a_valid_unexpired_cookie_and_allowed_origin(
    client, users, session_factory
):
    assert client.post(f"{API}/auth/refresh").status_code == 401  # no cookie
    cookie = refresh_cookie(login(client, ROLE_USERS["viewer"]))

    bad_origin = client.post(f"{API}/auth/refresh", headers={"Origin": "https://evil.example"})
    assert bad_origin.status_code == 403
    good_origin = client.post(f"{API}/auth/refresh", headers={"Origin": "https://app.example.test"})
    assert good_origin.status_code == 200
    cookie = refresh_cookie(good_origin)

    with session_factory() as session:
        row = session.query(RefreshToken).filter(RefreshToken.revoked_at.is_(None)).one()
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()
    client.cookies.clear()
    expired = client.post(f"{API}/auth/refresh", headers={"Cookie": f"refresh_token={cookie}"})
    assert expired.status_code == 401


def test_only_hashes_of_refresh_tokens_are_stored(client, users, session_factory):
    cookie = refresh_cookie(login(client, ROLE_USERS["viewer"]))
    with session_factory() as session:
        stored = [row[0] for row in session.execute(text("SELECT token_hash FROM refresh_tokens"))]
    assert stored and cookie not in stored and all(len(h) == 64 for h in stored)


def test_logout_revokes_the_family_and_clears_the_cookie(client, users):
    cookie = refresh_cookie(login(client, ROLE_USERS["admin"]))
    out = client.post(f"{API}/auth/logout")
    assert out.status_code == 204 and "max-age=0" in out.headers["set-cookie"].lower()
    client.cookies.clear()
    assert (
        client.post(
            f"{API}/auth/refresh", headers={"Cookie": f"refresh_token={cookie}"}
        ).status_code
        == 401
    )
    assert client.post(f"{API}/auth/logout").status_code == 204  # idempotent without a cookie


# ---- invitations --------------------------------------------------------------


def invite(client, auth, email="new.person@example.com", role="analyst"):
    return client.post(
        f"{API}/users/invite",
        json={"email": email, "full_name": "New Person", "role": role},
        headers=auth["admin"],
    )


def test_invite_accept_login_flow_and_single_use(client, auth, session_factory):
    response = invite(client, auth)
    assert response.status_code == 201
    token = response.json()["invite_token"]
    assert response.json()["user"]["role"] == "analyst"

    # no password yet, cannot log in
    assert login(client, "new.person@example.com", STRONG).status_code == 401

    weak = client.post(
        f"{API}/auth/accept-invite", json={"token": token, "password": "Password1234!"}
    )
    assert weak.status_code == 422 and "common" in weak.json()["detail"]

    accepted = client.post(
        f"{API}/auth/accept-invite",
        json={"token": token, "password": STRONG, "full_name": "Nina Pérez"},
    )
    assert accepted.status_code == 204
    me = login(client, "new.person@example.com", STRONG)
    assert me.status_code == 200 and me.json()["user"]["full_name"] == "Nina Pérez"

    again = client.post(
        f"{API}/auth/accept-invite", json={"token": token, "password": STRONG + "x"}
    )
    assert again.status_code == 400
    with session_factory() as session:  # only the hash is stored
        hashes = [r[0] for r in session.execute(text("SELECT token_hash FROM user_tokens"))]
    assert token not in hashes


def test_expired_invitation_is_refused(client, auth, session_factory):
    token = invite(client, auth).json()["invite_token"]
    with session_factory() as session:
        row = session.query(UserToken).one()
        row.expires_at = datetime.now(UTC) - timedelta(hours=1)
        session.commit()
    response = client.post(f"{API}/auth/accept-invite", json={"token": token, "password": STRONG})
    assert response.status_code == 400


def test_invitations_are_admin_only_and_emails_unique(client, auth):
    assert invite(client, auth).status_code == 201
    assert invite(client, auth).status_code == 409
    for role in ("attorney", "analyst", "viewer"):
        denied = client.post(
            f"{API}/users/invite",
            json={"email": f"x.{role}@example.com", "full_name": "X", "role": role},
            headers=auth[role],
        )
        assert denied.status_code == 403
    bad_role = client.post(
        f"{API}/users/invite",
        json={"email": "r@example.com", "full_name": "R", "role": "superuser"},
        headers=auth["admin"],
    )
    assert bad_role.status_code == 422


def test_admin_cannot_demote_or_deactivate_themselves(client, auth, users):
    me = users["admin"].id
    assert (
        client.patch(
            f"{API}/users/{me}", json={"role": "viewer"}, headers=auth["admin"]
        ).status_code
        == 400
    )
    assert (
        client.patch(
            f"{API}/users/{me}", json={"is_active": False}, headers=auth["admin"]
        ).status_code
        == 400
    )


def test_admin_password_reset_voids_the_old_password_and_sessions(client, auth, users):
    victim = ROLE_USERS["viewer"]
    first = login(client, victim)
    old_cookie = refresh_cookie(first)
    reset = client.post(f"{API}/users/{users['viewer'].id}/reset-password", headers=auth["admin"])
    assert reset.status_code == 200
    assert login(client, victim).status_code == 401  # old password gone
    client.cookies.clear()
    assert (
        client.post(
            f"{API}/auth/refresh", headers={"Cookie": f"refresh_token={old_cookie}"}
        ).status_code
        == 401
    )

    done = client.post(
        f"{API}/auth/accept-invite", json={"token": reset.json()["reset_token"], "password": STRONG}
    )
    assert done.status_code == 204 and login(client, victim, STRONG).status_code == 200


# ---- passwords ----------------------------------------------------------------


def test_change_password_checks_current_policy_and_signs_out_other_sessions(client, users):
    email = ROLE_USERS["attorney"]
    first = login(client, email)
    cookie = refresh_cookie(first)
    headers = {"Authorization": f"Bearer {first.json()['access_token']}"}

    wrong = client.post(
        f"{API}/auth/change-password",
        headers=headers,
        json={"current_password": "nope-nope-nope-1", "new_password": STRONG},
    )
    assert wrong.status_code == 400
    weak = client.post(
        f"{API}/auth/change-password",
        headers=headers,
        json={"current_password": PASSWORD, "new_password": "short"},
    )
    assert weak.status_code == 422
    same_as_email = client.post(
        f"{API}/auth/change-password",
        headers=headers,
        json={"current_password": PASSWORD, "new_password": "attorney@example.com"},
    )
    assert same_as_email.status_code == 422

    ok = client.post(
        f"{API}/auth/change-password",
        headers=headers,
        json={"current_password": PASSWORD, "new_password": STRONG},
    )
    assert ok.status_code == 204
    client.cookies.clear()
    assert (
        client.post(
            f"{API}/auth/refresh", headers={"Cookie": f"refresh_token={cookie}"}
        ).status_code
        == 401
    )
    assert login(client, email, PASSWORD).status_code == 401
    assert login(client, email, STRONG).status_code == 200


# ---- totp ---------------------------------------------------------------------


def test_totp_setup_enable_login_and_disable(client, auth, users, session_factory, settings):
    email = ROLE_USERS["attorney"]
    headers = auth["attorney"]
    secret = client.post(f"{API}/auth/totp/setup", headers=headers).json()["secret"]

    with session_factory() as session:  # the secret is stored encrypted
        stored = session.get(User, users["attorney"].id).totp_secret
    assert stored and stored != secret and secret not in stored

    assert (
        client.post(f"{API}/auth/totp/enable", json={"code": "000000"}, headers=headers).status_code
        == 400
    )
    assert (
        client.post(
            f"{API}/auth/totp/enable", json={"code": pyotp.TOTP(secret).now()}, headers=headers
        ).status_code
        == 204
    )

    needs_code = login(client, email)
    assert needs_code.status_code == 401 and needs_code.headers["x-auth-error"] == "totp_required"
    wrong = login(client, email, totp_code="000000")
    assert wrong.status_code == 401 and wrong.headers["x-auth-error"] == "invalid_credentials"
    assert login(client, email, totp_code=pyotp.TOTP(secret).now()).status_code == 200

    assert (
        client.post(
            f"{API}/auth/totp/disable", json={"password": "wrong-password-123"}, headers=headers
        ).status_code
        == 400
    )
    assert (
        client.post(
            f"{API}/auth/totp/disable", json={"password": PASSWORD}, headers=headers
        ).status_code
        == 204
    )
    assert login(client, email).status_code == 200


# ---- misc ---------------------------------------------------------------------


def test_login_rate_limit_returns_429(client, users, settings, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_auth", "3/minute")
    codes = [
        login(client, ROLE_USERS["viewer"], "Wrong-Password-12345").status_code for _ in range(5)
    ]
    assert codes[:3] == [401, 401, 401] and codes[3:] == [429, 429]


def test_user_listing_never_exposes_credentials(client, auth):
    body = client.get(f"{API}/users", headers=auth["admin"]).text
    for secret_field in ("password", "totp_secret", "token_hash"):
        assert secret_field not in body


def test_users_without_a_password_hash_cannot_log_in(client, session_factory, settings, clean_db):
    add_user(session_factory, settings, "pending@example.com", "analyst", password=None)
    assert login(client, "pending@example.com", "anything-at-all-123").status_code == 401
