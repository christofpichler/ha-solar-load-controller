# Telemetry Collector

The server side of the anonymous installation heartbeat described in the main
[README](../README.md#anonymous-usage-statistics).

It is published here so the claim made there is verifiable rather than taken on
trust: the integration says it sends two fields and nothing else, and this is
the code that receives them.

The resulting numbers are public: <https://telemetry.cloudpichler.net>

## What it receives

One request shape, once a day per installation:

```http
POST /heartbeat
Content-Type: application/json

{"installation_id": "<uuid4>", "version": "1.3.2"}
```

Anything else is rejected with `400` before it reaches the database. Extra
fields in the payload are ignored, not stored.

## What it stores

The entire schema:

```sql
CREATE TABLE installations (
    installation_id TEXT PRIMARY KEY,
    version         TEXT NOT NULL,
    first_seen      TEXT NOT NULL,
    last_seen       TEXT NOT NULL
);

CREATE TABLE retired (
    id    INTEGER PRIMARY KEY CHECK (id = 1),
    count INTEGER NOT NULL DEFAULT 0
);
```

Four columns, of which two come from the payload and two are timestamps
generated on arrival. The second table holds a single integer: how many
installations have expired, so the all-time total survives without their ids.

There is no other table and no other write path.

## Privacy properties

These are enforced in the code above, not merely intended:

**Client addresses are never logged.** `BaseHTTPRequestHandler` prints the
client address on every request by default. `log_message` is overridden to
output nothing, so the IP is never read, stored or printed. The only log line
the collector writes during normal operation is the one at startup.

**Rows expire.** Anything not seen for `HEARTBEAT_RETENTION_DAYS` (400 by
default) is deleted, so the identifier does not live on indefinitely. A counter
is raised first, so the installation still counts towards the all-time total
without its id being kept.

The window is longer than the obvious 90 days on purpose: this controller runs
seasonally. A pool pump is typically shut down over winter, and an installation
that goes quiet for a few months has not disappeared — it is waiting for spring.

**Input is validated.** Only a canonical uuid4 and a short version string are
accepted, so a scanner that finds the endpoint cannot fill the table with junk.

**Per-installation data is not served by default.** The aggregate endpoints
(`/` and `/stats.json`) never expose an identifier. There is a `/insights`
route that lists them for the operator, and it returns `404` unless it is
explicitly switched on — an unset flag fails closed rather than relying on a
proxy rule having been configured correctly.

**The installation id means nothing on its own.** It is generated with
`uuid.uuid4()` on the client, has no relation to the machine, the Home Assistant
instance or the configuration, and is stored in that installation's `.storage`.
Deleting it there produces a new one and orphans the old row, which then expires.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/heartbeat` | Record one installation. `204` on success, `400` on bad input |
| `GET` | `/` | Status page — counts and version distribution |
| `GET` | `/stats.json` | The same numbers as JSON |
| `GET` | `/health` | Liveness probe |
| `GET` | `/insights` | Per-installation listing. **Off unless enabled**, see below |

```json
{
  "active_installations": 12,
  "known_installations": 15,
  "all_time_installations": 18,
  "versions": {"1.3.2": 11, "1.3.1": 4}
}
```

`active` is what reported within `HEARTBEAT_ACTIVE_DAYS`, `known` is what is
still stored, `all_time` adds the retired ones. An installation that goes quiet
for longer than the retention window and later returns is counted twice in the
all-time figure — the point of dropping the id is that it can no longer be
recognised.

`GET /heartbeat` returns `404`: the intake is POST-only, and the reporting
endpoints accept nothing.

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `HEARTBEAT_ACTIVE_DAYS` | `30` | Days without contact before an installation stops counting as active |
| `HEARTBEAT_RETENTION_DAYS` | `400` | Days without contact before the row is deleted and counted as retired |
| `HEARTBEAT_PORT` | `8080` | Listen port |
| `HEARTBEAT_DB` | `/data/installations.db` | SQLite file |
| `HEARTBEAT_STATS` | `/data/stats.json` | Generated statistics file |
| `HEARTBEAT_MAINTENANCE` | `600` | Seconds between prune and stats refresh |
| `HEARTBEAT_INSIGHTS` | unset | Set to `1` to expose `/insights` |
| `HEARTBEAT_INSIGHTS_USER` | unset | Optional built-in basic auth for `/insights` |
| `HEARTBEAT_INSIGHTS_PASSWORD` | unset | Optional built-in basic auth for `/insights` |

## Running it

Standard library only — no dependencies to install, audit or update:

```bash
HEARTBEAT_DB=./installations.db HEARTBEAT_STATS=./stats.json \
HEARTBEAT_PORT=8080 python3 heartbeat.py
```

In production it runs in a container behind a reverse proxy that terminates TLS.
Deployment details are specific to one host and are not part of this repository.
