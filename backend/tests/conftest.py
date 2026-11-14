import os
import sys
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="skillos-test-"))
os.environ.update({
    "SKILLOS_DATABASE_URL": f"sqlite:///{(_tmp / 'test.db').as_posix()}",
    "SKILLOS_STORAGE_DIR": str(_tmp / "storage"),
    "SKILLOS_SEED_DEMO_DATA": "false",
    "SKILLOS_JWT_SECRET": "test-secret-key-that-is-long-enough-for-hs256",
})
for k in ("OPENAI_API_KEY", "OPENAI_MODEL", "SKILLOS_OPENAI_API_KEY", "SKILLOS_OPENAI_MODEL", "SKILLOS_REDIS_URL"):
    os.environ.pop(k, None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import copy  # noqa: E402
import json  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from argon2 import PasswordHasher  # noqa: E402

from app.core import ratelimit, security  # noqa: E402

security._hasher = PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1)  # fast hashing for tests only
from app.core.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.seed.demo import DEMO_PASSWORD, seed  # noqa: E402

SKILLS = Path(__file__).resolve().parents[1] / "app" / "seed" / "skills"


def load(name: str) -> dict:
    return copy.deepcopy(json.loads((SKILLS / f"{name}.json").read_text(encoding="utf-8")))


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    ratelimit.reset()
    yield


@pytest.fixture
def db():
    with SessionLocal() as s:
        yield s


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def demo(db):
    return seed(db)


def login(client, email: str) -> dict:
    r = client.post("/api/v1/auth/login", json={"email": email, "password": DEMO_PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def learner(client, demo):
    return login(client, "learner@demo.skillos.dev")


@pytest.fixture
def expert(client, demo):
    return login(client, "expert@demo.skillos.dev")


@pytest.fixture
def admin(client, demo):
    return login(client, "admin@demo.skillos.dev")
