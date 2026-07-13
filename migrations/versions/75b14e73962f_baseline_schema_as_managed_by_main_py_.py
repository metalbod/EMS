"""baseline: schema as managed by main.py init_db()

Revision ID: 75b14e73962f
Revises: 
Create Date: 2026-07-13 16:16:19.195624

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '75b14e73962f'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Intentionally empty.

    Establishes revision 75b14e73962f as the baseline marker for the schema
    that already existed before Alembic was introduced — the full current
    schema is still defined and applied by main.py's init_db()/
    _init_db_body(), which runs idempotently on every app boot (see db.py
    and main.py). This revision is stamped onto the database via
    `alembic stamp head`, NOT run via `alembic upgrade head` — no DDL
    executes here, since the schema this revision represents is already
    live.

    Reusing init_db()'s logic directly from here was considered and
    rejected: importing main.py unconditionally re-triggers its own
    module-level init_db() call (and boots the whole FastAPI app just to
    reach one function) — an unwanted side effect just to read schema DDL.

    Going forward, NEW schema changes should be written as real Alembic
    migrations (op.execute(...) with the actual SQL, following this
    project's raw-SQL style — see migrations/README) chained after this
    baseline, rather than added to init_db(). init_db() remains as-is for
    now (untouched, still the source of truth for anything predating this
    revision) until enough new migrations exist to fully retire it.
    """
    pass


def downgrade() -> None:
    """No baseline to downgrade to — this is revision 1."""
    raise NotImplementedError("Cannot downgrade past the baseline revision.")
