"""Examine the local setup for KubeTrail.

Run this script from the repository root:

    .venv/bin/python scripts/doctor.py

./run.sh runs this script before it starts the server.

The script gives each check a result: OK, WARN or FAIL. Each WARN and FAIL
result has one line of help. The exit code is 1 if a required check fails.
Otherwise, the exit code is 0.

The script is read-only. It does not change the cluster or the kubectl
context. Each CLI call has a timeout.
"""
from __future__ import annotations

import importlib.util
import json
import os
import platform
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# Put the repository root on sys.path. Thus, "backend" is importable without PYTHONPATH.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend import cluster  # noqa: E402

MIN_PYTHON = (3, 11)
# The newest GA feature in the catalog: native sidecar containers (1.33).
MIN_KUBERNETES = (1, 33)
PACKAGES = ("fastapi", "uvicorn", "yaml")
TIMEOUT_S = 10
CONTAINER_DRIVERS = {
    "docker": ["docker", "info", "--format", "{{.ServerVersion}}"],
    "podman": ["podman", "info", "--format", "{{.Version.Version}}"],
}

OK, WARN, FAIL = "OK", "WARN", "FAIL"


@dataclass
class Check:
    level: str
    message: str
    help: str = ""
    required: bool = True


def _first_line(text: str) -> str:
    return next((line.strip() for line in text.splitlines() if line.strip()), "")


def _json(text: str):
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None


# Required checks

def check_python(version: tuple = sys.version_info[:3]) -> Check:
    found = ".".join(str(v) for v in version)
    need = ".".join(str(v) for v in MIN_PYTHON)
    if tuple(version[:2]) >= MIN_PYTHON:
        return Check(OK, f"Python {found}")
    return Check(FAIL, f"Python {found} is too old. KubeTrail needs Python {need} or later.",
                 f"Run `brew install python@3.12`, delete .venv, then run ./run.sh again.")


def check_minikube() -> Check:
    r = cluster.run(["minikube", "version", "--short"], timeout=TIMEOUT_S)
    if not r.ok:
        return Check(FAIL, f"minikube: {r.stderr or 'the version command failed.'}",
                     "Run `brew install minikube`.")
    return Check(OK, f"minikube {_first_line(r.stdout)}")


def check_kubectl() -> Check:
    r = cluster.run(["kubectl", "version", "--client", "-o", "json"], timeout=TIMEOUT_S)
    if not r.ok:
        return Check(FAIL, f"kubectl: {r.stderr or 'the version command failed.'}",
                     "Run `brew install kubectl`.")
    data = _json(r.stdout) or {}
    version = data.get("clientVersion", {}).get("gitVersion") or _first_line(r.stdout)
    return Check(OK, f"kubectl {version}")


def _profile_drivers() -> dict[str, str]:
    """Return the driver of each valid minikube profile."""
    r = cluster.run(["minikube", "profile", "list", "-o", "json"], timeout=TIMEOUT_S)
    data = _json(r.stdout) or {}
    return {p["Name"]: p.get("Config", {}).get("Driver", "") for p in data.get("valid", [])}


def _profile_running(profile: str) -> bool:
    r = cluster.run(["minikube", "status", "-p", profile, "-o", "json"], timeout=TIMEOUT_S)
    st = _json(r.stdout)
    # A profile with more than one node gives a list. The first item is the control plane.
    primary = st[0] if isinstance(st, list) and st else st
    return isinstance(primary, dict) and primary.get("APIServer") == "Running"


def check_driver(drivers: dict[str, str], profile: str | None) -> Check:
    """Examine the driver of the profile. If there is no profile, examine Docker."""
    driver = drivers.get(profile or "", "") or "docker"
    cmd = CONTAINER_DRIVERS.get(driver)
    if cmd is None:
        # A VM driver (for example qemu or vfkit) does not need a container engine.
        return Check(OK, f"minikube driver: {driver}")
    r = cluster.run(cmd, timeout=TIMEOUT_S)
    if not r.ok:
        return Check(FAIL, f"The {driver} driver does not respond: {_first_line(r.stderr) or 'no output.'}",
                     "Open Docker Desktop and wait until it runs, then try again." if driver == "docker"
                     else f"Start {driver}, then try again.")
    return Check(OK, f"minikube driver: {driver} {_first_line(r.stdout)}")


def check_running(drivers: dict[str, str], context: str | None) -> tuple[Check, str | None]:
    """Find a running profile. Examine the profile of the current context first."""
    if not drivers:
        return Check(FAIL, "There is no minikube profile.", "Run `minikube start`."), None
    if context in drivers:
        if _profile_running(context):
            return Check(OK, f"The minikube profile '{context}' is running."), context
        return Check(FAIL, f"The minikube profile '{context}' is not running.",
                     f"Run `minikube start -p {context}`."), context
    for profile in drivers:
        if _profile_running(profile):
            return Check(OK, f"The minikube profile '{profile}' is running."), profile
    names = ", ".join(drivers)
    return Check(FAIL, f"No minikube profile is running. Profiles: {names}.",
                 "Run `minikube start`."), next(iter(drivers))


def check_context() -> Check:
    """Use the same guard as the backend. Do not change the context."""
    try:
        profile = cluster.require_minikube()
    except cluster.UnsafeContextError:
        ctx = cluster.current_context()
        if ctx is None:
            return Check(FAIL, "kubectl has no current context. `minikube stop` removes it.",
                         "Run `minikube start`, or run `kubectl config use-context minikube`.")
        return Check(FAIL, f"The kubectl context '{ctx}' is not a minikube profile.",
                     "Run `kubectl config use-context minikube`, or use the name of your profile.")
    return Check(OK, f"The kubectl context '{profile}' is a minikube profile.")


