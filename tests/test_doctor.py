"""Tests for scripts/doctor.py.

These tests replace cluster.run with a fake. They do not need a running minikube.
"""
import importlib.util
import io
import json
import sys
from pathlib import Path

import pytest

from backend import cluster

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "doctor.py"
_spec = importlib.util.spec_from_file_location("doctor", SCRIPT)
doctor = importlib.util.module_from_spec(_spec)
sys.modules["doctor"] = doctor
_spec.loader.exec_module(doctor)

PROFILES = {"invalid": [], "valid": [{"Name": "minikube", "Status": "OK", "Config": {"Driver": "docker"}}]}
STATUS = {"Name": "minikube", "Host": "Running", "Kubelet": "Running", "APIServer": "Running"}


def key(args):
    """A kubectl call with --context has the key ("kubectl@", verb)."""
    if args[:2] == ["kubectl", "--context"]:
        return ("kubectl@", args[3])
    return tuple(args[:2])


def ok(stdout):
    return cluster.Result(True, stdout, "")


def missing(tool):
    return cluster.Result(False, "", f"{tool} is not on the PATH.")


@pytest.fixture
def fake(monkeypatch):
    """Answer each CLI call from state['answers']. A tool not in 'answers' is not on the PATH."""
    state = {
        "context": "minikube",
        "system": "Darwin",
        "calls": [],
        "answers": {
            ("minikube", "version"): ok("v1.39.0\n"),
            ("kubectl", "version"): ok(json.dumps({"clientVersion": {"gitVersion": "v1.37.2"}})),
            ("minikube", "profile"): ok(json.dumps(PROFILES)),
            ("minikube", "status"): ok(json.dumps(STATUS)),
            ("docker", "info"): ok("29.9.2\n"),
            ("helm", "version"): ok("v4.0.0+g1234\n"),
            ("terraform", "version"): ok(json.dumps({"terraform_version": "1.13.0"})),
            ("kubectl@", "get"): ok("calico-node-abcde"),
            ("kubectl@", "version"): ok(json.dumps({"serverVersion": {"gitVersion": "v1.34.0"}})),
        },
    }

    def run(args, timeout=cluster.TIMEOUT_S, stdin=None):
        state["calls"].append(args)
        assert 0 < timeout <= cluster.TIMEOUT_S
        return state["answers"].get(key(args), missing(args[0]))

    monkeypatch.setattr(cluster, "run", run)
    monkeypatch.setattr(cluster, "current_context", lambda: state["context"])
    monkeypatch.setattr(doctor.platform, "system", lambda: state["system"])
    monkeypatch.setattr(doctor.platform, "mac_ver", lambda: ("15.1", ("", "", ""), "arm64"))
    return state


def results(state):
    out = io.StringIO()
    code = doctor.report(doctor.run_checks(), out)
    return code, out.getvalue()


def line(text, word):
    return next(row for row in text.splitlines() if word in row)


def test_all_ok(fake):
    code, text = results(fake)
    assert code == 0
    assert not any(row.startswith(("WARN", "FAIL")) for row in text.splitlines())
    assert "0 FAIL." in text
    assert line(text, "kubectl v").startswith("OK")
    assert "v1.37.2" in text and "v1.39.0" in text


def test_missing_tool_fails(fake):
    del fake["answers"][("kubectl", "version")]
    code, text = results(fake)
    assert code == 1
    assert line(text, "kubectl is not on the PATH").startswith("FAIL")
    assert "brew install kubectl" in text


def test_unsafe_context_fails(fake):
    fake["context"] = "gke_prod_us-central1_main"
    code, text = results(fake)
    assert code == 1
    assert line(text, "gke_prod_us-central1_main").startswith("FAIL")
    assert "kubectl config use-context minikube" in text


def test_macos_is_ok(fake):
    _, text = results(fake)
    assert line(text, "macOS 15.1").startswith("OK")


def test_other_platform_warns(fake):
    fake["system"] = "Linux"
    code, text = results(fake)
    assert code == 0
    assert line(text, "supports macOS only").startswith("WARN")
    assert "0 FAIL." in text


def test_new_tool_checks_do_not_fail_the_run(fake):
    del fake["answers"][("helm", "version")]
    del fake["answers"][("terraform", "version")]
    code, text = results(fake)
    assert code == 0
    assert {"helm", "terraform"} <= {args[0] for args in fake["calls"]}
    assert line(text, "helm is not installed").startswith("WARN")
    assert line(text, "terraform is not installed").startswith("WARN")
    assert "brew install hashicorp/tap/terraform" in text


def test_tools_ok(fake):
    _, text = results(fake)
    assert line(text, "helm v4").startswith("OK")
    assert line(text, "terraform 1.13.0").startswith("OK")


def test_no_calico_warns(fake):
    fake["answers"][("kubectl@", "get")] = ok("")
    code, text = results(fake)
    assert code == 0
    assert line(text, "no Calico").startswith("WARN")
    assert "--cni=calico" in text


def test_calico_and_version_pin_context(fake):
    results(fake)
    ctx = [a for a in fake["calls"] if a[0] == "kubectl" and a[1] == "--context"]
    assert len(ctx) == 2 and all(a[2] == "minikube" for a in ctx)


@pytest.mark.parametrize("version,level", [("v1.32.5", "WARN"), ("v1.33.0", "OK"), ("v2.0.0", "OK")])
def test_kubernetes_version(fake, version, level):
    fake["answers"][("kubectl@", "version")] = ok(json.dumps({"serverVersion": {"gitVersion": version}}))
    code, text = results(fake)
    assert code == 0
    assert line(text, version).startswith(level)


def test_unreadable_version_warns(fake):
    fake["answers"][("kubectl@", "version")] = missing("kubectl")
    _, text = results(fake)
    assert line(text, "cannot read the Kubernetes version").startswith("WARN")


def test_stopped_profile_fails(fake):
    fake["answers"][("minikube", "status")] = cluster.Result(
        False, json.dumps({**STATUS, "Host": "Stopped", "APIServer": "Stopped"}), "")
    code, text = results(fake)
    assert code == 1
    assert "minikube start -p minikube" in text


def test_driver_down_fails(fake):
    fake["answers"][("docker", "info")] = cluster.Result(False, "", "Cannot connect to the Docker daemon")
    code, text = results(fake)
    assert code == 1
    assert line(text, "docker driver").startswith("FAIL")


def test_runs_only_read_only_commands(fake):
    results(fake)
    verbs = {key(args) for args in fake["calls"]}
    assert verbs <= set(fake["answers"])
    assert not any("use-context" in args or "start" in args for args in fake["calls"])


def test_no_color_without_tty(fake, monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    _, text = results(fake)
    assert "\033[" not in text
