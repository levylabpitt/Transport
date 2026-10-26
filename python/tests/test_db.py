import json
import os

import pytest

from expconfig import db


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self._rows = []

    def execute(self, sql, params=None):
        self.conn.log.append((sql, params))
        self._rows = self.conn.answer(sql, params)

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class FakeConn:
    def __init__(self, answers, has_wiring_table=False, stored=None):
        self.answers = answers
        self.has_wiring_table = has_wiring_table
        self.stored = dict(stored or {})  # sha256 -> wiring_id, as in public.wiring
        self.log = []
        self.committed = False
        self.user = None

    def answer(self, sql, params):
        if "to_regclass('public.wiring')" in sql:
            return [(self.has_wiring_table,)]
        if sql.startswith("INSERT INTO public.wiring"):
            if params["sha256"] in self.stored:
                return []  # ON CONFLICT DO NOTHING returns no row
            self.stored[params["sha256"]] = len(self.stored) + 1
            return [(self.stored[params["sha256"]],)]
        if sql.startswith("SELECT wiring_id FROM public.wiring"):
            return [(self.stored[params["sha256"]],)]
        for key, rows in self.answers.items():
            if key in sql:
                return rows
        return []

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.committed = True

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def connector(conn):
    def connect(settings, user):
        conn.user = user
        return conn
    return connect


def test_lookups_fill_the_rings():
    conn = FakeConn({
        "FROM public.users": [("Ana ",), ("Ben",)],
        "SELECT DISTINCT type": [("Cryo",), ("AFM",)],
        "SELECT type, name": [("Cryo", "PPMS 1"), ("Cryo", "MNK "), ("AFM", "Cypher")],
    })
    lk = db.lookups(db.DbSettings(), connect=connector(conn))
    assert lk.users == ["Ana", "Ben"]
    assert lk.station_types == ["Cryo", "AFM"]
    assert lk.stations_of("Cryo") == ["PPMS 1", "MNK"]
    assert set(lk.stations_of("")) == {"PPMS 1", "MNK", "Cypher"}
    assert conn.user == "llab_reader"
    users_sql, users_params = conn.log[0]
    assert "end_date IS NULL" in users_sql and users_params == (list(db.NON_EXPERIMENTER_ROLES),)


def test_lookups_report_errors_instead_of_raising():
    def broken(settings, user):
        raise OSError("no route to host")
    lk = db.lookups(db.DbSettings(), connect=broken)
    assert lk.users == [] and "no route" in lk.error


def test_record_measurement_uses_parameters_and_real_nulls():
    conn = FakeConn({})
    db.record_measurement(db.DbSettings(), user="Ana", station="PPMS 1", device="SA1.2026",
                          measurement="", lockin_serial="2674814", kh_serial="", connect=connector(conn))
    sql, params = conn.log[-1]
    assert sql.startswith("INSERT INTO public.llab_001")
    assert "Ana" not in sql  # values are parameters, never formatted into the SQL
    assert params["measurement"] is None and params["kh"] is None  # NULL, not the text 'NULL'
    assert conn.user == "llab_writer" and conn.committed
    assert params["wiring_id"] is None  # no wiring passed


def _record(conn, wiring):
    return db.record_measurement(db.DbSettings(), user="A", station="S", device="D", measurement="M",
                                 lockin_serial="L", kh_serial="K", wiring=wiring, connect=connector(conn))


def test_wiring_is_stored_once_and_linked_from_the_measurement():
    from expconfig.demo import demo_config
    doc = db.wiring_document(demo_config())
    conn = FakeConn({}, has_wiring_table=True)
    assert _record(conn, doc) == 1
    stored_sql, stored_params = next(e for e in conn.log if e[0].startswith("INSERT INTO public.wiring"))
    assert json.loads(stored_params["wiring"]) == doc
    assert stored_params["sha256"] == db.wiring_hash(doc)
    assert conn.log[-1][1]["wiring_id"] == 1
    # the same wiring again: no second copy, same id on the new measurement row
    assert _record(conn, json.loads(json.dumps(doc))) == 1
    assert len(conn.stored) == 1 and conn.log[-1][1]["wiring_id"] == 1
    # a different wiring gets a new id
    changed = demo_config()
    changed.channels[0].electrode = "99"
    assert _record(conn, db.wiring_document(changed)) == 2


def test_no_wiring_table_means_no_wiring_id():
    conn = FakeConn({}, has_wiring_table=False)
    assert _record(conn, {"x": 1}) is None
    assert conn.log[-1][0].startswith("INSERT INTO public.llab_001")
    assert conn.log[-1][1]["wiring_id"] is None


def test_hash_ignores_key_order():
    assert db.wiring_hash({"a": 1, "b": [1, 2]}) == db.wiring_hash({"b": [1, 2], "a": 1})


@pytest.mark.skipif(not os.environ.get("EXPCONFIG_LIVE_DB"), reason="set EXPCONFIG_LIVE_DB=1 to read the lab database")
def test_live_lookups_read_only():
    lk = db.lookups(db.DbSettings())
    assert not lk.error, lk.error
    assert lk.users and lk.station_types
