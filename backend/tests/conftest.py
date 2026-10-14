"""Shared fixtures: a throwaway migrated database and offline fake models."""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from datetime import date
from pathlib import Path

import psycopg
import pytest
from alembic.config import Config
from sqlalchemy import Engine, create_engine, insert, text
from sqlalchemy.orm import sessionmaker

from alembic import command

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(0, str(ROOT / "scripts"))

# Application settings for tests. Set before app.config is first used.
from cryptography.fernet import Fernet  # noqa: E402

TEST_ENV = {
    "APP_ENV": "test",
    "JWT_SECRET": "test-jwt-secret-with-more-than-thirty-two-characters",
    "FERNET_KEY": Fernet.generate_key().decode(),
    "COOKIE_SECURE": "true",
    "CORS_ORIGINS": "https://app.example.test",
    "RATE_LIMIT_DEFAULT": "100000/minute",
    "RATE_LIMIT_AUTH": "100000/minute",
    "RATE_LIMIT_LLM": "100000/minute",
    "RATE_LIMIT_CONTACT": "5/hour",
    "ARGON2_TIME_COST": "1",
    "ARGON2_MEMORY_KIB": "8192",
    "ARGON2_PARALLELISM": "1",
}
os.environ.update(TEST_ENV)

from support import FakeEmbedder  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db.models import Patent, PatentChunk, PatentClaim  # noqa: E402

