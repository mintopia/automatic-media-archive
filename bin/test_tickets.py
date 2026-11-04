#!/usr/bin/env python3
"""Runnable checks for tickets.py core logic. `python3 bin/test_tickets.py`."""
import importlib.util
import json
import os
import tempfile

_spec = importlib.util.spec_from_file_location(
    "tickets", os.path.join(os.path.dirname(__file__), "tickets.py"))
t = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(t)


def test_find_cycle():
    assert t.find_cycle({"a": ["b"], "b": ["c"], "c": []}) is None
    cyc = t.find_cycle({"a": ["b"], "b": ["c"], "c": ["a"]})
    assert cyc and cyc[0] == cyc[-1], cyc
    assert t.find_cycle({"a": ["a"]}) == ["a", "a"]
    # diamond is acyclic
    assert t.find_cycle({"a": ["b", "c"], "b": ["d"], "c": ["d"], "d": []}) is None


def test_body_text():
    assert t.body_text(["one", "two"]) == "one\ntwo"
    assert t.body_text("x") == "x"
    assert t.body_text(None) == ""


def _plan(d):
    f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    json.dump(d, f)
    f.close()
    return f.name


def _rejects(d, needle):
    try:
        t.load_plan(_plan(d))
    except SystemExit:
        return
    raise AssertionError(f"expected rejection ({needle}) but plan loaded")


def test_load_plan():
    good = {"epic": {"title": "E"},
            "tickets": [{"id": "a", "title": "A"},
                        {"id": "b", "title": "B", "blocked_by": ["a", "#9"]}]}
    epic, tickets = t.load_plan(_plan(good))
    assert epic["title"] == "E" and len(tickets) == 2

    _rejects({"epic": {}, "tickets": [{"id": "a", "title": "A"}]}, "no epic title")
    _rejects({"epic": {"title": "E"}, "tickets": []}, "no tickets")
    _rejects({"epic": {"title": "E"},
              "tickets": [{"id": "a", "title": "A"}, {"id": "a", "title": "B"}]}, "dup ids")
    _rejects({"epic": {"title": "E"}, "tickets": [{"id": "a"}]}, "missing title")
    _rejects({"epic": {"title": "E"},
              "tickets": [{"id": "a", "title": "A", "blocked_by": ["ghost"]}]}, "bad ref")
    _rejects({"epic": {"title": "E"},
              "tickets": [{"id": "a", "title": "A", "ready": "maybe"}]}, "bad ready")


if __name__ == "__main__":
    test_find_cycle()
    test_body_text()
    test_load_plan()
    print("ok")
