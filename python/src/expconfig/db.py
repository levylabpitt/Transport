"""The lab database (PostgreSQL), as Configure Experiment uses it.

Queries are those of the LabVIEW DB VIs (src/Control Experiment/subVIs/DB *.vi).
Connection details come from the standard pgpass file
(%APPDATA%\\postgresql\\pgpass.conf), the same file the LabVIEW PGPASS
connection manager reads; libpq looks the password up there itself, so no
credentials live in this code or its config.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

DEFAULT_HOST = "db.levylab.org"
DEFAULT_PORT = 5432
DEFAULT_DBNAME = "levylab"

# Roles that are not experimenters (DB Get Current Users.vi).
NON_EXPERIMENTER_ROLES = ("InfoTech", "Support Staff, Lab Organizer")

# Optional column for the wiring topology on the measurement table. The table does
# not have it today; when someone adds it (jsonb), record_measurement fills it.
WIRING_COLUMN = "wiring"


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


def record_measurement(settings: DbSettings, *, user: str, station: str, device: str, measurement: str,
                       lockin_serial: str, kh_serial: str, wiring: dict | None = None,
                       connect=_connect) -> None:
    """Insert one measurement row (DB Set Measurement.vi). Empty strings become NULL."""
    def v(x):
        return x or None

    cols = ["time", "user_id", "station_id", "device_id", "measurement_id", "lockin_id", "kh_id"]
    vals = ["now()",
            "(SELECT user_id FROM public.users WHERE first_name = %(user)s LIMIT 1)",
            "(SELECT station_id FROM public.stations WHERE name = %(station)s LIMIT 1)",
            "%(device)s", "%(measurement)s", "%(lockin)s", "%(kh)s"]
    params = {"user": v(user), "station": v(station), "device": v(device), "measurement": v(measurement),
              "lockin": v(lockin_serial), "kh": v(kh_serial)}
    with connect(settings, settings.write_user) as conn:
        cur = conn.cursor()
        if wiring is not None:
            cur.execute("SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' "
                        "AND table_name = 'llab_001' AND column_name = %s", (WIRING_COLUMN,))
            if cur.fetchone():
                cols.append(WIRING_COLUMN)
                vals.append("%(wiring)s::jsonb")
                params["wiring"] = json.dumps(wiring)
        cur.execute(f'INSERT INTO public.llab_001 ({", ".join(chr(34) + c + chr(34) for c in cols)}) '
                    f'VALUES ({", ".join(vals)})', params)
        conn.commit()
