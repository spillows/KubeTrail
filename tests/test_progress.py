"""Tests for progress.json and the progress routes.

The tests use a temporary progress.json. They do not need a running minikube.
"""
import json

import pytest
from fastapi.testclient import TestClient

from backend import labs, progress
from backend.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def tmp_progress(tmp_path, monkeypatch):
    path = tmp_path / "progress.json"
    monkeypatch.setattr(progress, "PATH", path)
    return path


# The module

def test_empty_without_file(tmp_progress):
    assert progress.load() == {"done": {}}
    assert not tmp_progress.exists()


def test_mark_writes_file(tmp_progress):
    out = progress.mark("k1")
    assert list(out["done"]) == ["k1"]
    on_disk = json.loads(tmp_progress.read_text())
    assert on_disk["version"] == progress.VERSION and "k1" in on_disk["done"]
    assert not tmp_progress.with_name("progress.json.tmp").exists()


def test_mark_keeps_first_time():
    first = progress.mark("k1")["done"]["k1"]
    progress.unmark("k9")
    assert progress.mark("k1")["done"]["k1"] == first


def test_unmark():
    progress.mark("k1")
    assert progress.unmark("k1") == {"done": {}}
    assert progress.unmark("k1") == {"done": {}}


@pytest.mark.parametrize("bad", ["", "../x", "-k1", "k 1", "a" * 65])
def test_rejects_bad_id(bad):
    with pytest.raises(progress.ProgressError):
        progress.mark(bad)


@pytest.mark.parametrize("text", ["{not json", "[]", '{"done": []}', '{"done": {"k1": 3}}'])
def test_bad_file_is_not_overwritten(tmp_progress, text):
    tmp_progress.write_text(text)
    with pytest.raises(progress.ProgressFileError):
        progress.mark("k1")
    assert tmp_progress.read_text() == text


# The routes

def test_put_and_delete_routes():
    assert client.get("/api/progress").json() == {"done": {}}
    r = client.put("/api/progress/k1")
    assert r.status_code == 200 and "k1" in r.json()["done"]
    r = client.delete("/api/progress/k1")
    assert r.status_code == 200 and r.json() == {"done": {}}


def test_lab_quest_cannot_be_marked_by_hand(tmp_progress):
    r = client.put("/api/progress/k2")
    assert r.status_code == 400
    assert "Check my work" in r.json()["detail"]
    assert not tmp_progress.exists()


def test_unknown_quest_cannot_be_marked(tmp_progress):
    r = client.put("/api/progress/no-such-quest")
    assert r.status_code == 400
    assert "No quest has the id 'no-such-quest'" in r.json()["detail"]
    assert not tmp_progress.exists()


def test_delete_of_unknown_quest_is_permitted():
    """A progress file can keep the id of a quest that the content removed."""
    r = client.delete("/api/progress/k9")
    assert r.status_code == 200 and r.json() == {"done": {}}


def test_bad_file_gives_500(tmp_progress):
    tmp_progress.write_text("{not json")
    r = client.get("/api/progress")
    assert r.status_code == 500
    assert "not valid JSON" in r.json()["detail"]


def test_passing_verify_records_lab(monkeypatch):
    monkeypatch.setattr(labs, "verify", lambda lab_id: {"id": lab_id, "passed": True, "checks": []})
    r = client.post("/api/labs/k2/verify")
    assert r.status_code == 200
    assert "k2" in r.json()["progress"]["done"]
    assert "k2" in progress.load()["done"]


def test_failing_verify_records_nothing(monkeypatch):
    monkeypatch.setattr(labs, "verify", lambda lab_id: {"id": lab_id, "passed": False, "checks": []})
    r = client.post("/api/labs/k2/verify")
    assert r.status_code == 200 and "progress" not in r.json()
    assert progress.load() == {"done": {}}
