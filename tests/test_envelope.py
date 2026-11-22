"""Byte-level contract for the reply envelopes (key order and omission rules)."""

import json

from callback.models.envelope import err, ok


def test_ok_minimal():
    assert json.dumps(ok("s")) == json.dumps({"session_id": "s", "status": "ok"})


def test_ok_drops_falsy_optionals_but_keeps_empty_session_id():
    actual = ok("", next_action="", data={}, workflow={})

    assert json.dumps(actual) == json.dumps({"session_id": "", "status": "ok"})


def test_ok_keeps_nested_nulls_and_key_order():
    actual = ok("s", "next", {"a": None, "b": {"c": None}}, {"phase": "p"})

    expected = {
        "session_id": "s",
        "status": "ok",
        "next_action": "next",
        "data": {"a": None, "b": {"c": None}},
        "workflow": {"phase": "p"},
    }
    assert json.dumps(actual) == json.dumps(expected)


def test_err_minimal():
    actual = err("st", "c", "m")

    expected = {
        "status": "error",
        "error": {"stage": "st", "code": "c", "message": "m", "retriable": False},
    }
    assert json.dumps(actual) == json.dumps(expected)


def test_err_full_keeps_order_empty_session_id_and_explicit_nulls():
    actual = err("st", "c", "m", "", True, {"pdf_path": None}, "report_and_wait")

    expected = {
        "status": "error",
        "error": {
            "stage": "st",
            "code": "c",
            "message": "m",
            "retriable": True,
            "host_action": "report_and_wait",
        },
        "data": {"pdf_path": None},
        "session_id": "",
    }
    assert json.dumps(actual) == json.dumps(expected)


def test_err_keeps_empty_data_dict():
    actual = err("st", "c", "m", data={})

    expected = {
        "status": "error",
        "error": {"stage": "st", "code": "c", "message": "m", "retriable": False},
        "data": {},
    }
    assert json.dumps(actual) == json.dumps(expected)
