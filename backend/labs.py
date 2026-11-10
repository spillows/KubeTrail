"""Load, validate and compare lab specs.

Each lab is a YAML file in the labs/ directory. The file name is the lab id.
The validator is strict because lab data goes into kubectl commands. A lab
cannot add kubectl flags, change cluster-scoped objects or use a namespace
that is not its own.
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import yaml

from backend import cluster, needs

LABS_DIR = Path(__file__).resolve().parent.parent / "labs"

ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
# A DNS label (max 63 characters) that starts with "lab-".
NAMESPACE_RE = re.compile(r"^lab-(?:[a-z0-9-]{0,58})?[a-z0-9]$")
# "kind" or "kind/name". The first character cannot be "-". Thus, the value
# cannot be a kubectl flag.
GET_RE = re.compile(r"^[a-z][a-z0-9.]*(?:/[a-z0-9](?:[-a-z0-9.]{0,251}[a-z0-9])?)?$")
SELECTOR_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/=,!() -]{0,254}$")

# The app puts this label on each namespace that it makes. Setup and reset
# refuse a namespace that does not have this label.
MANAGED_BY = ("app.kubernetes.io/managed-by", "kubetrail")
RESET_TIMEOUT_S = 120

OPERATORS = ("equals", "matches", "atLeast", "atMost", "exists")
LAB_KEYS = {"id", "title", "namespace", "needs", "setup", "checks", "hints"}
CHECK_KEYS = {"id", "say", "why", "get", "path", "selector", *OPERATORS}
WHY_MAX = 200

# Setup manifests can use only these kinds. All of them are namespaced.
SETUP_KINDS = frozenset({
    "ConfigMap", "CronJob", "DaemonSet", "Deployment", "HorizontalPodAutoscaler",
    "Ingress", "Job", "LimitRange", "NetworkPolicy", "PersistentVolumeClaim",
    "Pod", "PodDisruptionBudget", "ReplicaSet", "ResourceQuota", "Role",
    "RoleBinding", "Secret", "Service", "ServiceAccount", "StatefulSet",
})


class LabError(ValueError):
    """A lab spec is not valid, or a lab operation cannot continue."""


class LabNotFound(LabError):
    """No lab file has this id."""


def _fail(lab_id: str, msg: str) -> LabError:
    return LabError(f"Lab '{lab_id}': {msg}")


def _scalar(lab_id: str, where: str, v) -> str:
    """Change a YAML scalar to the text that kubectl jsonpath shows."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float, str)):
        return str(v)
    raise _fail(lab_id, f"{where} must be a text or a number.")


def _number(lab_id: str, where: str, v) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise _fail(lab_id, f"{where} must be a number.")
    return float(v)


def _check_manifest(lab_id: str, ns: str, i: int, doc) -> None:
    where = f"setup[{i}]"
    if not isinstance(doc, dict):
        raise _fail(lab_id, f"{where} must be a mapping.")
    if not isinstance(doc.get("apiVersion"), str):
        raise _fail(lab_id, f"{where} has no apiVersion.")
    # An alpha or beta API can go away in a minor release. Labs use GA APIs only.
    if "alpha" in doc["apiVersion"] or "beta" in doc["apiVersion"]:
        raise _fail(lab_id, f"{where} uses the apiVersion '{doc['apiVersion']}'. Use a GA API.")
    kind = doc.get("kind")
    if kind not in SETUP_KINDS:
        raise _fail(lab_id, f"{where} has the kind '{kind}'. This kind is not permitted in setup.")
    meta = doc.get("metadata")
    if not isinstance(meta, dict) or not isinstance(meta.get("name"), str):
        raise _fail(lab_id, f"{where} has no metadata.name.")
    if meta.get("namespace", ns) != ns:
        raise _fail(lab_id, f"{where} uses the namespace '{meta['namespace']}'. Use '{ns}' or no namespace.")


