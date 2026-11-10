"""Tests for the lab spec validator and the compare operators.

These tests do not need a running minikube.
"""
import copy

import pytest

from backend import labs


def spec(**over):
    s = {
        "id": "t1",
        "title": "Test lab",
        "namespace": "lab-t1",
        "setup": [],
        "checks": [{"id": "c", "say": "A check.", "why": "Because.", "get": "deployment/web",
                    "path": "{.status.readyReplicas}", "equals": "3"}],
        "hints": ["A hint."],
    }
    s.update(over)
    return s


def with_check(**over):
    s = spec()
    s["checks"][0].update(over)
    return s


def check(op, expected):
    return {"op": op, "expected": expected}


# compare

@pytest.mark.parametrize("actual,c,want", [
    ("3", check("equals", "3"), True),
    ("2", check("equals", "3"), False),
    (None, check("equals", "3"), False),
    ("nginx:1.27", check("matches", r"nginx:1\.2\d"), True),
    ("nginx:1.27-alpine", check("matches", r"nginx:1\.2\d"), False),
    ("3", check("atLeast", 3.0), True),
    ("2", check("atLeast", 3.0), False),
    ("2", check("atMost", 3.0), True),
    ("4", check("atMost", 3.0), False),
    ("abc", check("atLeast", 1.0), False),
    (None, check("atMost", 3.0), False),
    ("x", check("exists", True), True),
    ("", check("exists", True), False),
    (None, check("exists", True), False),
    (None, check("exists", False), True),
])
def test_compare(actual, c, want):
    assert labs.compare(actual, c) is want


# validate

def test_valid_spec_gives_normal_form():
    lab = labs.validate(spec(), "t1")
    assert lab["checks"][0]["op"] == "equals"
    assert lab["checks"][0]["expected"] == "3"


def test_scalars_change_to_kubectl_text():
    lab = labs.validate(with_check(equals=True), "t1")
    assert lab["checks"][0]["expected"] == "true"
    lab = labs.validate(with_check(equals=3), "t1")
    assert lab["checks"][0]["expected"] == "3"


@pytest.mark.parametrize("ns", ["default", "kube-system", "lab-", "lab-Bad", "lab-x-", "lab-" + "a" * 60])
def test_rejects_bad_namespace(ns):
    with pytest.raises(labs.LabError, match="namespace"):
        labs.validate(spec(namespace=ns), "t1")


@pytest.mark.parametrize("get", [
    "-n", "--all-namespaces", "deployment/-A", "deployment --all-namespaces",
    "deployment/web -o yaml", "Deployment", "deployment/web/x",
])
def test_rejects_flag_like_get(get):
    with pytest.raises(labs.LabError, match="get"):
        labs.validate(with_check(get=get), "t1")


@pytest.mark.parametrize("kind", ["Namespace", "ClusterRole", "ClusterRoleBinding", "Node",
                                  "PersistentVolume", "CustomResourceDefinition"])
def test_rejects_cluster_scoped_setup_kind(kind):
    doc = {"apiVersion": "v1", "kind": kind, "metadata": {"name": "x"}}
    with pytest.raises(labs.LabError, match="not permitted"):
        labs.validate(spec(setup=[doc]), "t1")


