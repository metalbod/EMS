"""Computes version/commit history from git, for the app's About panel
(Settings/user menu -> About; routers/frontend.py's GET /api/changelog).

Shared by two callers that need the exact same logic against two different
data sources:
  - scripts/generate_changelog.py (run by deploy.sh) — writes the result to
    CHANGELOG.json at deploy time, since the deployed container has no
    .git (see .dockerignore) and can't compute this at request time.
  - routers/frontend.py's _changelog() — calls this directly as a local-dev
    fallback when CHANGELOG.json isn't present, since local dev does have
    .git; same reasoning as _app_version()'s own local-dev fallback there.
"""
import subprocess

_UNIT_SEP = "\x1f"


def _run(*args):
    return subprocess.run(args, capture_output=True, text=True, check=True).stdout


def _existing_version_tags():
    """[(major, minor, tag_name), ...] sorted newest-first — only tags
    shaped exactly like v<major>.<minor> (deploy.sh's own scheme), so a
    stray differently-shaped tag can never break this."""
    try:
        raw = _run("git", "tag", "-l")
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    tags = []
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("v"):
            continue
        parts = line[1:].split(".")
        if len(parts) != 2 or not all(p.isdigit() for p in parts):
            continue
        tags.append((int(parts[0]), int(parts[1]), line))
    tags.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return tags


def _commits_between(prev_ref, ref):
    """[{sha, summary}, ...], newest first. prev_ref=None means "no earlier
    tag to diff against" — capped to just ref's own commit rather than
    dumping this project's entire pre-versioning history into one entry."""
    fmt = f"%h{_UNIT_SEP}%s"
    try:
        if prev_ref:
            raw = _run("git", "log", "--pretty=format:" + fmt, f"{prev_ref}..{ref}")
        else:
            raw = _run("git", "log", "--pretty=format:" + fmt, "-1", ref)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    commits = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        sha, _, summary = line.partition(_UNIT_SEP)
        commits.append({"sha": sha, "summary": summary})
    return commits


def _date_of(ref):
    try:
        return _run("git", "log", "-1", "--pretty=format:%ad", "--date=short", ref).strip() or None
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def compute_changelog(pending_version=None):
    """[{version, date, commits: [{sha, summary}]}, ...], newest-first.

    pending_version, when given, adds a synthetic leading entry (ref=HEAD)
    for a deploy still in progress whose own vX.Y tag doesn't exist yet —
    deploy.sh's own version computation always runs before the tag is
    created, so this mirrors that exact ordering. Left as None for the
    local-dev fallback, which has no such in-progress-deploy concept."""
    existing = _existing_version_tags()
    entries = [(maj, minr, tag) for maj, minr, tag in existing]
    versions = [(f"{maj}.{minr}", tag) for maj, minr, tag in entries]
    if pending_version is not None:
        versions = [(pending_version, "HEAD")] + versions

    changelog = []
    for i, (version, ref) in enumerate(versions):
        prev_ref = versions[i + 1][1] if i + 1 < len(versions) else None
        changelog.append({
            "version": version,
            "date": _date_of(ref),
            "commits": _commits_between(prev_ref, ref),
        })
    return changelog
