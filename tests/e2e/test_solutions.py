"""Each lab has a machine solution, and each solution is valid. This test runs in CI."""
import pytest

from backend import labs
import runner


def test_each_lab_has_a_solution():
    lab_ids = {lab["id"] for lab in labs.load_all()}
    solution_ids = {p.stem for p in runner.SOLUTIONS.glob("*.yaml")}
    assert lab_ids == solution_ids


@pytest.mark.parametrize("lab_id", sorted(p.stem for p in runner.SOLUTIONS.glob("*.yaml")))
def test_solution_is_valid(lab_id):
    assert runner.load(lab_id)["steps"]


@pytest.mark.parametrize("bad,match", [
    ({"id": "x", "steps": []}, "steps"),
    ({"id": "x", "steps": [{"run": ["bash", "-c", "true"]}]}, "kubectl, helm or terraform"),
    ({"id": "x", "steps": [{"run": ["kubectl", "--context", "prod", "get", "pods"]}]}, "context"),
    ({"id": "x", "steps": [{"run": ["kubectl"], "file": {"name": "a", "text": ""}}]}, "exactly one"),
    ({"id": "x", "steps": [{"apply": [{"apiVersion": "batch/v1beta1", "kind": "CronJob"}]}]}, "GA API"),
    ({"id": "x", "steps": [{"file": {"name": "../x", "text": ""}}]}, "plain"),
    ({"id": "x", "steps": [{"file": {"name": "templates/../../x", "text": ""}}]}, "plain"),
    ({"id": "x", "steps": [{"file": {"name": "/etc/x", "text": ""}}]}, "plain"),
    ({"id": "x", "steps": [{"fails": ["bash", "-c", "false"]}]}, "kubectl, helm or terraform"),
    ({"id": "x", "steps": [{"fails": ["helm", "test", "a", "--kube-context=prod"]}]}, "context"),
    ({"id": "x", "steps": [{"copy": {"from": "/etc", "to": "x"}}]}, "copy"),
    ({"id": "x", "steps": [{"copy": {"from": "charts/cache", "to": "../x"}}]}, "copy"),
    ({"id": "x", "dir": "/etc", "steps": [{"run": ["kubectl", "get", "pods"]}]}, "dir"),
    ({"id": "y", "steps": [{"run": ["kubectl", "get", "pods"]}]}, "same id"),
    ({"id": "x", "extra": 1, "steps": [{"run": ["kubectl", "get", "pods"]}]}, "unknown"),
])
def test_bad_solution_is_refused(tmp_path, bad, match):
    import yaml
    (tmp_path / "x.yaml").write_text(yaml.safe_dump(bad))
    with pytest.raises(runner.SolutionError, match=match):
        runner.load("x", tmp_path)


@pytest.mark.parametrize("args,want", [
    (["kubectl", "get", "pods"], ["kubectl", "--context", "mk", "get", "pods"]),
    (["helm", "install", "a", "b"], ["helm", "install", "a", "b", "--kube-context", "mk"]),
    (["terraform", "init"], ["terraform", "init"]),
    (["terraform", "apply", "-auto-approve"], ["terraform", "apply", "-auto-approve", "-var", "kube_context=mk"]),
])
def test_with_context(args, want):
    assert runner.with_context(args, "mk") == want


def test_subpath_file_copy_and_fails(monkeypatch):
    seen = []

    class R:
        def __init__(self, rc):
            self.returncode, self.stdout, self.stderr = rc, "", ""

    def fake_run(args, input=None, capture_output=True, text=True, timeout=None, cwd=None):
        from pathlib import Path
        seen.append((args, sorted(str(p.relative_to(cwd)) for p in Path(cwd).rglob("*"))))
        return R(1 if args[1] == "upgrade" else 0)

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    runner.execute({"id": "h0", "dir": "charts/demo", "steps": [
        {"file": {"name": "templates/extra.yaml", "text": "x"}},
        {"copy": {"from": "charts/cache", "to": "charts/cache"}},
        {"run": ["helm", "install", "demo", "."]},
        {"fails": ["helm", "upgrade", "demo", "."]},
    ]}, "mk")
    files = seen[0][1]
    assert "templates/extra.yaml" in files and "charts/cache/Chart.yaml" in files
    assert seen[1][0][-2:] == ["--kube-context", "mk"]
    with pytest.raises(runner.SolutionError, match="must fail"):
        runner.execute({"id": "h0", "steps": [{"fails": ["helm", "install", "demo", "."]}]}, "mk")


@pytest.mark.parametrize("lab_id", sorted(p.stem for p in runner.SOLUTIONS.glob("*.yaml")))
def test_terraform_lab_has_scaffold(lab_id):
    lab = labs.load(lab_id)
    if "terraform" not in lab["needs"]:
        return
    sol = runner.load(lab_id)
    assert sol.get("dir") == f"workspace/{lab_id}"
    for name in ("versions.tf", "providers.tf"):
        assert (runner.ROOT / sol["dir"] / name).is_file()
