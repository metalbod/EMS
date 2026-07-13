"""
Postgres (Supabase) connection layer that mimics the sqlite3 API surface
used throughout main.py — conn.execute(sql_with_question_marks, params),
row["col"] / row[0] / dict(row) access, and last_insert_rowid() emulation —
so the application query code did not need to be rewritten call-by-call.
"""
import contextvars
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
# Schema DDL (init_db(), Alembic migrations) needs a role with ownership-level
# privileges; regular request-serving queries should NOT run as that role,
# since Postgres's RLS is bypassed unconditionally for a role with the
# BYPASSRLS attribute (confirmed set on this project's `postgres` role) —
# independent of, and not overridden by, FORCE ROW LEVEL SECURITY or even
# non-superuser status. See migrations/versions/eb95a484c74a_* for the RLS
# policies this separation makes actually effective. Falls back to
# DATABASE_URL for any environment that hasn't set up the separate
# non-bypass app role yet (schema DDL keeps working; RLS just isn't
# meaningfully enforced there, same as before this split existed).
ADMIN_DATABASE_URL = os.environ.get("ADMIN_DATABASE_URL", DATABASE_URL)

_pool = None
_admin_pool = None


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


def _get_admin_pool():
    global _admin_pool
    if _admin_pool is None:
        if not ADMIN_DATABASE_URL:
            raise RuntimeError(
                "ADMIN_DATABASE_URL (or DATABASE_URL as its fallback) environment "
                "variable is not set. Set one to your Supabase Postgres connection "
                "string for the owner/admin role used by schema migrations."
            )
        # Small pool: only used for schema DDL at boot/migration time, not
        # per-request traffic, so it doesn't need the same capacity as the
        # app's regular pool.
        _admin_pool = psycopg2.pool.SimpleConnectionPool(1, 3, dsn=ADMIN_DATABASE_URL, sslmode="require")
    return _admin_pool


