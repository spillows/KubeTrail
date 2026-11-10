"""Tests for setup and reset.

These tests replace cluster.run with a fake. They do not need a running minikube.
"""
import json

import pytest
import yaml

from backend import cluster, labs

LABEL = {"app.kubernetes.io/managed-by": "kubetrail"}
NOT_FOUND = cluster.Result(False, "", 'Error from server (NotFound): namespaces "lab-t1" not found')

LAB = {
    "id": "t1",
    "title": "Test lab",
    "namespace": "lab-t1",
    "setup": [{"apiVersion": "v1", "kind": "ConfigMap",
               "metadata": {"name": "cfg", "labels": {"tier": "web"}}, "data": {"a": "1"}}],
    "checks": [{"id": "c", "say": "A check.", "why": "Because.", "get": "configmap/cfg",
                "path": "{.data.a}", "equals": "1"}],
}


@pytest.fixture
def labs_dir(tmp_path):
    (tmp_path / "t1.yaml").write_text(yaml.safe_dump(LAB))
    return tmp_path


def ns_obj(labels=None, phase="Active"):
    obj = {"kind": "Namespace", "metadata": {"name": "lab-t1", "labels": labels or {}},
           "status": {"phase": phase}}
    return cluster.Result(True, json.dumps(obj), "")


@pytest.fixture
def fake(monkeypatch):
    """Record each call. Answer 'get namespace' from state['ns'] and 'kubectl config view'
    from state['kns']. Accept all other calls. The read-only 'config view' is not recorded."""
    state = {"ns": NOT_FOUND, "kns": "", "calls": []}

    def run(args, timeout=cluster.TIMEOUT_S, stdin=None):
        if args[1] == "config":
            return cluster.Result(True, state["kns"], "")
        state["calls"].append({"args": args, "stdin": stdin, "timeout": timeout})
        if args[3:5] == ["get", "namespace"]:
            return state["ns"]
        return cluster.Result(True, "", "")

    monkeypatch.setattr(cluster, "run", run)
    monkeypatch.setattr(cluster, "require_minikube", lambda: "minikube")
    return state


def verbs(state):
    return [c["args"][3] for c in state["calls"]]


# setup

def test_setup_new_namespace(fake, labs_dir):
    out = labs.setup("t1", labs_dir)
    assert verbs(fake) == ["get", "apply", "apply"]

    ns_apply, docs_apply = fake["calls"][1], fake["calls"][2]
    assert ns_apply["args"] == ["kubectl", "--context", "minikube", "apply", "-f", "-"]
    ns_doc = json.loads(ns_apply["stdin"])["items"][0]
    assert ns_doc["kind"] == "Namespace" and ns_doc["metadata"]["labels"] == LABEL

    assert docs_apply["args"] == ["kubectl", "--context", "minikube", "apply", "-n", "lab-t1", "-f", "-"]
    cm = json.loads(docs_apply["stdin"])["items"][0]
    assert cm["metadata"]["namespace"] == "lab-t1"
    assert cm["metadata"]["labels"] == {"tier": "web", **LABEL}

    assert out["next"] == "kubectl config set-context --current --namespace lab-t1"
    assert out["kubectlNamespace"] == "default"


def test_setup_does_not_change_lab_spec(fake, labs_dir):
    labs.setup("t1", labs_dir)
    assert "namespace" not in labs.load("t1", labs_dir)["setup"][0]["metadata"]


def test_setup_again_on_managed_namespace(fake, labs_dir):
    fake["ns"] = ns_obj(LABEL)
    labs.setup("t1", labs_dir)
    assert verbs(fake) == ["get", "apply", "apply"]


def test_setup_refuses_unmanaged_namespace(fake, labs_dir):
    fake["ns"] = ns_obj({"team": "prod"})
    with pytest.raises(labs.LabError, match="did not make it"):
        labs.setup("t1", labs_dir)
    assert "apply" not in verbs(fake)


def test_setup_refuses_terminating_namespace(fake, labs_dir):
    fake["ns"] = ns_obj(LABEL, phase="Terminating")
    with pytest.raises(labs.LabError, match="Wait"):
        labs.setup("t1", labs_dir)
    assert "apply" not in verbs(fake)


def test_setup_unsafe_context_runs_nothing(fake, labs_dir, monkeypatch):
    def refuse():
        raise cluster.UnsafeContextError("not a minikube profile")

    monkeypatch.setattr(cluster, "require_minikube", refuse)
    with pytest.raises(cluster.UnsafeContextError):
        labs.setup("t1", labs_dir)
    assert fake["calls"] == []


def test_setup_apply_error_raises(fake, labs_dir, monkeypatch):
    real = cluster.run

    def run(args, timeout=cluster.TIMEOUT_S, stdin=None):
        if args[3] == "apply":
            return cluster.Result(False, "", "admission webhook denied the request")
        return real(args, timeout, stdin)

    monkeypatch.setattr(cluster, "run", run)
    with pytest.raises(cluster.ClusterError, match="webhook"):
        labs.setup("t1", labs_dir)


# reset

def test_reset_deletes_managed_namespace(fake, labs_dir):
    fake["ns"] = ns_obj(LABEL)
    out = labs.reset("t1", labs_dir)
    assert out["deleted"] is True
    delete = fake["calls"][1]
    assert delete["args"] == ["kubectl", "--context", "minikube", "delete", "namespace", "lab-t1",
                              "--wait=true", "--timeout=120s"]
    assert delete["timeout"] > labs.RESET_TIMEOUT_S


def test_reset_gives_command_back_to_default(fake, labs_dir):
    fake["ns"] = ns_obj(LABEL)
    assert labs.reset("t1", labs_dir)["next"] is None
    fake["kns"] = "lab-t1"
    assert labs.reset("t1", labs_dir)["next"] == "kubectl config set-context --current --namespace default"


def test_reset_refuses_unmanaged_namespace(fake, labs_dir):
    fake["ns"] = ns_obj()
    with pytest.raises(labs.LabError, match="did not make it"):
        labs.reset("t1", labs_dir)
    assert "delete" not in verbs(fake)


def test_reset_absent_namespace_is_no_op(fake, labs_dir):
    out = labs.reset("t1", labs_dir)
    assert out["deleted"] is False
    assert verbs(fake) == ["get"]


def test_reset_unsafe_context_runs_nothing(fake, labs_dir, monkeypatch):
    def refuse():
        raise cluster.UnsafeContextError("not a minikube profile")

    monkeypatch.setattr(cluster, "require_minikube", refuse)
    with pytest.raises(cluster.UnsafeContextError):
        labs.reset("t1", labs_dir)
    assert fake["calls"] == []


def test_setup_refuses_unmet_need_before_namespace(fake, labs_dir, monkeypatch):
    spec = dict(LAB, needs=["terraform"])
    (labs_dir / "t1.yaml").write_text(yaml.safe_dump(spec))
    monkeypatch.setattr(labs.needs.shutil, "which", lambda n: None)
    with pytest.raises(labs.LabError, match="terraform"):
        labs.setup("t1", labs_dir)
    assert fake["calls"] == []
