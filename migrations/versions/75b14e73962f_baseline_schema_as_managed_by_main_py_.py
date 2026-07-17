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
    that already existed before Alembic was introduced. All schema DDL has
    been moved to Alembic migrations (see 20260717_0001_full_schema_ddl.py).

    This baseline revision is stamped onto existing databases via
    `alembic stamp head` to establish a starting point for future migrations.
    It does not execute any DDL itself — the actual schema is defined in the
    20260717_0001_full_schema_ddl migration that follows.

    Going forward, NEW schema changes should be written as real Alembic
    migrations (op.execute(...) with the actual SQL, following this
    project's raw-SQL style — see migrations/README) chained after this
    baseline.
    """
    pass


def downgrade() -> None:
    """No baseline to downgrade to — this is revision 1."""
    raise NotImplementedError("Cannot downgrade past the baseline revision.")
