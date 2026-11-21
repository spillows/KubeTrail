"""Load and run the machine solution of a lab.

A machine solution (tests/e2e/solutions/<id>.yaml) is test data only. The UI
and the API never read it. The end-to-end test runs it between Start lab and
Check my work.

    id: k2
    dir: workspace/t2        # optional: workspace/<id> or charts/<name>
    steps:
      - run: [kubectl, run, hello, --image=nginx:1.27, -n, lab-k2]
      - apply: [{apiVersion: v1, kind: ConfigMap, ...}]
      - file: {name: main.tf, text: "..."}
      - copy: {from: charts/cache, to: charts/cache}
      - fails: [helm, upgrade, demo, ., --rollback-on-failure]

The runner adds the context to each run and fails step. It copies `dir` to a
temporary directory, and `file`, `copy`, `run` and `fails` steps use that
directory. A `file` name or a `copy` target is a relative path in it. A
`fails` step is a run step that must exit with an error. The runner never
writes to the real workspace/ or charts/.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SOLUTIONS = Path(__file__).resolve().parent / "solutions"
TOOLS = ("kubectl", "helm", "terraform")
STEP_KINDS = ("run", "fails", "apply", "file", "copy")
RUN_KINDS = ("run", "fails")
DIR_RE = re.compile(r"^(workspace/[a-z0-9-]+|charts/[a-z0-9-]+)$")
REL_RE = re.compile(r"^[A-Za-z0-9_-][A-Za-z0-9._-]*(/[A-Za-z0-9_-][A-Za-z0-9._-]*)*$")
TF_VAR_COMMANDS = {"plan", "apply", "destroy", "import", "refresh"}
TIMEOUT_S = 300


class SolutionError(Exception):
    pass


def _fail(lab_id: str, msg: str) -> SolutionError:
    return SolutionError(f"Solution '{lab_id}': {msg}")


def load(lab_id: str, solutions_dir: Path = SOLUTIONS) -> dict:
    path = solutions_dir / f"{lab_id}.yaml"
    if not path.is_file():
        raise _fail(lab_id, f"there is no file {path}.")
    doc = yaml.safe_load(path.read_text())
    if not isinstance(doc, dict) or doc.get("id") != lab_id:
        raise _fail(lab_id, "the file must be a mapping with the same id as its name.")
    unknown = set(doc) - {"id", "dir", "steps"}
    if unknown:
        raise _fail(lab_id, f"unknown keys: {', '.join(sorted(unknown))}.")
    if "dir" in doc and not (isinstance(doc["dir"], str) and DIR_RE.match(doc["dir"])):
        raise _fail(lab_id, "dir must be workspace/<id> or charts/<name>.")
    steps = doc.get("steps")
    if not isinstance(steps, list) or not steps:
        raise _fail(lab_id, "steps must be a list with one or more steps.")
    for i, step in enumerate(steps):
        where = f"steps[{i}]"
        if not isinstance(step, dict) or len(step) != 1 or next(iter(step)) not in STEP_KINDS:
            raise _fail(lab_id, f"{where} must have exactly one of {', '.join(STEP_KINDS)}.")
        kind, value = next(iter(step.items()))
        if kind in RUN_KINDS:
            if not (isinstance(value, list) and value and all(isinstance(a, str) for a in value)):
                raise _fail(lab_id, f"{where}.{kind} must be a list of strings.")
            if value[0] not in TOOLS:
                raise _fail(lab_id, f"{where}.{kind} must start with kubectl, helm or terraform.")
            if any(a in ("--context", "--kube-context") or a.startswith(("--context=", "--kube-context="))
                   for a in value):
                raise _fail(lab_id, f"{where}.{kind} must not set the context. The runner adds it.")
        elif kind == "apply":
            if not isinstance(value, list) or not value or not all(isinstance(m, dict) for m in value):
                raise _fail(lab_id, f"{where}.apply must be a list of manifests.")
            for m in value:
                api = m.get("apiVersion")
                if not isinstance(api, str) or "alpha" in api or "beta" in api:
                    raise _fail(lab_id, f"{where}.apply uses the apiVersion '{api}'. Use a GA API.")
        elif kind == "copy":
            if not (isinstance(value, dict) and set(value) == {"from", "to"}
                    and isinstance(value["from"], str) and DIR_RE.match(value["from"])
                    and isinstance(value["to"], str) and REL_RE.match(value["to"])):
                raise _fail(lab_id, f"{where}.copy must copy workspace/<id> or charts/<name> to a plain relative path.")
        else:
            if not (isinstance(value, dict) and set(value) == {"name", "text"}
                    and isinstance(value["name"], str) and isinstance(value["text"], str)
                    and REL_RE.match(value["name"])):
                raise _fail(lab_id, f"{where}.file must have a plain relative 'name' and a 'text'.")
    return doc


def with_context(args: list[str], context: str) -> list[str]:
    tool = args[0]
    if tool == "kubectl":
        return [tool, "--context", context, *args[1:]]
    if tool == "helm":
        return [*args, "--kube-context", context]
    if len(args) > 1 and args[1] in TF_VAR_COMMANDS:
        return [*args, "-var", f"kube_context={context}"]
    return list(args)


def execute(solution: dict, context: str) -> None:
    """Run each step. A failed step stops the solution with its error text."""
    lab_ns = f"lab-{solution['id']}"
    with tempfile.TemporaryDirectory(prefix=f"kt-{solution['id']}-") as tmp:
        cwd = Path(tmp)
        if "dir" in solution:
            src = ROOT / solution["dir"]
            if src.is_dir():
                shutil.copytree(src, cwd, dirs_exist_ok=True)
        for i, step in enumerate(solution["steps"]):
            kind, value = next(iter(step.items()))
            if kind == "file":
                target = cwd / value["name"]
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(value["text"].replace("{{context}}", context))
                continue
            if kind == "copy":
                shutil.copytree(ROOT / value["from"], cwd / value["to"], dirs_exist_ok=True)
                continue
            if kind in RUN_KINDS:
                args, stdin = with_context(value, context), None
            else:
                args = ["kubectl", "--context", context, "apply", "-n", lab_ns, "-f", "-"]
                stdin = yaml.safe_dump_all(value)
            r = subprocess.run(args, input=stdin, capture_output=True, text=True,
                               timeout=TIMEOUT_S, cwd=cwd)
            if kind == "fails":
                if r.returncode == 0:
                    raise SolutionError(f"Solution '{solution['id']}' steps[{i}] must fail, "
                                        f"but it passed: {' '.join(args)}")
                continue
            if r.returncode != 0:
                raise SolutionError(f"Solution '{solution['id']}' steps[{i}] failed: "
                                    f"{' '.join(args)}\n{r.stderr.strip() or r.stdout.strip()}")
