# EMS MCP server (Claude connector)

Lets a person ask Claude to clock them in/out and check their leave balance, acting only as themselves.

```
Claude ──► ems-mcp (this folder) ──► ems-app (/api/...)         OAuth login + consent live in ems-app (routers/oauth.py)
```

- **No data, no secrets here.** Each call carries a token EMS issued to that person; this server checks it with
  `GET /api/oauth/whoami` and forwards it. EMS enforces everything (company switch, revoke, scope per route).
- Tools: `clock_in`, `clock_out`, `attendance_today`, `leave_balance`. Claude is told to ask for the person's location
  before clocking; if they decline, EMS records the clock-in as "no location".
- HR turns it on per company in EMS: Settings → Claude Access (off by default).

## Run locally
```bash
cd mcp && python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt pytest
EMS_BASE_URL=http://localhost:8010 MCP_PUBLIC_URL=http://localhost:8090/mcp PORT=8090 python server.py
pytest            # unit tests (EMS faked)
```
Use the `EMS-test-db` dev server (port 8010) for EMS, never prod. Do not add an `__init__.py` here: this folder is named
`mcp`, and the installed `mcp` package must keep winning the import.

## Deploy (Fly, region nrt)
```bash
cd mcp
fly launch --no-deploy --copy-config --name ems-mcp --region nrt   # first time only
fly deploy --app ems-mcp
```
Connector address for staff: `https://ems-mcp.fly.dev/mcp` (Claude → Settings → Connectors → Add custom connector).
Deploy EMS first (`./deploy.sh`) — it carries the migration and the OAuth endpoints this server depends on.

## Claude skill
`skill/ems-attendance/SKILL.md` teaches Claude how to use these tools (check status first, ask for location, confirm clock-out,
report results as returned). `skill/ems-attendance.zip` is the same folder zipped for upload in Claude → Settings → Capabilities →
Skills. Rebuild the zip after editing: `cd mcp/skill && rm -f ems-attendance.zip && zip -qr ems-attendance.zip ems-attendance`.
For Claude Code, copy the folder to `~/.claude/skills/`.
