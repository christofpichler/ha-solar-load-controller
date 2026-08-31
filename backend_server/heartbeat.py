#!/usr/bin/env python3
"""Anonymous installation heartbeat collector.

    POST /heartbeat  {"installation_id": "<uuid4>", "version": "1.3.2"}

Stores those two fields plus arrival timestamps in SQLite. Standard library
only. See README.md for the data model and endpoints.
"""

from __future__ import annotations

import base64
import hmac
import json
import logging
import os
import re
import signal
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Shown in the status page footer. Versioned separately from the integration.
COLLECTOR_VERSION = "1.2"

DB_PATH = os.environ.get("HEARTBEAT_DB", "/data/installations.db")
PORT = int(os.environ.get("HEARTBEAT_PORT", "8080"))
ACTIVE_DAYS = int(os.environ.get("HEARTBEAT_ACTIVE_DAYS", "30"))
RETENTION_DAYS = int(os.environ.get("HEARTBEAT_RETENTION_DAYS", "400"))
MAINTENANCE_INTERVAL_SECONDS = int(os.environ.get("HEARTBEAT_MAINTENANCE", "600"))

# /insights returns 404 unless enabled by the flag or by setting both
# credentials. Credentials, when set, are enforced by this process.
INSIGHTS_ENABLED = os.environ.get("HEARTBEAT_INSIGHTS", "").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
INSIGHTS_USER = os.environ.get("HEARTBEAT_INSIGHTS_USER", "")
INSIGHTS_PASSWORD = os.environ.get("HEARTBEAT_INSIGHTS_PASSWORD", "")

MAX_BODY_BYTES = 512
VERSION_PATTERN = re.compile(r"^[0-9A-Za-z][0-9A-Za-z.+_-]{0,31}$")
# ISO 3166-1 alpha-2, or Cloudflare's XX/T1 for unknown/Tor.
COUNTRY_PATTERN = re.compile(r"^[A-Z]{2}$")


def country_from_headers(get_header) -> str | None:
    """Return the two-letter country the proxy resolved, if usable.

    Reads CF-IPCountry, set by Cloudflare from the client IP. The IP itself is
    never read here.
    """
    value = (get_header("CF-IPCountry") or "").strip().upper()
    if COUNTRY_PATTERN.match(value) and value not in {"XX", "T1"}:
        return value
    return None


