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
    def __init__(self, answers, has_wiring=False):
        self.answers = answers
        self.has_wiring = has_wiring
        self.log = []
        self.committed = False
        self.user = None

    def answer(self, sql, params):
        if "information_schema.columns" in sql:
            return [(1,)] if self.has_wiring else []
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
    assert "wiring" not in sql  # no wiring passed


def test_wiring_is_written_only_if_the_column_exists():
    graph = {"schema": "levylab.topology/1", "nodes": [], "edges": []}
    without = FakeConn({}, has_wiring=False)
    db.record_measurement(db.DbSettings(), user="A", station="S", device="D", measurement="M",
                          lockin_serial="L", kh_serial="K", wiring=graph, connect=connector(without))
    assert '"wiring"' not in without.log[-1][0]
    with_col = FakeConn({}, has_wiring=True)
    db.record_measurement(db.DbSettings(), user="A", station="S", device="D", measurement="M",
                          lockin_serial="L", kh_serial="K", wiring=graph, connect=connector(with_col))
    sql, params = with_col.log[-1]
    assert '"wiring"' in sql and json.loads(params["wiring"]) == graph


@pytest.mark.skipif(not os.environ.get("EXPCONFIG_LIVE_DB"), reason="set EXPCONFIG_LIVE_DB=1 to read the lab database")
def test_live_lookups_read_only():
    lk = db.lookups(db.DbSettings())
    assert not lk.error, lk.error
    assert lk.users and lk.station_types
