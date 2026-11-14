"""Demo organization with an admin, an expert, two learners and the three solar modules (published).

Run: python -m app.seed.demo   (also runs on startup when SKILLOS_SEED_DEMO_DATA=true)
Demo password for all accounts: skillos-demo-2026
"""

import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models import Organization, Role, Skill, User
from app.skillgraph import service

SKILLS_DIR = Path(__file__).parent / "skills"
DEMO_PASSWORD = "skillos-demo-2026"
USERS = [
    ("admin@demo.skillos.dev", "Amina Admin", Role.ADMIN),
    ("expert@demo.skillos.dev", "Evans Expert (solar technician)", Role.EXPERT),
    ("learner@demo.skillos.dev", "John Learner", Role.LEARNER),
    ("learner2@demo.skillos.dev", "Grace Learner", Role.LEARNER),
]


def load_skill_files() -> list[dict]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(SKILLS_DIR.glob("*.json"))]


def seed(db: Session) -> Organization:
    org = db.scalar(select(Organization).where(Organization.slug == "demo-tvet"))
    if org is None:
        org = Organization(name="Demo TVET Institute", slug="demo-tvet")
        db.add(org)
        db.flush()
    users = {}
    for email, name, role in USERS:
        u = db.scalar(select(User).where(User.email == email))
        if u is None:
            u = User(org_id=org.id, email=email, full_name=name, password_hash=hash_password(DEMO_PASSWORD), role=role)
            db.add(u)
            db.flush()
        users[role] = u
    expert = users[Role.EXPERT]
    for graph in load_skill_files():
        if db.scalar(select(Skill).where(Skill.org_id == org.id, Skill.slug == graph["skill_id"])):
            continue
        skill = service.create_skill(db, expert, graph, "Seeded MVP module")
        v = skill.versions[-1]
        warnings = [f"{w['code']}:{w['step_id']}" for w in v.validation_report["warnings"]]
        service.publish(db, expert, skill, v, warnings, "Seeded demo module. Requires review by a qualified solar technician before real use.")
    db.commit()
    return org


if __name__ == "__main__":
    from app.core.db import Base, SessionLocal, engine

    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed(db)
    print("Seeded demo org. Accounts:", ", ".join(e for e, _, _ in USERS), "| password:", DEMO_PASSWORD)
