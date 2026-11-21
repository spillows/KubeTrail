"""Tests for the context guard.

The guard is the only barrier between the setup YAML of a lab and a real
cluster. These tests do not need a running minikube.
"""
import pytest

from backend import cluster


@pytest.fixture
def fake(monkeypatch):
    def set_(context, profiles):
        monkeypatch.setattr(cluster, "current_context", lambda: context)
        monkeypatch.setattr(cluster, "minikube_profiles", lambda: profiles)
    return set_


def test_allows_minikube_context(fake):
    fake("minikube", ["minikube"])
    assert cluster.require_minikube() == "minikube"


def test_allows_named_profile(fake):
    fake("multinode", ["minikube", "multinode"])
    assert cluster.require_minikube() == "multinode"


def test_refuses_other_context(fake):
    fake("gke_prod_us-central1_main", ["minikube"])
    with pytest.raises(cluster.UnsafeContextError, match="not a minikube profile"):
        cluster.require_minikube()


def test_refuses_no_context(fake):
    fake(None, ["minikube"])
    with pytest.raises(cluster.UnsafeContextError):
        cluster.require_minikube()


def test_refuses_when_minikube_missing(fake):
    fake("minikube", [])
    with pytest.raises(cluster.UnsafeContextError):
        cluster.require_minikube()


def test_status_reports_unsafe_without_raising(fake):
    fake("kind-kind", ["minikube"])
    s = cluster.status()
    assert s["safe"] is False and s["running"] is False and s["problems"]


@pytest.mark.parametrize("stdout", ["null", "[]"])
def test_status_without_node_state_is_a_problem(fake, monkeypatch, stdout):
    """minikube gives "null" and exit code 7 when it cannot reach the node."""
    fake("minikube", ["minikube"])
    monkeypatch.setattr(cluster, "run", lambda *a, **k: cluster.Result(False, stdout, ""))
    s = cluster.status()
    assert s["safe"] is True and s["running"] is False
    assert "minikube start -p minikube" in s["problems"][0]


def test_api_cluster_gives_200_for_null_status(fake, monkeypatch):
    from fastapi.testclient import TestClient
    from backend.main import app
    fake("minikube", ["minikube"])
    monkeypatch.setattr(cluster, "run", lambda *a, **k: cluster.Result(False, "null", ""))
    r = TestClient(app).get("/api/cluster")
    assert r.status_code == 200
    assert r.json()["problems"]


def test_status_pins_context_on_each_kubectl_call(fake, monkeypatch):
    fake("kt-multi", ["minikube", "kt-multi"])
    calls = []

    def run(args, **_kw):
        calls.append(args)
        if args[:2] == ["minikube", "status"]:
            return cluster.Result(True, '{"Host": "Running", "APIServer": "Running"}', "")
        return cluster.Result(True, "{}", "")

    monkeypatch.setattr(cluster, "run", run)
    cluster.status()
    kubectl = [a for a in calls if a[0] == "kubectl" and a[1] != "config"]
    assert len(kubectl) == 2 and all(a[1:3] == ["--context", "kt-multi"] for a in kubectl)