def _check_check(lab_id: str, i: int, c) -> dict:
    where = f"checks[{i}]"
    if not isinstance(c, dict):
        raise _fail(lab_id, f"{where} must be a mapping.")
    extra = set(c) - CHECK_KEYS
    if extra:
        raise _fail(lab_id, f"{where} has unknown keys: {', '.join(sorted(extra))}.")
    for key in ("id", "say", "get", "path"):
        if not isinstance(c.get(key), str) or not c[key]:
            raise _fail(lab_id, f"{where} must have a text value for '{key}'.")
    why = c.get("why")
    if not isinstance(why, str) or not why.strip() or "\n" in why.strip() or len(why) > WHY_MAX:
        raise _fail(lab_id, f"{where} must have a 'why': one line of text, {WHY_MAX} characters or fewer.")
    if not GET_RE.match(c["get"]):
        raise _fail(lab_id, f"{where}.get '{c['get']}' is not 'kind' or 'kind/name'.")
    path = c["path"]
    if not (path.startswith("{") and path.endswith("}")) or "\n" in path:
        raise _fail(lab_id, f"{where}.path must be one jsonpath expression in braces.")
    if "selector" in c:
        if "/" in c["get"]:
            raise _fail(lab_id, f"{where} has a selector. A selector needs 'get' without a name.")
        if not isinstance(c["selector"], str) or not SELECTOR_RE.match(c["selector"]):
            raise _fail(lab_id, f"{where}.selector is not a valid label selector.")

    ops = [op for op in OPERATORS if op in c]
    if len(ops) != 1:
        raise _fail(lab_id, f"{where} must have exactly one of: {', '.join(OPERATORS)}.")
    op = ops[0]
    out = {k: c[k] for k in ("id", "say", "get", "path", "selector") if k in c}
    out["why"] = why.strip()
    out["op"] = op
    if op == "equals":
        out["expected"] = _scalar(lab_id, f"{where}.equals", c[op])
    elif op == "matches":
        try:
            re.compile(_scalar(lab_id, f"{where}.matches", c[op]))
        except re.error as e:
            raise _fail(lab_id, f"{where}.matches is not a valid regex: {e}.") from None
        out["expected"] = str(c[op])
    elif op in ("atLeast", "atMost"):
        out["expected"] = _number(lab_id, f"{where}.{op}", c[op])
    else:
        if not isinstance(c[op], bool):
            raise _fail(lab_id, f"{where}.exists must be true or false.")
        out["expected"] = c[op]
    return out


def validate(spec, lab_id: str) -> dict:
    """Validate a parsed lab spec. Return a normal form of the spec.

    In the normal form, each check has the keys "op" and "expected" in place
    of the operator key. Raise LabError if the spec is not valid.
    """
    if not isinstance(spec, dict):
        raise _fail(lab_id, "the file must contain a mapping.")
    extra = set(spec) - LAB_KEYS
    if extra:
        raise _fail(lab_id, f"unknown keys: {', '.join(sorted(extra))}.")
    if spec.get("id") != lab_id:
        raise _fail(lab_id, f"the id must be equal to the file name '{lab_id}'.")
    if not isinstance(spec.get("title"), str) or not spec["title"]:
        raise _fail(lab_id, "the lab must have a title.")
    ns = spec.get("namespace")
    if not isinstance(ns, str) or not NAMESPACE_RE.match(ns):
        raise _fail(lab_id, f"the namespace '{ns}' must be a DNS label that starts with 'lab-'.")
    if ns != f"lab-{lab_id}":
        raise _fail(lab_id, f"the namespace '{ns}' must be 'lab-{lab_id}'.")
    try:
        lab_needs = needs.validate(spec.get("needs"))
    except ValueError as e:
        raise _fail(lab_id, str(e)) from None

    setup = spec.get("setup") or []
    if not isinstance(setup, list):
        raise _fail(lab_id, "setup must be a list of manifests.")
    for i, doc in enumerate(setup):
        _check_manifest(lab_id, ns, i, doc)
    # Helm refuses to install over an object with a different managed-by
    # label, and setup stamps each object with the label of the app.
    if setup and "helm" in lab_needs:
        raise _fail(lab_id, "a lab that needs helm must have an empty setup.")

    raw_checks = spec.get("checks")
    if not isinstance(raw_checks, list) or not raw_checks:
        raise _fail(lab_id, "the lab must have one or more checks.")
    checks = [_check_check(lab_id, i, c) for i, c in enumerate(raw_checks)]
    ids = [c["id"] for c in checks]
    if len(set(ids)) != len(ids):
        raise _fail(lab_id, "two or more checks have the same id.")

    hints = spec.get("hints") or []
    if not isinstance(hints, list) or not all(isinstance(h, str) for h in hints):
        raise _fail(lab_id, "hints must be a list of texts.")

    return {"id": lab_id, "title": spec["title"], "namespace": ns, "needs": lab_needs,
            "setup": setup, "checks": checks, "hints": hints}


def exists(lab_id: str, labs_dir: Path = LABS_DIR) -> bool:
    """Return True if a lab file has this id. Do not validate the file."""
    return bool(ID_RE.match(lab_id)) and (labs_dir / f"{lab_id}.yaml").is_file()


def load(lab_id: str, labs_dir: Path = LABS_DIR) -> dict:
    """Read and validate one lab. Raise LabNotFound if no file has this id."""
    # Examine the id before it goes into a path. Thus, "../x" cannot read other files.
    if not ID_RE.match(lab_id):
        raise LabNotFound(f"No lab has the id '{lab_id}'.")
    path = labs_dir / f"{lab_id}.yaml"
    if not path.is_file():
        raise LabNotFound(f"No lab has the id '{lab_id}'.")
    try:
        spec = yaml.safe_load(path.read_text())
    except yaml.YAMLError as e:
        raise _fail(lab_id, f"the file is not valid YAML: {e}") from None
    return validate(spec, lab_id)


