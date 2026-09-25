"""SQLAlchemy ORM models.

Importing this package registers every model on `Base.metadata`, which is what
Alembic autogenerate compares against. `app/migrations/env.py` imports it for
exactly that reason.
"""

from app.models.comparison import Comparison
from app.models.event import Event, EventType
from app.models.project import Project
from app.models.run import Run, RunStatus

__all__ = ["Comparison", "Event", "EventType", "Project", "Run", "RunStatus"]
