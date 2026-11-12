from sqlalchemy.orm import Session

from app.models import AuditLog, User


def audit(db: Session, actor: User | None, action: str, target_type: str | None = None,
          target_id: str | None = None, **details) -> None:
    db.add(AuditLog(org_id=actor.org_id if actor else None, actor_id=actor.id if actor else None, action=action,
                    target_type=target_type, target_id=target_id, details=details))
