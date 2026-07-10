"""
Postgres (Supabase) connection layer that mimics the sqlite3 API surface
used throughout main.py — conn.execute(sql_with_question_marks, params),
row["col"] / row[0] / dict(row) access, and last_insert_rowid() emulation —
so the application query code did not need to be rewritten call-by-call.
"""
import logging
import os
import re
import weakref
import psycopg2
import psycopg2.extensions
import psycopg2.pool

logger = logging.getLogger("ems.db")

IntegrityError = psycopg2.IntegrityError

# Currency columns are NUMERIC(12,2) (exact fixed-point) rather than REAL
# (float) so storage/aggregation don't drift — see main.py's migration notes.
# psycopg2 returns NUMERIC as Decimal by default, which would break every
# existing call site that mixes these values with float arithmetic
# (payroll_calc.py, main.py's payslip math) with a TypeError, since Python's
# decimal module deliberately refuses to mix with float. Registering this
# standard adapter makes NUMERIC come back as plain float instead, so all
# existing arithmetic and JSON serialization keep working unchanged — the
# fixed-point guarantee still applies to storage and SQL-side aggregation
# (e.g. SUM(net_pay)), which is where float drift actually caused problems.
_DEC2FLOAT = psycopg2.extensions.new_type(
    psycopg2.extensions.DECIMAL.values, "DEC2FLOAT",
    lambda value, curs: float(value) if value is not None else None,
)
psycopg2.extensions.register_type(_DEC2FLOAT)

DATABASE_URL = os.environ.get("DATABASE_URL")

_pool = None


def _get_pool():
    global _pool
    if _pool is None:
        if not DATABASE_URL:
            raise RuntimeError(
                "DATABASE_URL environment variable is not set. "
                "Set it to your Supabase Postgres connection string."
            )
        _pool = psycopg2.pool.SimpleConnectionPool(1, 10, dsn=DATABASE_URL, sslmode="require")
    return _pool


_INSERT_RE = re.compile(r"^\s*INSERT\s+INTO", re.IGNORECASE)
_RETURNING_RE = re.compile(r"RETURNING", re.IGNORECASE)


class Row:
    """Mimics sqlite3.Row: supports row[0], row['col'], dict(row), len(row)."""
    __slots__ = ("_values", "_col_index")

    def __init__(self, values, col_index):
        self._values = values
        self._col_index = col_index

    def __getitem__(self, key):
        if isinstance(key, str):
            return self._values[self._col_index[key]]
        return self._values[key]

    def keys(self):
        return self._col_index.keys()

    def __iter__(self):
        return iter(self._values)

    def __len__(self):
        return len(self._values)

    def __repr__(self):
        return repr(dict(zip(self._col_index.keys(), self._values)))


class CursorResult:
    def __init__(self, cur):
        self._cur = cur
        if cur.description:
            cols = [d[0] for d in cur.description]
            self._col_index = {name: i for i, name in enumerate(cols)}
        else:
            self._col_index = {}

    def _wrap(self, values):
        if values is None:
            return None
        return Row(values, self._col_index)

    def fetchone(self):
        return self._wrap(self._cur.fetchone())

    def fetchall(self):
        return [Row(v, self._col_index) for v in self._cur.fetchall()]

    @property
    def rowcount(self):
        return self._cur.rowcount


class Conn:
    def __init__(self, raw):
        self._raw = raw
        self._last_id = None
        self._closed = False
        # Safety net: if calling code forgets to call .close() (e.g. an
        # exception raised between get_db() and the endpoint's close() call),
        # this returns the connection to the pool once the Conn is garbage
        # collected instead of leaking it out of the (small, 10-connection)
        # pool permanently. GC timing isn't deterministic, so this is a
        # backstop, not a substitute for closing explicitly.
        self._finalizer = weakref.finalize(self, _return_to_pool, raw, leaked=True)

    def execute(self, sql, params=()):
        sql2 = sql.replace("?", "%s")
        if "last_insert_rowid()" in sql2:
            sql2 = sql2.replace("last_insert_rowid()", str(self._last_id))
        is_insert = bool(_INSERT_RE.match(sql2))
        has_returning = bool(_RETURNING_RE.search(sql2))
        if is_insert and not has_returning:
            sql2 = sql2.rstrip().rstrip(";") + " RETURNING id"
        cur = self._raw.cursor()
        cur.execute(sql2, params)
        if is_insert and not has_returning:
            row = cur.fetchone()
            if row is not None:
                self._last_id = row[0]
        return CursorResult(cur)

    def executescript(self, sql):
        cur = self._raw.cursor()
        cur.execute(sql)
        return CursorResult(cur)

    def commit(self):
        self._raw.commit()

    def rollback(self):
        self._raw.rollback()

    def close(self):
        if self._closed:
            return
        self._closed = True
        self._finalizer.detach()
        _return_to_pool(self._raw, leaked=False)


def _return_to_pool(raw, leaked):
    if leaked:
        logger.warning(
            "DB connection was garbage-collected without an explicit .close() call "
            "— returning it to the pool now, but this indicates a leak at the call site."
        )
    try:
        _get_pool().putconn(raw)
    except Exception:
        logger.exception("Failed to return a connection to the pool")


def get_db():
    raw = _get_pool().getconn()
    return Conn(raw)
