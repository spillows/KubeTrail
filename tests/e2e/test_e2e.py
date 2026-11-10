"""The end-to-end test. It runs each machine solution against a real minikube.

Run it with `.venv/bin/pytest -m e2e`. The default run excludes it. It uses
the current kubectl context, and require_minikube() refuses any context that
is not a minikube profile.
"""
import pytest
from fastapi.testclient import TestClient

from backend import cluster, labs, needs
from backend.main import app
import runner

pytestmark = pytest.mark.e2e

LAB_IDS = [lab["id"] for lab in labs.load_all()]


@pytest.fixture(scope="module")
def context():
    return cluster.require_minikube()


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.mark.parametrize("lab_id", LAB_IDS)
def test_solution_passes(lab_id, context, client):
    lab = labs.load(lab_id)
    unmet = needs.unmet_help(needs.evaluate(lab["needs"], context))
    if unmet:
        pytest.skip(" ".join(unmet))
    r = client.post(f"/api/labs/{lab_id}/setup")
    assert r.status_code == 200, r.text
    try:
        runner.execute(runner.load(lab_id), context)
        r = client.post(f"/api/labs/{lab_id}/verify")
        assert r.status_code == 200, r.text
        failed = [c for c in r.json()["checks"] if not c["passed"]]
        assert r.json()["passed"], failed
    finally:
        client.post(f"/api/labs/{lab_id}/reset")