def load_all(labs_dir: Path = LABS_DIR) -> list[dict]:
    """Read and validate all labs, sorted by id."""
    return [load(p.stem, labs_dir) for p in sorted(labs_dir.glob("*.yaml"))]


def summary(lab: dict) -> dict:
    """Return the lab data for the UI. The setup manifests are not included."""
    return {
        "id": lab["id"],
        "title": lab["title"],
        "namespace": lab["namespace"],
        "needs": lab["needs"],
        "checks": [{"id": c["id"], "say": c["say"], "why": c["why"]} for c in lab["checks"]],
        "hints": lab["hints"],
    }


def compare(actual: str | None, check: dict) -> bool:
    """Compare a value from the cluster with the expected value of a check.

    The value None means that the object or the field does not exist.
    """
    op, expected = check["op"], check["expected"]
    if op == "exists":
        return (actual is not None and actual != "") == expected
    if actual is None:
        return False
    if op == "equals":
        return actual == expected
    if op == "matches":
        return re.fullmatch(expected, actual) is not None
    try:
        n = float(actual)
    except ValueError:
        return False
    return n >= expected if op == "atLeast" else n <= expected


def check_values(values: list[str] | None, check: dict) -> bool:
    """Compare all values from the cluster with the expected value of a check.

    The check passes only if each value passes. An empty list has the same
    meaning as None: the object or the field does not exist.
    """
    if not values:
        return compare(None, check)
    return all(compare(v, check) for v in values)


def read_value(lab: dict, check: dict, context: str) -> list[str] | None:
    """Read the value of a check from the cluster.

    The command always uses the lab namespace and the context that the guard
    accepted. Thus, a context change during a verify cannot send the command
    to a different cluster.

    For "kind/name", the result has one value. It is None if the object or the
    field does not exist. For "kind" (with or without a selector), the result
    has one value for each word that kubectl shows.
    """
    args = ["kubectl", "--context", context, "get", check["get"],
            "-n", lab["namespace"], "-o", f"jsonpath={check['path']}"]
    if "selector" in check:
        # One argument with "=". Thus, kubectl cannot read the value as a flag.
        args.append(f"--selector={check['selector']}")
    r = cluster.run(args)
    if not r.ok:
        if "(NotFound)" in r.stderr:
            return None
        raise cluster.ClusterError(r.stderr or "kubectl get failed.")
    if "/" in check["get"]:
        return [r.stdout] if r.stdout != "" else None
    return r.stdout.split()


def kubectl_namespace(context: str) -> str:
    """Return the default namespace of the context: the namespace that the user's kubectl commands use."""
    r = cluster.run(["kubectl", "config", "view", "--minify", f"--context={context}",
                     "-o", "jsonpath={..namespace}"])
    return (r.stdout.strip() if r.ok else "") or "default"


def _target(check: dict) -> str | None:
    """Return the text that names the object of a check, or None if the check names no object."""
    if "/" in check["get"]:
        return check["get"]
    if "selector" in check:
        return f"{check['get']} with labels {check['selector']}"
    return None


def find_elsewhere(lab: dict, check: dict, context: str) -> list[str]:
    """Return the other namespaces that have the object of the check. This is read-only.

    For "kind/name", search by name. For a check with a selector, search by
    the selector. Otherwise, return an empty list.
    """
    if "/" in check["get"]:
        kind, name = check["get"].split("/", 1)
        match = f"--field-selector=metadata.name={name}"
    elif "selector" in check:
        kind, match = check["get"], f"--selector={check['selector']}"
    else:
        return []
    r = cluster.run(["kubectl", "--context", context, "get", kind, "--all-namespaces", match,
                     "-o", "jsonpath={.items[*].metadata.namespace}"])
    if not r.ok:
        return []
    return sorted({ns for ns in r.stdout.split() if ns != lab["namespace"]})