logging.basicConfig(
    level=getattr(logging, os.environ.get("HEARTBEAT_LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(message)s",
)
_LOGGER = logging.getLogger("heartbeat")

_DB_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=5000")
    return connection


def init_db() -> None:
    """Create the schema if it does not exist yet."""
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    with _DB_LOCK, _connect() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS installations (
                installation_id TEXT PRIMARY KEY,
                version         TEXT NOT NULL,
                first_seen      TEXT NOT NULL,
                last_seen       TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_last_seen ON installations(last_seen)"
        )
        # Country column added in collector 1.2. ALTER on an existing DB is a
        # no-op guard: sqlite has no ADD COLUMN IF NOT EXISTS.
        have = {r[1] for r in connection.execute("PRAGMA table_info(installations)")}
        if "country" not in have:
            connection.execute("ALTER TABLE installations ADD COLUMN country TEXT")
        # Counter for rows removed by prune_stale, kept for the all-time total.
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS retired (
                id    INTEGER PRIMARY KEY CHECK (id = 1),
                count INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        connection.execute("INSERT OR IGNORE INTO retired (id, count) VALUES (1, 0)")


def record_heartbeat(
    installation_id: str, version: str, country: str | None = None
) -> None:
    """Insert or refresh one installation.

    ``country`` is a two-letter code derived by the proxy; it is kept only if
    present, so a heartbeat without it does not wipe a known value.
    """
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as connection:
        connection.execute(
            """
            INSERT INTO installations
                (installation_id, version, first_seen, last_seen, country)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(installation_id) DO UPDATE SET
                version   = excluded.version,
                last_seen = excluded.last_seen,
                country   = COALESCE(excluded.country, installations.country)
            """,
            (installation_id, version, now, now, country),
        )


def prune_stale() -> int:
    """Delete rows older than RETENTION_DAYS, adding them to the retired count."""
    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)
    ).isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as connection:
        cursor = connection.execute(
            "DELETE FROM installations WHERE last_seen < ?", (cutoff,)
        )
        removed = cursor.rowcount or 0
        if removed:
            connection.execute(
                "UPDATE retired SET count = count + ? WHERE id = 1", (removed,)
            )
        return removed


def build_stats() -> dict:
    """Return active installation count and version distribution."""
    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=ACTIVE_DAYS)
    ).isoformat(timespec="seconds")
    with _DB_LOCK, _connect() as connection:
        active = connection.execute(
            "SELECT COUNT(*) FROM installations WHERE last_seen >= ?", (cutoff,)
        ).fetchone()[0]
        stored = connection.execute("SELECT COUNT(*) FROM installations").fetchone()[0]
        retired = connection.execute(
            "SELECT count FROM retired WHERE id = 1"
        ).fetchone()[0]
        versions = dict(
            connection.execute(
                """
                SELECT version, COUNT(*) FROM installations
                WHERE last_seen >= ?
                GROUP BY version
                ORDER BY COUNT(*) DESC, version
                """,
                (cutoff,),
            ).fetchall()
        )
        countries = dict(
            connection.execute(
                """
                SELECT COALESCE(country, '??'), COUNT(*) FROM installations
                WHERE last_seen >= ?
                GROUP BY country
                ORDER BY COUNT(*) DESC
                """,
                (cutoff,),
            ).fetchall()
        )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "collector_version": COLLECTOR_VERSION,
        "active_days": ACTIVE_DAYS,
        "active_installations": active,
        "known_installations": stored,
        "all_time_installations": stored + retired,
        "versions": versions,
        "countries": countries,
    }


