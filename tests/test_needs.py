"""Tests for the needs of a lab.

These tests replace cluster.run and shutil.which with fakes. They do not need a running minikube.
"""
import json

import pytest

from backend import cluster, needs


def node(ready=True):
    return {"status": {"conditions": [{"type": "Ready", "status": "True" if ready else "False"}]}}


@pytest.fixture
def fake(monkeypatch):
    state = {"nodes": [node()], "addons": {"ingress": {"Status": "disabled"},
                                           "metrics-server": {"Status": "enabled"}},
             "calico": "calico-node-abc", "gateway": "True", "tools": {"helm"}, "calls": [], "fail": False}

    def run(args, timeout=cluster.TIMEOUT_S, stdin=None):
        state["calls"].append(args)
        if state["fail"]:
            return cluster.Result(False, "", "Unable to connect")
        if args[0] == "minikube":
            return cluster.Result(True, json.dumps(state["addons"]), "")
        if "gatewayclass" in args:
            return cluster.Result(True, state["gateway"], "")
        if "nodes" in args:
            return cluster.Result(True, json.dumps({"items": state["nodes"]}), "")
        return cluster.Result(True, state["calico"], "")

    monkeypatch.setattr(cluster, "run", run)
    monkeypatch.setattr(needs.shutil, "which", lambda n: f"/bin/{n}" if n in state["tools"] else None)
    return state


def met(result):
    return {k: v["met"] for k, v in result.items()}


def test_no_needs_reads_nothing(fake):
    assert needs.evaluate([], "minikube") == {}
    assert fake["calls"] == []


def test_tools(fake):
    out = needs.evaluate(["helm", "terraform"], "minikube")
    assert met(out) == {"helm": True, "terraform": False}
    assert "brew install hashicorp/tap/terraform" in out["terraform"]["help"]
    assert "PATH=" in out["terraform"]["help"]
    assert fake["calls"] == []


def test_addons(fake):
    out = needs.evaluate(["addon:ingress", "addon:metrics-server"], "minikube")
    assert met(out) == {"addon:ingress": False, "addon:metrics-server": True}
    assert "minikube addons enable ingress -p minikube" in out["addon:ingress"]["help"]
    assert len(fake["calls"]) == 1


def test_calico(fake):
    assert needs.evaluate(["cni:calico"], "minikube")["cni:calico"]["met"] is True
    fake["calico"] = ""
    out = needs.evaluate(["cni:calico"], "minikube")["cni:calico"]
    assert out["met"] is False and "--cni=calico" in out["help"]


def test_calico_read_pins_context(fake):
    needs.evaluate(["cni:calico"], "kt-multi")
    assert fake["calls"][0][:3] == ["kubectl", "--context", "kt-multi"]


def test_gateway(fake):
    assert needs.evaluate(["gateway"], "kt-multi")["gateway"]["met"] is True
    assert fake["calls"][0][:6] == ["kubectl", "--context", "kt-multi", "get", "gatewayclass", "quest"]
    fake["gateway"] = ""
    out = needs.evaluate(["gateway"], "minikube")["gateway"]
    assert out["met"] is False
    assert "envoyproxy/gateway/releases/download/v1.10.0/install.yaml" in out["help"]
    assert "kubectl apply -f install/gateway.yaml" in out["help"]


def test_nodes_counts_ready_only(fake):
    fake["nodes"] = [node(), node(), node(ready=False)]
    out = needs.evaluate(["nodes:2", "nodes:3"], "minikube")
    assert met(out) == {"nodes:2": True, "nodes:3": False}
    assert "kt-multi" in out["nodes:3"]["help"] and "has 2" in out["nodes:3"]["help"]
    assert len(fake["calls"]) == 1


def test_failed_reads_are_unmet(fake):
    fake["fail"] = True
    out = needs.evaluate(["addon:ingress", "cni:calico", "gateway", "nodes:1"], "minikube")
    assert not any(v["met"] for v in out.values())


def test_unmet_help(fake):
    out = needs.evaluate(["helm", "terraform"], "minikube")
    assert needs.unmet_help(out) == [out["terraform"]["help"]]