def verify(lab_id: str, labs_dir: Path = LABS_DIR) -> dict:
    """Run all checks of a lab against the cluster. Return the result of each check.

    If a named object is not in the lab namespace, also return the other
    namespaces that have it ("elsewhere"). The usual cause is a kubectl
    command that ran in the "default" namespace.

    Raise UnsafeContextError before any kubectl get if the context is not minikube.
    """
    lab = load(lab_id, labs_dir)
    context = cluster.require_minikube()
    results = []
    missing: dict[str, dict] = {}
    for c in lab["checks"]:
        # A failed read fails this check only. The other checks still run.
        try:
            values = read_value(lab, c, context)
        except cluster.UnsafeContextError:
            raise
        except cluster.ClusterError as e:
            results.append({"id": c["id"], "say": c["say"], "why": c["why"], "passed": False,
                            "actual": None, "error": (str(e).strip().splitlines() or ["kubectl get failed."])[0]})
            continue
        target = _target(c)
        if not values and target is not None and target not in missing:
            missing[target] = c
        results.append({
            "id": c["id"],
            "say": c["say"],
            "why": c["why"],
            "passed": check_values(values, c),
            "actual": " ".join(values) if values else None,
        })
    elsewhere = []
    for target, c in missing.items():
        found = find_elsewhere(lab, c, context)
        if found:
            elsewhere.append({"get": target, "namespaces": found})
    return {"id": lab_id, "passed": all(r["passed"] for r in results), "checks": results,
            "namespace": lab["namespace"], "kubectlNamespace": kubectl_namespace(context),
            "elsewhere": elsewhere}


def _namespace(context: str, ns: str) -> dict | None:
    """Return the Namespace object, or None if it does not exist."""
    r = cluster.run(["kubectl", "--context", context, "get", "namespace", ns, "-o", "json"])
    if not r.ok:
        if "(NotFound)" in r.stderr:
            return None
        raise cluster.ClusterError(r.stderr or "kubectl get namespace failed.")
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        raise cluster.ClusterError("The output of kubectl get namespace is not valid JSON.") from None


def _require_managed(obj: dict, ns: str) -> None:
    key, value = MANAGED_BY
    if obj.get("metadata", {}).get("labels", {}).get(key) != value:
        raise LabError(
            f"The namespace '{ns}' exists, but KubeTrail did not make it. "
            f"The app does not change it. Delete it yourself or use a different cluster."
        )


def _apply(context: str, docs: list[dict], ns: str | None = None) -> None:
    args = ["kubectl", "--context", context, "apply"]
    if ns is not None:
        args += ["-n", ns]
    body = json.dumps({"apiVersion": "v1", "kind": "List", "items": docs})
    r = cluster.run(args + ["-f", "-"], stdin=body)
    if not r.ok:
        raise cluster.ClusterError(r.stderr or "kubectl apply failed.")


def setup(lab_id: str, labs_dir: Path = LABS_DIR) -> dict:
    """Make the lab namespace and apply the setup manifests of the lab.

    This function does not change the kubectl context of the user. It returns
    the command that sets the lab namespace as the default namespace.
    """
    lab = load(lab_id, labs_dir)
    context = cluster.require_minikube()
    ns = lab["namespace"]
    key, value = MANAGED_BY

    # Refuse before the namespace exists.
    unmet = needs.unmet_help(needs.evaluate(lab["needs"], context))
    if unmet:
        raise LabError(" ".join(unmet))

    existing = _namespace(context, ns)
    if existing is not None:
        _require_managed(existing, ns)
        if existing.get("status", {}).get("phase") == "Terminating":
            raise LabError(f"Kubernetes deletes the namespace '{ns}' now. Wait, then try again.")

    _apply(context, [{"apiVersion": "v1", "kind": "Namespace",
                      "metadata": {"name": ns, "labels": {key: value}}}])

    docs = copy.deepcopy(lab["setup"])
    for doc in docs:
        meta = doc["metadata"]
        meta["namespace"] = ns
        meta.setdefault("labels", {})[key] = value
    if docs:
        _apply(context, docs, ns)

    return {"id": lab_id, "namespace": ns, "kubectlNamespace": kubectl_namespace(context),
            "next": f"kubectl config set-context --current --namespace {ns}"}


def reset(lab_id: str, labs_dir: Path = LABS_DIR) -> dict:
    """Delete the lab namespace and all objects in it.

    Delete the namespace only if it has the managed-by label. Wait until
    Kubernetes completes the delete, for a maximum of RESET_TIMEOUT_S seconds.
    """
    lab = load(lab_id, labs_dir)
    context = cluster.require_minikube()
    ns = lab["namespace"]

    # The app does not change the user's default namespace. If it is the lab
    # namespace, return the command that goes back to "default".
    back = "kubectl config set-context --current --namespace default"
    next_cmd = back if kubectl_namespace(context) == ns else None

    existing = _namespace(context, ns)
    if existing is None:
        return {"id": lab_id, "namespace": ns, "deleted": False, "next": next_cmd}
    _require_managed(existing, ns)

    r = cluster.run(
        ["kubectl", "--context", context, "delete", "namespace", ns,
         "--wait=true", f"--timeout={RESET_TIMEOUT_S}s"],
        timeout=RESET_TIMEOUT_S + 10,
    )
    if not r.ok:
        raise cluster.ClusterError(r.stderr or "kubectl delete namespace failed.")
    return {"id": lab_id, "namespace": ns, "deleted": True, "next": next_cmd}
