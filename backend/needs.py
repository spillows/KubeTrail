"""The needs of a lab: the tools and cluster features that it must have.

A lab can declare a list of tokens in `needs`. Start lab refuses a lab with a
need that is not met, before the lab namespace exists. The lab panel reads
/api/needs and disables Start lab. The backend is the authority.

Each call is read-only and uses cluster.run, with a list of arguments and a
timeout. The tool check uses the PATH of the server process. That PATH can be
different from the PATH of the shell of the learner, so the help gives it.
"""
from __future__ import annotations

import json
import os
import re
import shutil

from backend import cluster

TOKEN_RE = re.compile(r"^(helm|terraform|gateway|cni:calico|addon:[a-z0-9-]+|nodes:[1-9])$")

INSTALL = {
    "helm": "brew install helm",
    "terraform": "brew install hashicorp/tap/terraform",
}
MULTI = "minikube start -p mq-multi --driver=docker --cni=calico --nodes=3"
ENVOY_GATEWAY = "v1.10.0"
GATEWAY_CLASS = "quest"
GATEWAY_INSTALL = (
    "`kubectl apply --server-side -f https://github.com/envoyproxy/gateway/releases/download/"
    f"{ENVOY_GATEWAY}/install.yaml`, then `kubectl wait --timeout=5m -n envoy-gateway-system "
    "deployment/envoy-gateway --for=condition=Available`, then, in the kubetrail folder, "
    "`kubectl apply -f install/gateway.yaml`"
)


def validate(tokens) -> list[str]:
    """Return the tokens as a list. Raise ValueError for a bad or repeated token."""
    if tokens is None:
        return []
    if not isinstance(tokens, list):
        raise ValueError("needs must be a list of tokens.")
    for t in tokens:
        if not isinstance(t, str) or not TOKEN_RE.match(t):
            raise ValueError(f"the need '{t}' is not valid. Use helm, terraform, gateway, cni:calico, "
                             f"addon:<name> or nodes:<n>.")
    if len(set(tokens)) != len(tokens):
        raise ValueError("needs has the same token two or more times.")
    return list(tokens)


def _tool(name: str) -> dict:
    if shutil.which(name):
        return {"met": True, "help": ""}
    return {"met": False, "help": f"This lab needs {name}. The server looked in "
                                  f"PATH={os.environ.get('PATH', '')}. Run `{INSTALL[name]}`, "
                                  f"then start the server again."}


def _ready_nodes(context: str) -> int | None:
    r = cluster.run(["kubectl", "--context", context, "get", "nodes", "-o", "json"])
    try:
        items = json.loads(r.stdout).get("items", []) if r.ok else None
    except (json.JSONDecodeError, AttributeError):
        items = None
    if items is None:
        return None
    return sum(any(c.get("type") == "Ready" and c.get("status") == "True"
                   for c in n.get("status", {}).get("conditions", [])) for n in items)


def _addons(context: str) -> set[str] | None:
    r = cluster.run(["minikube", "addons", "list", "-p", context, "-o", "json"])
    try:
        data = json.loads(r.stdout)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return {k for k, v in data.items() if isinstance(v, dict) and v.get("Status") == "enabled"}


def _calico(context: str) -> bool:
    r = cluster.run(["kubectl", "--context", context, "get", "pods", "-n", "kube-system",
                     "-l", "k8s-app=calico-node", "-o", "jsonpath={.items[*].metadata.name}"])
    return r.ok and r.stdout.strip() != ""


def _gateway(context: str) -> bool:
    r = cluster.run(["kubectl", "--context", context, "get", "gatewayclass", GATEWAY_CLASS, "-o",
                     'jsonpath={.status.conditions[?(@.type=="Accepted")].status}'])
    return r.ok and r.stdout.strip() == "True"


def evaluate(tokens, context: str) -> dict[str, dict]:
    """Return {"met": bool, "help": str} for each token. Read the cluster one time for each kind of token."""
    tokens = list(dict.fromkeys(tokens))
    out: dict[str, dict] = {}
    nodes = _ready_nodes(context) if any(t.startswith("nodes:") for t in tokens) else None
    addons = _addons(context) if any(t.startswith("addon:") for t in tokens) else None
    calico = _calico(context) if "cni:calico" in tokens else False
    gateway = _gateway(context) if "gateway" in tokens else False
    for t in tokens:
        if t in INSTALL:
            out[t] = _tool(t)
        elif t.startswith("nodes:"):
            n = int(t.split(":", 1)[1])
            met = nodes is not None and nodes >= n
            out[t] = {"met": met, "help": "" if met else
                      f"This lab needs {n} Ready nodes. The profile '{context}' has {nodes or 0}. "
                      f"Start the mq-multi profile: `{MULTI}`, then run "
                      f"`kubectl config use-context mq-multi`."}
        elif t.startswith("addon:"):
            name = t.split(":", 1)[1]
            met = addons is not None and name in addons
            out[t] = {"met": met, "help": "" if met else
                      f"This lab needs the minikube addon {name}. Run "
                      f"`minikube addons enable {name} -p {context}`."}
        elif t == "gateway":
            out[t] = {"met": gateway, "help": "" if gateway else
                      f"This lab needs a Gateway API controller and the GatewayClass "
                      f"{GATEWAY_CLASS}. Install Envoy Gateway {ENVOY_GATEWAY}: {GATEWAY_INSTALL}."}
        elif t == "cni:calico":
            out[t] = {"met": calico, "help": "" if calico else
                      "This lab needs the Calico network plugin. Delete the cluster and start it "
                      "again: `minikube delete`, then `minikube start --driver=docker --cni=calico`."}
    return out


def unmet_help(result: dict[str, dict]) -> list[str]:
    return [v["help"] for v in result.values() if not v["met"]]