ADMIN_URL = os.environ.get(
    "TEST_ADMIN_URL", "postgresql://priorart:priorart@localhost:54329/postgres"
)
TEST_DB = "priorart_test"
TEST_URL = ADMIN_URL.rsplit("/", 1)[0].replace("postgresql://", "postgresql+psycopg://") + (
    f"/{TEST_DB}"
)


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    with psycopg.connect(ADMIN_URL, autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
        conn.execute(f"CREATE DATABASE {TEST_DB}")
    os.environ["DATABASE_URL"] = TEST_URL
    get_settings.cache_clear()
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    command.upgrade(config, "head")
    yield TEST_URL
    with psycopg.connect(ADMIN_URL, autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")


@pytest.fixture(scope="session")
def engine(database_url: str) -> Iterator[Engine]:
    eng = create_engine(database_url)
    yield eng
    eng.dispose()


@pytest.fixture
def session_factory(engine: Engine) -> sessionmaker:
    return sessionmaker(engine, expire_on_commit=False)


# (id, source, title, abstract, publication date, cpc codes, claims)
CORPUS = [
    (
        "US100A1",
        "HUPD_APP",
        "Battery thermal runaway detection",
        "A battery management unit detects thermal runaway by measuring cell impedance and "
        "sensing electrolyte gas inside the battery pack housing.",
        date(2016, 5, 1),
        ["H01M10/48", "B60L3/00"],
        [
            "A battery management unit comprising an impedance measurement circuit for lithium "
            "ion cells and a gas sensor configured to detect electrolyte vapour in a pack housing.",
            "The battery management unit of claim 1, wherein a contactor isolates the pack.",
        ],
    ),
    (
        "US101A1",
        "HUPD_APP",
        "Federated training of medical image networks",
        "Hospitals train neural networks on local medical images and share encrypted weight "
        "updates with a server that aggregates a global model.",
        date(2016, 8, 9),
        ["G06N3/08", "G16H30/40"],
        [
            "A method comprising training a neural network at a hospital on stored medical images, "
            "encrypting weight updates, and aggregating the updates at a server into a global model.",
            "The method of claim 1, wherein the updates are weighted by a data quality score.",
        ],
    ),
    (
        "US102A1",
        "HUPD_APP",
        "User equipment positioning with interference coordination",
        "A base station transmits positioning signals while neighbouring base stations mitigate "
        "interference so that user equipment can determine its position.",
        date(2016, 3, 3),
        ["H04W64/00"],
        [
            "A method of positioning user equipment using positioning reference signals from base stations."
        ],
    ),
    (
        "US103A1",
        "HUPD_APP",
        "Electric vehicle charging schedule with grid price",
        "A scheduler charges and discharges an electric vehicle battery according to electricity "
        "price forecasts and grid regulation signals while keeping the departure charge level.",
        date(2017, 1, 20),
        ["B60L53/60", "H02J3/32"],
        [
            "A scheduler receiving electricity price forecasts and a departure state of charge and "
            "scheduling charging and discharging of a vehicle battery.",
        ],
    ),
    (
        "US104A1",
        "HUPD_APP",
        "Hydrolase enzyme for polymer degradation",
        "An engineered hydrolase enzyme degrades polyethylene terephthalate plastic into monomers.",
        date(2016, 11, 2),
        ["C12N9/18"],
        [
            "An engineered hydrolase enzyme with stabilising substitutions that hydrolyses polyethylene terephthalate."
        ],
    ),
    (
        "US105A1",
        "HUPD_APP",
        "Retrieval of diagnosis codes for clinical notes",
        "Sentences of a clinical note are embedded and similar code descriptions are retrieved "
        "from an index to propose diagnosis codes.",
        date(2017, 2, 14),
        ["G16H10/60", "G06F16/33"],
        [
            "A method comprising embedding sentences of a clinical note and retrieving diagnosis codes from an index."
        ],
    ),
    (
        "US106A1",
        "HUPD_APP",
        "Later battery gas sensing patent",
        "A battery pack with a gas sensor and impedance monitoring for thermal runaway.",
        date(2019, 1, 10),
        ["H01M10/48"],
        ["A battery pack comprising a gas sensor and an impedance monitor for thermal runaway."],
    ),
    (
        "US9000001",
        "PV_GRANT",
        "Distributed learning of image classifiers",
        "Distributed training of neural networks across sites with aggregation of model weights.",
        date(2015, 6, 2),
        ["G06N3/04"],
        ["A system for distributed training of a neural network with weight aggregation."],
    ),
]
PRIORITY = date(2018, 1, 1)


@pytest.fixture
def seeded(engine: Engine, session_factory: sessionmaker) -> sessionmaker:
    """Truncate the corpus tables and load CORPUS with fake embeddings."""
    embedder = FakeEmbedder()
    with session_factory() as session:
        session.execute(text("TRUNCATE patent_chunks, patent_claims, patents"))
        for pid, source, title, abstract, published, cpcs, claims in CORPUS:
            session.execute(
                insert(Patent).values(
                    id=pid,
                    source=source,
                    title=title,
                    abstract=abstract,
                    publication_date=published,
                    grant_date=published if source == "PV_GRANT" else None,
                    cpc_codes=cpcs,
                    cpc_subclasses=sorted({c[:4] for c in cpcs}),
                    main_subclass=cpcs[0][:4],
                    n_claims=len(claims),
                    n_independent=1,
                    url=f"https://patents.google.com/patent/{pid}",
                )
            )
            texts = [("abstract", 0, None, abstract)] + [
                ("claim", i, i, claim) for i, claim in enumerate(claims, start=1)
            ]
            for index, claim in enumerate(claims, start=1):
                session.execute(
                    insert(PatentClaim).values(
                        patent_id=pid,
                        number=index,
                        text=claim,
                        is_independent=index == 1,
                        parent=None if index == 1 else 1,
                    )
                )
            vectors = embedder.encode_documents([t[3] for t in texts])
            for (kind, seq, claim_number, value), vector in zip(texts, vectors, strict=True):
                session.execute(
                    insert(PatentChunk).values(
                        id=f"{pid}:{kind}:{seq}",
                        patent_id=pid,
                        type=kind,
                        publication_date=published,
                        source=source,
                        claim_number=claim_number,
                        seq=seq,
                        text=value,
                        char_start=0,
                        char_end=len(value),
                        embedding=vector,
                    )
                )
        session.commit()
    return session_factory


# ---- API fixtures -------------------------------------------------------------

from fastapi.testclient import TestClient  # noqa: E402

from app.db.models import Role, User  # noqa: E402
from app.main import create_app  # noqa: E402
from app.security import passwords  # noqa: E402
from app.security.http import limiter  # noqa: E402

PASSWORD = "Tr1cky-Lantern-Vault-77"
ROLE_USERS = {
    "admin": "admin@example.com",
    "attorney": "attorney@example.com",
    "analyst": "analyst@example.com",
    "viewer": "viewer@example.com",
    "analyst2": "analyst2@example.com",
}


@pytest.fixture
def settings(database_url: str):
    get_settings.cache_clear()
    loaded = get_settings()
    # Tests never talk to a real LLM provider, whatever the developer has in the environment.
    loaded.groq_api_key = ""
    loaded.gemini_api_key = ""
    return loaded


@pytest.fixture(autouse=True)
def _reset_limiter():
    limiter.reset()
    yield


@pytest.fixture
def clean_db(engine: Engine) -> None:
    """Remove users and everything that hangs off them. Roles and the corpus stay."""
    with engine.begin() as conn:
        conn.execute(
            text("TRUNCATE users, clients, audit_log, llm_calls, jobs RESTART IDENTITY CASCADE")
        )


def add_user(
    session_factory,
    settings,
    email: str,
    role: str,
    password: str | None = PASSWORD,
    full_name: str | None = None,
    active: bool = True,
) -> User:
    with session_factory() as session:
        role_id = session.query(Role.id).filter(Role.name == role.rstrip("2")).scalar()
        user = User(
            email=email,
            full_name=full_name or email.split("@")[0].capitalize(),
            role_id=role_id,
            password_hash=passwords.hash_password(password, settings) if password else None,
            is_active=active,
        )
        session.add(user)
        session.commit()
        return user


@pytest.fixture
def users(clean_db, session_factory, settings) -> dict[str, User]:
    return {
        key: add_user(session_factory, settings, email, key, full_name=f"{key.title()} Person")
        for key, email in ROLE_USERS.items()
    }


@pytest.fixture
def app(clean_db, session_factory, settings):
    return create_app(settings, session_factory)


@pytest.fixture
def client(app) -> Iterator[TestClient]:
    # https base URL so the Secure refresh cookie is sent back by the test client
    with TestClient(app, base_url="https://testserver") as test_client:
        yield test_client


def login_headers(client: TestClient, email: str, password: str = PASSWORD) -> dict[str, str]:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def auth(client, users) -> dict[str, dict[str, str]]:
    """Bearer headers per role."""
    return {key: login_headers(client, email) for key, email in ROLE_USERS.items()}