def check_packages() -> Check:
    missing = [name for name in PACKAGES if importlib.util.find_spec(name) is None]
    if missing:
        return Check(FAIL, f"These Python packages are missing: {', '.join(missing)}.",
                     "Run ./run.sh. It installs the packages in .venv.")
    return Check(OK, f"Python packages: {', '.join(PACKAGES)}")


# Optional checks

def check_platform(system: str | None = None, release: str | None = None) -> Check:
    system = system or platform.system()
    if system == "Darwin":
        release = release if release is not None else platform.mac_ver()[0]
        return Check(OK, f"macOS {release}".strip(), required=False)
    return Check(WARN, f"KubeTrail supports macOS only. This computer runs {system}.",
                 "The app can work, but nobody tests it on this platform. See ROADMAP.md.",
                 required=False)


def check_helm() -> Check:
    r = cluster.run(["helm", "version", "--short"], timeout=TIMEOUT_S)
    if not r.ok:
        return Check(WARN, "helm is not installed. Act VIII and Act X need it.",
                     "Run `brew install helm`.", required=False)
    return Check(OK, f"helm {_first_line(r.stdout)}", required=False)


def check_terraform() -> Check:
    r = cluster.run(["terraform", "version", "-json"], timeout=TIMEOUT_S)
    data = _json(r.stdout) if r.ok else None
    if not isinstance(data, dict):
        return Check(WARN, "terraform is not installed. Act IX and Act X need it.",
                     "Run `brew install hashicorp/tap/terraform`.", required=False)
    return Check(OK, f"terraform {data.get('terraform_version', '')}".strip(), required=False)


def check_calico(context: str | None) -> Check:
    help_ = "Run `minikube delete`, then `minikube start --driver=docker --cni=calico`."
    if not context:
        return Check(WARN, "No context. Doctor cannot find Calico.", help_, required=False)
    r = cluster.run(["kubectl", "--context", context, "get", "pods", "-n", "kube-system",
                     "-l", "k8s-app=calico-node", "-o", "jsonpath={.items[*].metadata.name}"],
                    timeout=TIMEOUT_S)
    if r.ok and r.stdout.strip():
        return Check(OK, "The Calico network plugin runs.", required=False)
    return Check(WARN, "The cluster has no Calico. The NetworkPolicy lab needs it.", help_, required=False)


def check_kubernetes_version(context: str | None) -> Check:
    need = ".".join(str(v) for v in MIN_KUBERNETES)
    help_ = f"Run `minikube delete`, then `minikube start --driver=docker --cni=calico`. Act I works on older versions."
    r = cluster.run(["kubectl", "--context", context or "", "version", "-o", "json"], timeout=TIMEOUT_S) \
        if context else cluster.Result(False, "", "")
    data = _json(r.stdout) if r.ok else None
    found = (data or {}).get("serverVersion", {}).get("gitVersion", "") if isinstance(data, dict) else ""
    m = re.match(r"v?(\d+)\.(\d+)", found)
    if not m:
        return Check(WARN, "Doctor cannot read the Kubernetes version of the cluster.", help_, required=False)
    if (int(m.group(1)), int(m.group(2))) < MIN_KUBERNETES:
        return Check(WARN, f"Kubernetes {found} is older than {need}. Some labs need {need} or later.",
                     help_, required=False)
    return Check(OK, f"Kubernetes {found}", required=False)


def run_checks() -> list[Check]:
    checks = [check_platform(), check_python(), check_minikube(), check_kubectl()]
    drivers = _profile_drivers()
    context = cluster.current_context()
    running, profile = check_running(drivers, context)
    checks += [check_driver(drivers, profile), running, check_context(), check_packages()]
    target = context if context in drivers else None
    checks += [check_helm(), check_terraform(), check_calico(target), check_kubernetes_version(target)]
    return checks


def _use_color(stream) -> bool:
    # Obey the NO_COLOR convention: https://no-color.org/
    return "NO_COLOR" not in os.environ and hasattr(stream, "isatty") and stream.isatty()


COLORS = {OK: "\033[32m", WARN: "\033[33m", FAIL: "\033[31m"}


def report(checks: list[Check], stream=sys.stdout) -> int:
    """Write the results to the stream. Return the exit code."""
    color = _use_color(stream)
    print("KubeTrail doctor", file=stream)
    print(file=stream)
    for c in checks:
        label = f"{c.level:<4}"
        if color:
            label = f"{COLORS[c.level]}{label}\033[0m"
        print(f"{label}  {c.message}", file=stream)
        if c.help and c.level != OK:
            print(f"      {c.help}", file=stream)
    counts = {level: sum(c.level == level for c in checks) for level in (OK, WARN, FAIL)}
    failed = any(c.level == FAIL and c.required for c in checks)
    print(file=stream)
    print(f"Result: {counts[OK]} OK, {counts[WARN]} WARN, {counts[FAIL]} FAIL.", file=stream)
    print("Correct each FAIL result, then run this script again." if failed
          else "The required checks are satisfactory.", file=stream)
    return 1 if failed else 0


def main() -> int:
    return report(run_checks())


if __name__ == "__main__":
    sys.exit(main())
