"""The recorded tool output matches the names and labels that labs and needs use.

These tests do not need a running minikube. See tests/fixtures/README.md.
"""
import json
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def items(name):
    return json.loads((FIXTURES / name).read_text())["items"]


def select(objs, selector):
    want = dict(kv.split("=", 1) for kv in selector.split(","))
    return [o for o in objs if all(o["metadata"].get("labels", {}).get(k) == v for k, v in want.items())]


def test_helm_deployed_selector_finds_one_release():
    history = items("helm/release-history.json")
    found = select(history, "owner=helm,name=demo,status=deployed")
    assert [o["metadata"]["labels"]["version"] for o in found] == ["3"]
    assert found[0]["type"] == "helm.sh/release.v1"
    assert found[0]["metadata"]["name"] == "sh.helm.release.v1.demo.v3"


def test_helm_rollback_supersedes_old_revisions():
    history = items("helm/release-history.json")
    assert [o["metadata"]["labels"]["status"] for o in history] == ["superseded", "superseded", "deployed"]


def test_helm_failed_release_is_not_deployed():
    failed = items("helm/release-failed.json")
    assert select(failed, "owner=helm,status=failed")
    assert not select(failed, "owner=helm,status=deployed")


def test_helm_deployed_fixture_has_one_item():
    assert len(items("helm/release-deployed.json")) == 1


def test_terraform_state_secret_name_and_labels():
    s = json.loads((FIXTURES / "terraform/tfstate-secret.json").read_text())
    assert s["metadata"]["name"] == "tfstate-default-t2"
    assert s["metadata"]["labels"]["tfstate"] == "true"


def test_calico_pods_have_the_needs_label():
    assert select(items("calico/pods.json"), "k8s-app=calico-node")
