"""App-startup seed data: superadmin user and onboarding/offboarding templates.

Extracted out of main.py (a composition root — see its docstring) so that
"what data does this app need to boot" lives in its own module instead of
mixed into router wiring, middleware, and the health check.
"""
from db import get_admin_db

from core.deps import hash_password, verify_password
from core.onboarding_seed import seed_ob_templates_bulk


def init_db_seed():
    """Initialize seed data: superadmin user and OB templates.

    Called once on app startup (see main.py's startup event handler), after
    the schema is created (either via Alembic or on fresh app boot when no
    schema yet exists). Does not run any DDL — only INSERT and UPDATE
    statements for seed data.
    """
    conn = get_admin_db()
    try:
        # Seed platform superadmin. must_change_password=1 forces a password
        # rotation before anything else meaningful can happen with this
        # well-known default credential — see routers/auth.py's login response
        # and routers/users.py's update_user, which clears the flag once a real
        # password is set.
        if not conn.execute("SELECT id FROM users WHERE role='superadmin' LIMIT 1").fetchone():
            conn.execute("""
                INSERT INTO users (institution_id, username, full_name, email, password_hash, role, must_change_password)
                VALUES (NULL, ?, ?, ?, ?, 'superadmin', 1)
            """, ("superadmin", "Platform Administrator", "admin@platform.com", hash_password("Admin@123")))
            conn.commit()

        # One-time backfill for superadmin accounts seeded before
        # must_change_password existed: if the password still matches the known
        # default, flag it for rotation now instead of leaving it silently
        # unrotated forever. Skips accounts that already changed their password
        # (verify_password against the old default correctly fails for those).
        for row in conn.execute(
            "SELECT id, password_hash FROM users WHERE role='superadmin' AND must_change_password=0"
        ).fetchall():
            if verify_password("Admin@123", row["password_hash"]):
                conn.execute("UPDATE users SET must_change_password=1 WHERE id=?", (row["id"],))
        conn.commit()

        # Seed OB templates for existing institutions that don't have them —
        # seed_ob_templates_bulk avoids the per-institution round-trips the old
        # loop-over-every-institution-every-boot approach had (see its docstring;
        # with 1000+ institutions accumulated in this shared DB, that alone added
        # minutes to every startup).
        seed_ob_templates_bulk(conn)
        conn.commit()
    finally:
        conn.close()
