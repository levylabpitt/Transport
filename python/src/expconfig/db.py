"""The lab database (PostgreSQL), as Configure Experiment uses it.

Queries are those of the LabVIEW DB VIs (src/Control Experiment/subVIs/DB *.vi).
Connection details come from the standard pgpass file
(%APPDATA%\\postgresql\\pgpass.conf), the same file the LabVIEW PGPASS
connection manager reads; libpq looks the password up there itself, so no
credentials live in this code or its config.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

DEFAULT_HOST = "db.levylab.org"
DEFAULT_PORT = 5432
DEFAULT_DBNAME = "levylab"

# Roles that are not experimenters (DB Get Current Users.vi).
NON_EXPERIMENTER_ROLES = ("InfoTech", "Support Staff, Lab Organizer")

# Each distinct wiring is stored once in public.wiring (an ordinary table, keyed
# by a hash of its content); a measurement row in llab_001 points to it by wiring_id.
WIRING_SCHEMA = "levylab.wiring/1"


@dataclass
class DbSettings:
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    dbname: str = DEFAULT_DBNAME
    read_user: str = "llab_reader"
    write_user: str = "llab_writer"
    timeout: int = 5

    def dsn(self, user: str) -> str:
        return f"host={self.host} port={self.port} dbname={self.dbname} user={user} connect_timeout={self.timeout}"


@dataclass
class Lookups:
    users: list[str] = field(default_factory=list)
    station_types: list[str] = field(default_factory=list)
    stations: dict[str, list[str]] = field(default_factory=dict)  # type -> names
    error: str = ""

    def stations_of(self, station_type: str) -> list[str]:
        if not station_type:
            return sorted({s for v in self.stations.values() for s in v})
        return self.stations.get(station_type, [])


def _connect(settings: DbSettings, user: str):
    import psycopg  # imported here so the rest of the app works without the driver

    return psycopg.connect(settings.dsn(user))


def lookups(settings: DbSettings, connect=_connect) -> Lookups:
    """Everything the experiment form's rings need, in one connection."""
    try:
        with connect(settings, settings.read_user) as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT first_name FROM public.users WHERE end_date IS NULL AND role <> ALL(%s) ORDER BY first_name",
                (list(NON_EXPERIMENTER_ROLES),),
            )
            users = [r[0].strip() for r in cur.fetchall() if r[0]]
            cur.execute("SELECT DISTINCT type FROM public.stations ORDER BY type")
            types = [r[0].strip() for r in cur.fetchall() if r[0]]
            cur.execute("SELECT type, name FROM public.stations ORDER BY name")
            stations: dict[str, list[str]] = {}
            for t, n in cur.fetchall():
                if n:
                    stations.setdefault((t or "").strip(), []).append(n.strip())
        return Lookups(users, types, stations)
    except Exception as err:  # offline, no pgpass entry, no driver
        return Lookups(error=f"{type(err).__name__}: {err}".strip())


def wiring_document(cfg) -> dict:
    """What goes into public.wiring.wiring: the tables and the topology graph."""
    from . import topology

    return {
        "schema": WIRING_SCHEMA,
        "channels": [c.to_dict() for c in cfg.channels],
        "outputs": [o.to_dict() for o in cfg.outputs],
        "kh_override": cfg.kh_override,
        "topology": topology.build(cfg),
    }


def wiring_hash(doc: dict) -> str:
    """Content hash used to store an identical wiring only once."""
    canonical = json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


_USER = "(SELECT user_id FROM public.users WHERE first_name = %(user)s LIMIT 1)"
_STATION = "(SELECT station_id FROM public.stations WHERE name = %(station)s LIMIT 1)"


def record_measurement(settings: DbSettings, *, user: str, station: str, device: str, measurement: str,
                       lockin_serial: str, kh_serial: str, wiring: dict | None = None,
                       connect=_connect) -> int | None:
    """Insert one measurement row (DB Set Measurement.vi). Empty strings become NULL.

    With a wiring document, it is stored in public.wiring unless an identical one is
    already there, and the measurement row gets its wiring_id. Returns the wiring_id.
    Both inserts are one transaction.
    """
    def v(x):
        return x or None

    params = {"user": v(user), "station": v(station), "device": v(device), "measurement": v(measurement),
              "lockin": v(lockin_serial), "kh": v(kh_serial), "wiring_id": None}
    with connect(settings, settings.write_user) as conn:
        cur = conn.cursor()
        if wiring is not None:
            cur.execute("SELECT to_regclass('public.wiring') IS NOT NULL")
            row = cur.fetchone()
            if row and row[0]:
                params["sha256"] = wiring_hash(wiring)
                params["wiring"] = json.dumps(wiring)
                cur.execute(
                    "INSERT INTO public.wiring (user_id, station_id, device_id, sha256, wiring) "
                    f"VALUES ({_USER}, {_STATION}, %(device)s, %(sha256)s, %(wiring)s::jsonb) "
                    "ON CONFLICT (sha256) DO NOTHING RETURNING wiring_id", params)
                row = cur.fetchone()
                if row is None:  # stored before
                    cur.execute("SELECT wiring_id FROM public.wiring WHERE sha256 = %(sha256)s", params)
                    row = cur.fetchone()
                params["wiring_id"] = row[0] if row else None
        cur.execute(
            'INSERT INTO public.llab_001 ("time", user_id, station_id, device_id, measurement_id, '
            "lockin_id, kh_id, wiring_id) "
            f"VALUES (now(), {_USER}, {_STATION}, %(device)s, %(measurement)s, %(lockin)s, %(kh)s, "
            "%(wiring_id)s)", params)
        conn.commit()
    return params["wiring_id"]
