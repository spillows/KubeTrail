"""Read-only wrappers for the minikube and kubectl CLIs.

This module also contains the context guard. Each call that changes the
cluster must go through this guard.

Each call uses a list of arguments, not a shell string. Each call also has a
timeout. Thus, a cluster that does not respond does not stop the server.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass

TIMEOUT_S = 15


class ClusterError(RuntimeError):
    """A CLI call failed, or the cluster is in a state that the app cannot use."""


class UnsafeContextError(ClusterError):
    """The kubectl context is not a minikube profile."""


@dataclass
class Result:
    ok: bool
    stdout: str
    stderr: str


def run(args: list[str], timeout: int = TIMEOUT_S, stdin: str | None = None) -> Result:
    """Run a CLI command. Send stdin to the command if stdin is not None."""
    if shutil.which(args[0]) is None:
        return Result(False, "", f"{args[0]} is not on the PATH.")
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout, input=stdin)
    except subprocess.TimeoutExpired:
        return Result(False, "", f"{' '.join(args)} did not complete in {timeout} seconds.")
    return Result(p.returncode == 0, p.stdout, p.stderr.strip())


def _json(args: list[str]):
    r = run(args)
    # When a profile is stopped, minikube gives a non-zero exit code. It also
    # writes valid JSON. Thus, read the JSON first. Examine the exit code after.
    try:
        return json.loads(r.stdout)
    except (json.JSONDecodeError, ValueError):
        if not r.ok:
            raise ClusterError(r.stderr or f"{args[0]} failed.")
        raise ClusterError(f"The output of {' '.join(args)} is not valid JSON.")


def current_context() -> str | None:
    r = run(["kubectl", "config", "current-context"])
    if not r.ok:
        return None
    return r.stdout.strip() or None


def minikube_profiles() -> list[str]:
    try:
        data = _json(["minikube", "profile", "list", "-o", "json"])
    except ClusterError:
        return []
    return [p["Name"] for p in data.get("valid", [])]


def require_minikube() -> str:
    """Return the active minikube profile.

    If kubectl points to a different cluster, raise UnsafeContextError.
    minikube gives each kubeconfig context the same name as its profile. Thus,
    the current context must be equal to a valid name from
    `minikube profile list`.
    """
    ctx = current_context()
    if ctx is None:
        raise UnsafeContextError("kubectl has no current context. `minikube stop` removes it. Run `minikube start`.")
    if ctx not in minikube_profiles():
        raise UnsafeContextError(
            f"The kubectl context is '{ctx}'. This context is not a minikube profile. "
            f"Run `kubectl config use-context minikube`, or use the name of your profile."
        )
    return ctx


def status() -> dict:
    """Return a snapshot of the local setup for the UI.

    This function does not raise errors. It adds each problem to the
    "problems" list. The page then tells the user how to correct the problem.
    """
    out: dict = {
        "tools": {t: shutil.which(t) is not None for t in ("minikube", "kubectl")},
        "context": current_context(),
        "profiles": minikube_profiles(),
        "safe": False,
        "running": False,
        "problems": [],
    }
    try:
        out["profile"] = require_minikube()
        out["safe"] = True
    except UnsafeContextError as e:
        out["problems"].append(str(e))
        return out

    try:
        st = _json(["minikube", "status", "-p", out["profile"], "-o", "json"])
    except ClusterError as e:
        out["problems"].append(str(e))
        return out
    # A profile with more than one node gives a list. The list has one item for each node.
    primary = st[0] if isinstance(st, list) and st else st
    # When minikube cannot reach the node, it writes "null" and exits with code 7.
    if not isinstance(primary, dict):
        out["problems"].append(
            f"minikube cannot read the state of the profile '{out['profile']}'. "
            f"Make sure that Docker Desktop runs, then run `minikube start -p {out['profile']}`."
        )
        return out
    out["host"] = primary.get("Host")
    out["apiserver"] = primary.get("APIServer")
    out["running"] = primary.get("APIServer") == "Running"
    if not out["running"]:
        out["problems"].append(f"The minikube profile '{out['profile']}' is not running. Run `minikube start`.")
        return out

    try:
        ver = _json(["kubectl", "--context", out["profile"], "version", "-o", "json"])
        out["kubernetesVersion"] = ver.get("serverVersion", {}).get("gitVersion")
    except ClusterError as e:
        out["problems"].append(str(e))

    try:
        nodes = _json(["kubectl", "--context", out["profile"], "get", "nodes", "-o", "json"])
        out["nodes"] = [
            {
                "name": n["metadata"]["name"],
                "ready": any(c["type"] == "Ready" and c["status"] == "True" for c in n["status"].get("conditions", [])),
                "controlPlane": "node-role.kubernetes.io/control-plane" in n["metadata"].get("labels", {}),
            }
            for n in nodes.get("items", [])
        ]
    except ClusterError as e:
        out["problems"].append(str(e))

    try:
        addons = _json(["minikube", "addons", "list", "-p", out["profile"], "-o", "json"])
        out["addons"] = sorted(k for k, v in addons.items() if v.get("Status") == "enabled")
    except ClusterError as e:
        out["problems"].append(str(e))

    return out
