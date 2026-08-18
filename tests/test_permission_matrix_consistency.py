"""Guards against permission_matrix.py's own coverage claim silently going
stale — see NOT_YET_ENFORCED_MODULES's docstring for the incident this is
named after. Pure data checks: no DB connection, no app import, so this
runs fast and can't be flaky.
"""
from core.permission_matrix import MATRIX, ENFORCED_ACTION_KEYS, NOT_YET_ENFORCED_MODULES


def _allow_deny_keys(module: dict) -> list[str]:
    """Only ALLOW/DENY rows are override-eligible at all (see the module
    docstring) — a module made entirely of OWN/SUBORDINATE/CONFIGURABLE/
    NO_RESTRICTION rows (e.g. Dashboard, Org Chart, Locations) has nothing
    to retrofit and isn't a gap just because ENFORCED_ACTION_KEYS has none
    of its keys."""
    return [
        a["key"] for a in module["actions"]
        if any(v in ("allow", "deny") for v in a["access"].values())
    ]


def test_every_module_is_retrofitted_or_documented():
    for module in MATRIX:
        name = module["module"]
        allow_deny_keys = _allow_deny_keys(module)
        if not allow_deny_keys:
            continue  # nothing override-eligible in this module at all
        has_enforced = any(k in ENFORCED_ACTION_KEYS for k in allow_deny_keys)
        is_documented = name in NOT_YET_ENFORCED_MODULES
        assert has_enforced or is_documented, (
            f"{name!r} has {len(allow_deny_keys)} override-eligible action(s) but none are "
            f"in ENFORCED_ACTION_KEYS, and it isn't in NOT_YET_ENFORCED_MODULES either — "
            f"either retrofit it, or add an entry to NOT_YET_ENFORCED_MODULES explaining why not."
        )


def test_not_yet_enforced_entries_are_accurate():
    module_names = {m["module"] for m in MATRIX}
    modules_by_name = {m["module"]: m for m in MATRIX}
    for name, reason in NOT_YET_ENFORCED_MODULES.items():
        assert name in module_names, (
            f"NOT_YET_ENFORCED_MODULES references {name!r}, which doesn't match any "
            f"MATRIX module name — stale entry (renamed module?)."
        )
        assert reason and reason.strip(), f"NOT_YET_ENFORCED_MODULES[{name!r}] has an empty reason."
        allow_deny_keys = _allow_deny_keys(modules_by_name[name])
        already_enforced = [k for k in allow_deny_keys if k in ENFORCED_ACTION_KEYS]
        assert not already_enforced, (
            f"{name!r} is listed in NOT_YET_ENFORCED_MODULES but already has enforced "
            f"key(s) {already_enforced} — it's been retrofitted (fully or partially); "
            f"remove or narrow this entry instead of leaving it stale."
        )
