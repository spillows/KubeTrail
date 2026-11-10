"""Tests for read_value and verify.

These tests replace cluster.run with a fake. They do not need a running minikube.
"""
import pytest
import yaml

from backend import cluster, labs

LAB = {
    "id": "t1",
    "title": "Test lab",
    "namespace": "lab-t1",
    "checks": [
        {"id": "ready", "say": "Ready.", "why": "Because.", "get": "deployment/web",
         "path": "{.status.readyReplicas}", "equals": "3"},
        {"id": "pods", "say": "Pods run.", "why": "Because.", "get": "pods", "selector": "app=web",
         "path": "{.items[*].status.phase}", "equals": "Running"},
    ],
}


@pytest.fixture
def labs_dir(tmp_path):
    (tmp_path / "t1.yaml").write_text(yaml.safe_dump(LAB))
    return tmp_path


@pytest.fixture
def fake_run(monkeypatch):
    """Answer each kubectl get from a table keyed by the 'get' argument.

    A search in all namespaces has the key "-A kind". 'kubectl config view' has the key "config".
    """
    calls = []
    answers = {"config": ok("")}

    def run(args, timeout=cluster.TIMEOUT_S, stdin=None):
        calls.append(args)
        if args[1] == "config":
            return answers["config"]
        if "--all-namespaces" in args:
            return answers.get("-A " + args[4], ok(""))
        return answers[args[4]]

    monkeypatch.setattr(cluster, "run", run)
    monkeypatch.setattr(cluster, "require_minikube", lambda: "minikube")
    return calls, answers


def ok(out):
    return cluster.Result(True, out, "")


def lab():
    return labs.validate(LAB, "t1")


# read_value

def test_read_value_pins_context_and_namespace(fake_run):
    calls, answers = fake_run
    answers["pods"] = ok("Running Running")
    labs.read_value(lab(), lab()["checks"][1], "minikube")
    assert calls[0] == ["kubectl", "--context", "minikube", "get", "pods", "-n", "lab-t1",
                        "-o", "jsonpath={.items[*].status.phase}", "--selector=app=web"]


def test_read_value_not_found_is_none(fake_run):
    _, answers = fake_run
    answers["deployment/web"] = cluster.Result(
        False, "", 'Error from server (NotFound): deployments.apps "web" not found')
    assert labs.read_value(lab(), lab()["checks"][0], "minikube") is None


def test_read_value_missing_field_is_none(fake_run):
    _, answers = fake_run
    answers["deployment/web"] = ok("")
    assert labs.read_value(lab(), lab()["checks"][0], "minikube") is None


def test_read_value_other_error_raises(fake_run):
    _, answers = fake_run
    answers["deployment/web"] = cluster.Result(False, "", "Unable to connect to the server")
    with pytest.raises(cluster.ClusterError, match="Unable to connect"):
        labs.read_value(lab(), lab()["checks"][0], "minikube")


# check_values

@pytest.mark.parametrize("values,want", [
    (["Running", "Running"], True),
    (["Running", "Pending"], False),
    ([], False),
    (None, False),
])
def test_all_values_must_pass(values, want):
    assert labs.check_values(values, lab()["checks"][1]) is want


def test_empty_list_passes_exists_false():
    c = {"op": "exists", "expected": False}
    assert labs.check_values([], c) is True


# verify

def test_verify_all_pass(fake_run, labs_dir):
    _, answers = fake_run
    answers["deployment/web"] = ok("3")
    answers["pods"] = ok("Running Running Running")
    out = labs.verify("t1", labs_dir)
    assert out["passed"] is True
    assert [c["actual"] for c in out["checks"]] == ["3", "Running Running Running"]


def test_verify_reports_each_failure(fake_run, labs_dir):
    _, answers = fake_run
    answers["deployment/web"] = ok("2")
    answers["pods"] = ok("")
    out = labs.verify("t1", labs_dir)
    assert out["passed"] is False
    assert [(c["passed"], c["actual"]) for c in out["checks"]] == [(False, "2"), (False, None)]


def test_verify_finds_object_in_other_namespace(fake_run, labs_dir):
    calls, answers = fake_run
    answers["deployment/web"] = cluster.Result(
        False, "", 'Error from server (NotFound): deployments.apps "web" not found')
    answers["pods"] = ok("")
    answers["-A deployment"] = ok("default lab-t1 team-a")
    out = labs.verify("t1", labs_dir)
    assert out["elsewhere"] == [{"get": "deployment/web", "namespaces": ["default", "team-a"]}]
    assert out["kubectlNamespace"] == "default" and out["namespace"] == "lab-t1"
    search = next(a for a in calls if "--all-namespaces" in a)
    assert search == ["kubectl", "--context", "minikube", "get", "deployment", "--all-namespaces",
                      "--field-selector=metadata.name=web",
                      "-o", "jsonpath={.items[*].metadata.namespace}"]


def test_verify_searches_only_for_missing_objects(fake_run, labs_dir):
    calls, answers = fake_run
    answers["deployment/web"] = ok("2")
    answers["pods"] = ok("Pending")
    answers["config"] = ok("lab-t1")
    out = labs.verify("t1", labs_dir)
    assert out["elsewhere"] == [] and out["kubectlNamespace"] == "lab-t1"
    assert not any("--all-namespaces" in a for a in calls)


def test_verify_unsafe_context_runs_no_kubectl(fake_run, labs_dir, monkeypatch):
    calls, _ = fake_run

    def refuse():
        raise cluster.UnsafeContextError("not a minikube profile")

    monkeypatch.setattr(cluster, "require_minikube", refuse)
    with pytest.raises(cluster.UnsafeContextError):
        labs.verify("t1", labs_dir)
    assert calls == []


def test_verify_finds_selector_match_in_other_namespace(fake_run, labs_dir):
    calls, answers = fake_run
    answers["deployment/web"] = ok("3")
    answers["pods"] = ok("")
    answers["-A pods"] = ok("default default")
    out = labs.verify("t1", labs_dir)
    assert out["elsewhere"] == [{"get": "pods with labels app=web", "namespaces": ["default"]}]
    search = next(a for a in calls if "--all-namespaces" in a)
    assert "--selector=app=web" in search


def test_verify_failed_read_fails_one_check(fake_run, labs_dir):
    _, answers = fake_run
    answers["deployment/web"] = cluster.Result(False, "", "error: the server doesn't have a resource type\nmore")
    answers["pods"] = ok("Running")
    out = labs.verify("t1", labs_dir)
    assert out["passed"] is False
    first, second = out["checks"]
    assert first["passed"] is False and first["error"] == "error: the server doesn't have a resource type"
    assert second["passed"] is True and "error" not in second


def test_verify_returns_why(fake_run, labs_dir):
    _, answers = fake_run
    answers["deployment/web"] = ok("1")
    answers["pods"] = ok("Running")
    out = labs.verify("t1", labs_dir)
    assert all(c["why"] == "Because." for c in out["checks"])
