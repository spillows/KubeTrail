"""Tests for the lab routes and the error mapping.

These tests do not need a running minikube.
"""
import pytest
from fastapi.testclient import TestClient

from backend import cluster, labs
from backend.main import app

client = TestClient(app)


def raise_(exc):
    def f(*_args, **_kw):
        raise exc
    return f


def test_list_labs_has_no_setup():
    r = client.get("/api/labs")
    assert r.status_code == 200
    ids = [lab["id"] for lab in r.json()]
    assert "k2" in ids
    assert all("setup" not in lab for lab in r.json())


def test_get_lab():
    r = client.get("/api/labs/k2")
    assert r.status_code == 200
    assert r.json()["namespace"] == "lab-k2"


@pytest.mark.parametrize("method,url", [
    ("get", "/api/labs/no-such-lab"),
    ("post", "/api/labs/no-such-lab/setup"),
    ("post", "/api/labs/no-such-lab/verify"),
    ("post", "/api/labs/no-such-lab/reset"),
])
def test_unknown_lab_is_404(method, url):
    assert getattr(client, method)(url).status_code == 404


@pytest.mark.parametrize("exc,status", [
    (cluster.UnsafeContextError("not a minikube profile"), 409),
    (cluster.ClusterError("Unable to connect"), 502),
])
@pytest.mark.parametrize("action", ["setup", "verify", "reset"])
def test_cluster_errors_map_to_status(monkeypatch, action, exc, status):
    monkeypatch.setattr(cluster, "require_minikube", raise_(exc))
    r = client.post(f"/api/labs/k2/{action}")
    assert r.status_code == status
    assert r.json()["detail"] == str(exc)


def test_lab_error_is_400(monkeypatch):
    monkeypatch.setattr(labs, "setup", raise_(labs.LabError("did not make it")))
    r = client.post("/api/labs/k2/setup")
    assert r.status_code == 400
    assert r.json()["detail"] == "did not make it"


def test_needs_route(monkeypatch):
    from backend import needs
    monkeypatch.setattr(cluster, "require_minikube", lambda: "minikube")
    monkeypatch.setattr(labs, "load_all", lambda: [{"needs": ["helm"]}, {"needs": ["helm", "terraform"]}])
    seen = {}

    def evaluate(tokens, context):
        seen["args"] = (tokens, context)
        return {t: {"met": t == "helm", "help": ""} for t in tokens}

    monkeypatch.setattr(needs, "evaluate", evaluate)
    r = client.get("/api/needs")
    assert r.status_code == 200
    assert r.json()["terraform"]["met"] is False
    assert seen["args"][1] == "minikube"


def test_needs_route_unsafe_is_409(monkeypatch):
    monkeypatch.setattr(cluster, "require_minikube", raise_(cluster.UnsafeContextError("no")))
    assert client.get("/api/needs").status_code == 409


def test_setup_unmet_need_is_400(monkeypatch):
    from backend import needs
    lab = dict(labs.load("k2"), needs=["terraform"])
    calls = []
    monkeypatch.setattr(labs, "load", lambda *_a, **_k: lab)
    monkeypatch.setattr(cluster, "require_minikube", lambda: "minikube")
    monkeypatch.setattr(cluster, "run", lambda args, **_k: calls.append(args) or cluster.Result(True, "", ""))
    monkeypatch.setattr(needs.shutil, "which", lambda _n: None)
    r = client.post("/api/labs/k2/setup")
    assert r.status_code == 400
    assert "terraform" in r.json()["detail"]
    assert calls == []
