"""
CRM yesterday-memory helpers — operate on ctr_db.yesterday_memory.

Each /crm/process run:
  1. load_yesterday_memory(db)   → pass to process_rows() to avoid duplicate CTRs
  2. save_today_snapshot(db, …)  → replace with today's data for tomorrow's run
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List

from sqlalchemy.orm import Session

from models.crm import YesterdayMemory


def load_yesterday_memory(session: Session) -> Dict[str, List[dict]]:
    """
    Return {line_item_id: [{"clicks": int, "ctr": "0.42%"}, ...]}
    """
    rows = session.query(YesterdayMemory).all()
    memory: Dict[str, List[dict]] = {}
    for r in rows:
        memory.setdefault(r.line_item_id, []).append(
            {"clicks": r.clicks, "ctr": r.ctr}
        )
    return memory


def save_today_snapshot(
    session: Session,
    snapshot: Dict[str, List[dict]],
) -> None:
    """
    Atomically replace yesterday_memory with today's snapshot.
    """
    session.query(YesterdayMemory).delete(synchronize_session=False)
    today = datetime.now(timezone.utc).strftime("%d/%m/%Y")
    for line_id, entries in snapshot.items():
        for entry in entries:
            session.add(YesterdayMemory(
                line_item_id=line_id,
                clicks=int(entry.get("clicks", 0)),
                ctr=str(entry.get("ctr", "0.00%")),
                run_date=today,
            ))
    session.commit()