_INSERT_RE = re.compile(r"^\s*INSERT\s+INTO", re.IGNORECASE)
_RETURNING_RE = re.compile(r"RETURNING", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Row-level security context
#
# Tenant-scoped tables have Postgres RLS policies (see the tenant_isolation
# migration) that check two per-transaction GUCs: app.bypass_rls and
# app.current_institution_id. This is defense-in-depth against an endpoint's
# own query forgetting a `WHERE institution_id=?` filter — if the GUCs
# aren't set to scope a request, the policies fail CLOSED (zero rows), not
# open, since Postgres's `postgres` role here is confirmed non-superuser and
# every relevant table has FORCE ROW LEVEL SECURITY applied.
#
# A contextvars.ContextVar (not a plain global) is used because FastAPI/
# Starlette gives each request its own logical context — including for sync
# path functions run via anyio's threadpool, which copies the calling
# context into the worker call — so concurrent requests never see each
# other's institution scoping, without needing to touch the hundreds of
# `conn = get_db()` call sites throughout the routers.
#
# Default (contextvar unset) is bypass=True — i.e. today's actual behavior,
# unrestricted access — for any code path that doesn't go through
# core/deps.py's get_current_user: login (pre-authentication), health
# checks, init_db()'s own schema/seed queries, and direct get_db() use in
# tests/fixtures.
# ---------------------------------------------------------------------------
_rls_context: "contextvars.ContextVar[tuple]" = contextvars.ContextVar("ems_rls_context", default=None)


def set_rls_context(institution_id, bypass_rls: bool) -> None:
    """Scope subsequent get_db() connections in the current request/task to
    a specific institution at the Postgres level. See core/deps.py's
    get_current_user, the one dependency nearly every protected endpoint
    already goes through, for where this is actually called."""
    _rls_context.set((institution_id, bypass_rls))


def _apply_rls_context(raw) -> None:
    ctx = _rls_context.get()
    institution_id, bypass = ctx if ctx is not None else (None, True)
    cur = raw.cursor()
    # set_config(..., is_local=true) is the parameterized equivalent of
    # `SET LOCAL` — plain SET/SET LOCAL don't support bind parameters for
    # the value, and string-formatting an f-string into SQL here would be
    # a real injection risk since these run on every connection borrow.
    cur.execute("SELECT set_config('app.bypass_rls', %s, true)", ("true" if bypass else "false",))
    cur.execute(
        "SELECT set_config('app.current_institution_id', %s, true)",
        (str(institution_id) if institution_id is not None else "",)
    )
    cur.close()


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
    def __init__(self, raw, admin=False):
        self._raw = raw
        self._admin = admin
        self._last_id = None
        self._closed = False
        # Safety net: if calling code forgets to call .close() (e.g. an
        # exception raised between get_db() and the endpoint's close() call),
        # this returns the connection to the pool once the Conn is garbage
        # collected instead of leaking it out of the (small, 10-connection)
        # pool permanently. GC timing isn't deterministic, so this is a
        # backstop, not a substitute for closing explicitly.
        self._finalizer = weakref.finalize(self, _return_to_pool, raw, leaked=True, admin=admin)
        _apply_rls_context(raw)

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
        # set_config(..., is_local=true) (like SET LOCAL) only lasts for the
        # transaction it was set in — it clears the instant this commit()
        # ends that transaction. A very common pattern throughout this
        # codebase is commit() followed by a further SELECT on the SAME
        # connection to return the freshly written row (e.g.
        # `conn.commit(); row = conn.execute(...)`) — that follow-up query
        # would silently run with no RLS scoping at all (falling back to
        # bypass=True) unless reapplied here for the new transaction.
        _apply_rls_context(self._raw)

    def rollback(self):
        self._raw.rollback()
        # Same reasoning as commit() above — a rollback also ends the
        # transaction the context was scoped to.
        _apply_rls_context(self._raw)

    def close(self):
        if self._closed:
            return
        self._closed = True
        self._finalizer.detach()
        # psycopg2 connections are not autocommit, so every .execute() call
        # implicitly opens a transaction that stays open until explicitly
        # committed or rolled back. Read-only call sites (the majority —
        # every GET/list endpoint) never call .commit(), so without this
        # rollback, .close() would return the connection to the pool with an
        # open transaction still holding its locks and snapshot. The next
        # borrower inherits that half-open transaction, and Supabase's
        # connection pooler can forcibly terminate long-idle-in-transaction
        # connections — very likely the real cause of the "transient"
        # deadlocks and connection-reset errors seen intermittently in the
        # test suite, not actual infra flakiness. Rolling back here is safe
        # even when nothing was written (no-op on a clean read-only
        # transaction) and correct when something *was* written but the
        # caller forgot to commit (better to lose the write than leak an
        # open transaction into the pool).
        try:
            self._raw.rollback()
        except Exception:
            logger.exception("Failed to roll back connection before returning it to the pool")
        _return_to_pool(self._raw, leaked=False, admin=self._admin)


def _return_to_pool(raw, leaked, admin=False):
    if leaked:
        logger.warning(
            "DB connection was garbage-collected without an explicit .close() call "
            "— returning it to the pool now, but this indicates a leak at the call site."
        )
        # Same reasoning as Conn.close(): don't return a connection to the
        # pool with an open transaction still holding locks/snapshot.
        try:
            raw.rollback()
        except Exception:
            logger.exception("Failed to roll back a leaked connection before returning it to the pool")
    try:
        (_get_admin_pool() if admin else _get_pool()).putconn(raw)
    except Exception:
        logger.exception("Failed to return a connection to the pool")


def get_db():
    raw = _get_pool().getconn()
    return Conn(raw)


def get_admin_db():
    """Owner-privileged connection for schema DDL only (init_db(),
    Alembic) — see ADMIN_DATABASE_URL above for why this must be a
    separate connection from get_db()'s regular app-role pool."""
    raw = _get_admin_pool().getconn()
    return Conn(raw, admin=True)
