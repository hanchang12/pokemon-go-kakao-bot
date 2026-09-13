from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import Outbox


def enqueue_message(db: Session, room: str, message: str) -> None:
    db.add(Outbox(room=room, message=message))
    db.flush()


def pop_outbox(db: Session) -> list[Outbox]:
    """대기 중인 1회성 메시지를 전부 꺼내고 큐에서 지운다."""
    items = list(db.scalars(select(Outbox)).all())
    if items:
        db.execute(delete(Outbox).where(Outbox.id.in_([item.id for item in items])))
        db.flush()
    return items