def list_installations() -> list[dict]:
    """Return every stored installation."""
    with _DB_LOCK, _connect() as connection:
        rows = connection.execute(
            """
            SELECT installation_id, version, first_seen, last_seen, country
            FROM installations
            ORDER BY last_seen DESC
            """
        ).fetchall()
    return [
        {
            "installation_id": row[0],
            "version": row[1],
            "first_seen": row[2],
            "last_seen": row[3],
            "country": row[4],
        }
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def valid_installation_id(value: object) -> bool:
    """Return whether value is a canonical uuid4 string."""
    if not isinstance(value, str):
        return False
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        return False
    return parsed.version == 4 and str(parsed) == value.lower()


def valid_version(value: object) -> bool:
    """Return whether value looks like a version string."""
    return isinstance(value, str) and bool(VERSION_PATTERN.match(value))


def insights_enabled() -> bool:
    """Return whether the per-installation listing exists at all."""
    return INSIGHTS_ENABLED or bool(INSIGHTS_USER and INSIGHTS_PASSWORD)


def insights_needs_auth() -> bool:
    """Return whether the collector checks credentials itself."""
    return bool(INSIGHTS_USER and INSIGHTS_PASSWORD)


def insights_credentials_ok(header: str | None) -> bool:
    """Validate an Authorization header against the configured credentials."""
    if not header or not header.lower().startswith("basic "):
        return False
    try:
        decoded = base64.b64decode(header.split(" ", 1)[1], validate=True)
        user, _, password = decoded.decode("utf-8").partition(":")
    except (ValueError, UnicodeDecodeError):
        return False
    # Constant-time on both halves.
    return (
        hmac.compare_digest(user, INSIGHTS_USER)
        and hmac.compare_digest(password, INSIGHTS_PASSWORD)
    )



# ---------------------------------------------------------------------------
# Status page
# ---------------------------------------------------------------------------

STATUS_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>Solar Load Controller - Telemetry</title>
<style>
  :root {
    --bg: #f6f7f9; --card: #fff; --fg: #1b1d21; --muted: #6b7280;
    --accent: #f5a623; --bar: #e5e7eb; --line: #e5e7eb;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #16181d; --card: #1e2127; --fg: #e8eaed; --muted: #9aa0a6;
      --accent: #f5a623; --bar: #2c3038; --line: #2c3038;
    }
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 2rem 1rem; background: var(--bg); color: var(--fg);
    font: 15px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  }
  main { max-width: 44rem; margin: 0 auto; }
  h1 { font-size: 1.15rem; font-weight: 600; margin: 0 0 1.5rem; }
  .cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(11rem, 1fr)); gap: 1rem; }
  .card {
    background: var(--card); border: 1px solid var(--line);
    border-radius: 10px; padding: 1.1rem 1.2rem;
  }
  .label { color: var(--muted); font-size: .8rem; text-transform: uppercase; letter-spacing: .04em; }
  .value { font-size: 2.1rem; font-weight: 600; margin-top: .3rem; font-variant-numeric: tabular-nums; }
  section { margin-top: 2rem; }
  h2 { font-size: .8rem; color: var(--muted); text-transform: uppercase;
       letter-spacing: .04em; font-weight: 600; margin: 0 0 .8rem; }
  table { width: 100%; border-collapse: collapse; }
  td { padding: .45rem 0; vertical-align: middle; }
  td.v { font-weight: 600; white-space: nowrap; padding-right: 1rem; font-variant-numeric: tabular-nums; }
  td.n { text-align: right; color: var(--muted); white-space: nowrap;
         padding-left: 1rem; font-variant-numeric: tabular-nums; }
  td.bar { width: 100%; }   /* explicit width; auto layout collapses it to 0 */
  .track { background: var(--bar); border-radius: 4px; height: 9px; width: 100%; }
  .fill { background: var(--accent); border-radius: 4px; height: 9px; }
  footer { margin-top: 2rem; color: var(--muted); font-size: .8rem;
           border-top: 1px solid var(--line); padding-top: .9rem;
           display: flex; justify-content: space-between; gap: 1rem; flex-wrap: wrap; }
  footer a { color: inherit; }
  .err { color: #d13438; }
</style>
</head>
<body>
<main>
  <h1>Solar Load Controller - Telemetry</h1>
  <div class="cards">
    <div class="card"><div class="label">Active</div><div class="value" id="active">\u2013</div></div>
    <div class="card"><div class="label">All time</div><div class="value" id="alltime">\u2013</div></div>
    <div class="card"><div class="label">Versions</div><div class="value" id="vcount">\u2013</div></div>
    <div class="card"><div class="label">Countries</div><div class="value" id="ccount">\u2013</div></div>
  </div>
  <section>
    <h2>Version distribution</h2>
    <table id="versions"></table>
  </section>
  <section>
    <h2>Countries</h2>
    <table id="countries"></table>
  </section>
  <footer id="foot"></footer>
</main>
<script>
(async function () {
  const REPO = "https://github.com/christofpichler/ha-solar-load-controller";
  const $ = (id) => document.getElementById(id);
  try {
    const res = await fetch("stats.json", { cache: "no-store" });
    if (!res.ok) throw new Error("HTTP " + res.status);
    const d = await res.json();

    $("active").textContent = d.active_installations;
    $("alltime").textContent = d.all_time_installations;

    function renderBars(id, obj) {
      const rowsArr = Object.entries(obj || {});
      const max = rowsArr.reduce((m, [, n]) => Math.max(m, n), 0) || 1;
      const total = rowsArr.reduce((s, [, n]) => s + n, 0) || 1;
      $(id).innerHTML = rowsArr.map(([k, n]) => {
        const pct = Math.round((n / total) * 100);
        const label = k === "??" ? "unknown" : k;
        return "<tr><td class='v'>" + label + "</td>" +
               "<td class='bar'><div class='track'><div class='fill' style='width:" +
               Math.max(2, Math.round((n / max) * 100)) + "%'></div></div></td>" +
               "<td class='n'>" + n + " \u00b7 " + pct + "%</td></tr>";
      }).join("") || "<tr><td class='n'>no data yet</td></tr>";
      return rowsArr;
    }

    const entries = renderBars("versions", d.versions);
    $("vcount").textContent = entries.length;
    const cEntries = renderBars("countries", d.countries);
    $("ccount").textContent = cEntries.filter(([k]) => k !== "??").length;

    // Numeric compare so 1.3.10 > 1.3.9.
    const rank = (v) => (v.match(/\\d+/g) || []).map(Number);
    const newest = entries.map(([v]) => v).sort((a, b) => {
      const x = rank(a), y = rank(b);
      for (let i = 0; i < Math.max(x.length, y.length); i++) {
        if ((x[i] || 0) !== (y[i] || 0)) return (y[i] || 0) - (x[i] || 0);
      }
      return 0;
    })[0];

    const right = [];
    if (newest) right.push("integration " + newest);
    if (d.collector_version) right.push("collector " + d.collector_version);

    $("foot").innerHTML =
      "<a href='" + REPO + "'>" + REPO.replace(/^https:\\/\\//, "") + "</a>" +
      "<span>" + right.join(" \u00b7 ") + "</span>";
  } catch (err) {
    $("foot").innerHTML = "<a href='" + REPO + "'>" + REPO.replace(/^https:\\/\\//, "") +
      "</a><span class='err'>stats.json unavailable: " + err.message + "</span>";
  }
})();
</script>
</body>
</html>
"""


INSIGHTS_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>Solar Load Controller - Insights</title>
<style>
  :root {
    --bg: #f6f7f9; --card: #fff; --fg: #1b1d21; --muted: #6b7280;
    --accent: #f5a623; --line: #e5e7eb; --stale: #d13438;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #16181d; --card: #1e2127; --fg: #e8eaed; --muted: #9aa0a6;
      --accent: #f5a623; --line: #2c3038; --stale: #f47c7c;
    }
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 2rem 1rem; background: var(--bg); color: var(--fg);
    font: 15px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  }
  main { max-width: 60rem; margin: 0 auto; }
  h1 { font-size: 1.15rem; font-weight: 600; margin: 0 0 .4rem; }
  .sub { color: var(--muted); font-size: .85rem; margin-bottom: 1.5rem; }
  .wrap { background: var(--card); border: 1px solid var(--line);
          border-radius: 10px; overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-size: .88rem; }
  th {
    text-align: left; color: var(--muted); font-weight: 600; font-size: .75rem;
    text-transform: uppercase; letter-spacing: .04em;
    padding: .8rem 1rem; border-bottom: 1px solid var(--line); white-space: nowrap;
    cursor: pointer; user-select: none;
  }
  th .arrow { opacity: .5; font-size: .7rem; margin-left: .3rem; }
  td { padding: .6rem 1rem; border-bottom: 1px solid var(--line); white-space: nowrap; }
  tr:last-child td { border-bottom: none; }
  td.id { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: .82rem; }
  td.v { font-weight: 600; }
  td.num { color: var(--muted); font-variant-numeric: tabular-nums; }
  td.num.stale { color: var(--stale); }   /* td.num would win over .stale */
  footer { margin-top: 2rem; color: var(--muted); font-size: .8rem;
           border-top: 1px solid var(--line); padding-top: .9rem;
           display: flex; justify-content: space-between; gap: 1rem; flex-wrap: wrap; }
  footer a { color: inherit; }
  .err { color: var(--stale); }
</style>
</head>
<body>
<main>
  <h1>Solar Load Controller - Insights</h1>
  <div class="sub" id="sub"></div>
  <div class="wrap">
    <table>
      <thead>
        <tr id="head">
          <th data-key="installation_id">Installation</th>
          <th data-key="version">Version</th>
          <th data-key="country">Country</th>
          <th data-key="first_seen">First seen</th>
          <th data-key="last_seen">Last heartbeat</th>
          <th data-key="last_seen">Age</th>
        </tr>
      </thead>
      <tbody id="rows"></tbody>
    </table>
  </div>
  <footer id="foot"></footer>
</main>
<script>
(async function () {
  const REPO = "https://github.com/christofpichler/ha-solar-load-controller";
  const $ = (id) => document.getElementById(id);
  const fmt = (iso) => new Date(iso).toLocaleString();

  function age(iso) {
    const days = (Date.now() - new Date(iso).getTime()) / 86400000;
    if (days < 1) return [Math.round(days * 24) + "h", false];
    return [Math.round(days) + "d", days > 30];
  }

  try {
    const res = await fetch("insights.json", { cache: "no-store" });
    if (!res.ok) throw new Error("HTTP " + res.status);
    const d = await res.json();

    $("sub").textContent =
      d.installations.length + " stored \u00b7 active window " +
      d.active_days + " days \u00b7 rows expire after " + d.retention_days + " days";

    const rows = d.installations;
    let sortKey = "last_seen", sortDir = -1;

    function render() {
      const sorted = rows.slice().sort((a, b) => {
        const x = a[sortKey] ?? "", y = b[sortKey] ?? "";
        return x < y ? -sortDir : x > y ? sortDir : 0;
      });
      $("rows").innerHTML = sorted.map((r) => {
        const [txt, stale] = age(r.last_seen);
        return "<tr>" +
          "<td class='id'>" + r.installation_id + "</td>" +
          "<td class='v'>" + r.version + "</td>" +
          "<td class='num'>" + (r.country || "\u2013") + "</td>" +
          "<td class='num'>" + fmt(r.first_seen) + "</td>" +
          "<td class='num'>" + fmt(r.last_seen) + "</td>" +
          "<td class='num" + (stale ? " stale" : "") + "'>" + txt + "</td>" +
          "</tr>";
      }).join("") || "<tr><td class='num' colspan='6'>no installations yet</td></tr>";
      [...$("head").children].forEach((th) => {
        const a = th.querySelector(".arrow");
        if (a) a.remove();
        if (th.dataset.key === sortKey) {
          th.insertAdjacentHTML("beforeend",
            "<span class='arrow'>" + (sortDir < 0 ? "\u25bc" : "\u25b2") + "</span>");
        }
      });
    }

    [...$("head").children].forEach((th) => {
      th.addEventListener("click", () => {
        const k = th.dataset.key;
        if (k === sortKey) { sortDir = -sortDir; } else { sortKey = k; sortDir = -1; }
        render();
      });
    });
    render();

    $("foot").innerHTML =
      "<a href='" + REPO + "'>" + REPO.replace(/^https:\\/\\//, "") + "</a>" +
      "<span>collector " + d.collector_version + "</span>";
  } catch (err) {
    $("foot").innerHTML = "<span class='err'>insights.json unavailable: " + err.message + "</span>";
  }
})();
</script>
</body>
</html>
"""

# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

class HeartbeatHandler(BaseHTTPRequestHandler):
    """Minimal handler for the heartbeat and stats endpoints."""

    server_version = "heartbeat"
    sys_version = ""

    # Set while serving a HEAD request: same headers as GET, no body.
    _head_only = False

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        """Suppress the default access log, which includes the client address."""
        return

    def _unauthorized(self) -> None:
        """Send a 401 with a Basic challenge."""
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="insights"')
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def _insights_allowed(self) -> bool:
        """Return whether this request may see per-installation data."""
        if not insights_enabled():
            self._respond(404)
            return False
        if insights_needs_auth() and not insights_credentials_ok(
            self.headers.get("Authorization")
        ):
            self._unauthorized()
            return False
        return True

    def _respond(self, status: int, body: bytes = b"", content_type: str = "") -> None:
        self.send_response(status)
        if body:
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if body and not self._head_only:
            self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        """Accept one heartbeat."""
        if self.path.rstrip("/") != "/heartbeat":
            self._respond(404)
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            _LOGGER.debug("Rejected heartbeat: bad Content-Length")
            self._respond(400)
            return

        if length <= 0 or length > MAX_BODY_BYTES:
            _LOGGER.debug("Rejected heartbeat: body length %s", length)
            self._respond(400)
            return

        try:
            payload = json.loads(self.rfile.read(length))
        except (ValueError, OSError):
            _LOGGER.debug("Rejected heartbeat: body is not JSON")
            self._respond(400)
            return

        if not isinstance(payload, dict):
            _LOGGER.debug("Rejected heartbeat: body is not an object")
            self._respond(400)
            return

        installation_id = payload.get("installation_id")
        version = payload.get("version")
        if not valid_installation_id(installation_id) or not valid_version(version):
            _LOGGER.debug("Rejected heartbeat: invalid installation_id or version")
            self._respond(400)
            return

        country = country_from_headers(self.headers.get)
        try:
            record_heartbeat(installation_id, version, country)
        except sqlite3.Error as err:
            _LOGGER.error("Could not record heartbeat: %s", err)
            self._respond(503)
            return

        _LOGGER.debug("Recorded heartbeat: version=%s country=%s", version, country or "-")
        self._respond(204)

    def _method_not_allowed(self) -> None:
        """Reply 405 with an empty body, hiding the default 501 stack page."""
        self.send_response(405)
        self.send_header("Allow", "GET, HEAD, POST")
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _method_not_allowed  # noqa: N815

    def do_HEAD(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        """Answer with the headers GET would send, without the body."""
        self._head_only = True
        try:
            self.do_GET()
        finally:
            self._head_only = False

    def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        """Serve the current statistics and a health probe."""
        path = self.path.rstrip("/") or "/"
        if path == "/health":
            self._respond(200, b'{"status":"ok"}', "application/json")
            return

        if path in ("/", "/index.html"):
            self._respond(
                200, STATUS_PAGE.encode("utf-8"), "text/html; charset=utf-8"
            )
            return

        if path in ("/insights", "/insights.html"):
            if not self._insights_allowed():
                return
            self._respond(
                200, INSIGHTS_PAGE.encode("utf-8"), "text/html; charset=utf-8"
            )
            return

        if path == "/insights.json":
            if not self._insights_allowed():
                return
            try:
                body = json.dumps(
                    {
                        "collector_version": COLLECTOR_VERSION,
                        "active_days": ACTIVE_DAYS,
                        "retention_days": RETENTION_DAYS,
                        "installations": list_installations(),
                    },
                    indent=2,
                ).encode("utf-8")
            except sqlite3.Error as err:
                _LOGGER.error("Could not list installations: %s", err)
                self._respond(503)
                return
            self._respond(200, body, "application/json")
            return

        if path in ("/stats.json", "/stats"):
            try:
                body = json.dumps(build_stats(), indent=2).encode("utf-8")
            except sqlite3.Error as err:
                _LOGGER.error("Could not build stats: %s", err)
                self._respond(503)
                return
            self._respond(200, body, "application/json")
            return

        self._respond(404)


# ---------------------------------------------------------------------------
# Maintenance
# ---------------------------------------------------------------------------

def maintenance_loop(stop_event: threading.Event) -> None:
    """Prune stale rows until asked to stop."""
    while not stop_event.is_set():
        try:
            removed = prune_stale()
            if removed:
                _LOGGER.info("Pruned %s stale installation(s)", removed)
        except sqlite3.Error as err:
            _LOGGER.warning("Maintenance run failed: %s", err)
        stop_event.wait(MAINTENANCE_INTERVAL_SECONDS)


def main() -> None:
    """Start the collector."""
    init_db()

    stop_event = threading.Event()
    worker = threading.Thread(
        target=maintenance_loop, args=(stop_event,), daemon=True
    )
    worker.start()

    httpd = ThreadingHTTPServer(("", PORT), HeartbeatHandler)

    def _shutdown(_signum, _frame) -> None:
        _LOGGER.info("Shutting down")
        stop_event.set()
        threading.Thread(target=httpd.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    _LOGGER.info(
        "Listening on port %s (active window %s days, retention %s days)",
        PORT,
        ACTIVE_DAYS,
        RETENTION_DAYS,
    )
    httpd.serve_forever()
    httpd.server_close()


if __name__ == "__main__":
    main()