def test_rejects_setup_in_other_namespace():
    doc = {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": "x", "namespace": "default"}}
    with pytest.raises(labs.LabError, match="namespace"):
        labs.validate(spec(setup=[doc]), "t1")


def test_accepts_setup_in_lab_namespace():
    doc = {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": "x", "namespace": "lab-t1"}}
    labs.validate(spec(setup=[doc]), "t1")


def test_rejects_two_operators():
    with pytest.raises(labs.LabError, match="exactly one"):
        labs.validate(with_check(atLeast=1), "t1")


def test_rejects_no_operator():
    s = spec()
    del s["checks"][0]["equals"]
    with pytest.raises(labs.LabError, match="exactly one"):
        labs.validate(s, "t1")


def test_rejects_unknown_check_key():
    with pytest.raises(labs.LabError, match="unknown keys: atleast"):
        labs.validate(with_check(atleast=1), "t1")


def test_rejects_path_without_braces():
    with pytest.raises(labs.LabError, match="path"):
        labs.validate(with_check(path=".status.readyReplicas"), "t1")


def test_rejects_selector_with_named_get():
    with pytest.raises(labs.LabError, match="selector"):
        labs.validate(with_check(selector="app=web"), "t1")


def test_rejects_flag_like_selector():
    with pytest.raises(labs.LabError, match="selector"):
        labs.validate(with_check(get="pods", selector="-A"), "t1")


def test_rejects_id_not_equal_to_file_name():
    with pytest.raises(labs.LabError, match="file name"):
        labs.validate(spec(), "t2")


def test_rejects_duplicate_check_ids():
    s = spec()
    s["checks"].append(copy.deepcopy(s["checks"][0]))
    with pytest.raises(labs.LabError, match="same id"):
        labs.validate(s, "t1")


# load

def test_load_refuses_path_traversal():
    with pytest.raises(labs.LabNotFound):
        labs.load("../pyproject")


def test_load_unknown_id():
    with pytest.raises(labs.LabNotFound):
        labs.load("no-such-lab")


def test_all_lab_files_load():
    loaded = labs.load_all()
    assert loaded, "The labs/ directory has no lab files."
    assert all("setup" not in labs.summary(lab) for lab in loaded)


# why, needs, namespace, apiVersion

@pytest.mark.parametrize("why", [None, "", "   ", "two\nlines", "x" * 201, 3])
def test_rejects_bad_why(why):
    s = spec()
    if why is None:
        del s["checks"][0]["why"]
    else:
        s["checks"][0]["why"] = why
    with pytest.raises(labs.LabError, match="why"):
        labs.validate(s, "t1")


def test_summary_has_why_and_needs():
    out = labs.summary(labs.validate(spec(needs=["helm"]), "t1"))
    assert out["checks"][0]["why"] == "Because."
    assert out["needs"] == ["helm"]


def test_needs_default_empty():
    assert labs.validate(spec(), "t1")["needs"] == []


@pytest.mark.parametrize("needs", [
    "helm", ["kubectl"], ["addon:"], ["nodes:0"], ["nodes:x"], ["cni:flannel"], ["gateway:eg"], ["helm", "helm"], [3],
])
def test_rejects_bad_needs(needs):
    with pytest.raises(labs.LabError, match="need"):
        labs.validate(spec(needs=needs), "t1")


def test_accepts_all_need_kinds():
    tokens = ["helm", "terraform", "gateway", "addon:ingress", "addon:metrics-server", "cni:calico", "nodes:3"]
    assert labs.validate(spec(needs=tokens), "t1")["needs"] == tokens


def test_namespace_must_be_lab_id():
    with pytest.raises(labs.LabError, match="must be 'lab-t1'"):
        labs.validate(spec(namespace="lab-other"), "t1")


@pytest.mark.parametrize("api", ["batch/v1beta1", "autoscaling/v2beta2", "x.io/v1alpha1"])
def test_rejects_non_ga_api(api):
    doc = {"apiVersion": api, "kind": "CronJob", "metadata": {"name": "x"}}
    with pytest.raises(labs.LabError, match="GA API"):
        labs.validate(spec(setup=[doc]), "t1")


def test_helm_lab_needs_empty_setup():
    doc = {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": "x"}}
    with pytest.raises(labs.LabError, match="empty setup"):
        labs.validate(spec(needs=["helm"], setup=[doc]), "t1")
    assert labs.validate(spec(needs=["helm"]), "t1")["setup"] == []


def test_each_repo_check_has_why():
    for lab in labs.load_all():
        assert all(c["why"] for c in lab["checks"]), lab["id"]
