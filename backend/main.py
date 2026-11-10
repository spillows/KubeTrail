"""The FastAPI entry point.

The API is under /api. All other paths go to the static frontend.
To start the server, run this command:

    uvicorn backend.main:app --reload
"""
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import cluster, content, labs, needs, progress

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"

app = FastAPI(title="KubeTrail")

# FastAPI uses the handler of the most specific error class. Thus,
# LabNotFound gives 404 and not 400, and UnsafeContextError gives 409 and not 502.
ERROR_STATUS = {
    progress.ProgressError: 400,
    progress.ProgressFileError: 500,
    labs.LabNotFound: 404,
    labs.LabError: 400,
    content.ContentError: 500,
    cluster.UnsafeContextError: 409,
    cluster.ClusterError: 502,
}


def _handler(status: int):
    async def handle(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=status, content={"detail": str(exc)})
    return handle


for _cls, _status in ERROR_STATUS.items():
    app.add_exception_handler(_cls, _handler(_status))


@app.get("/api/cluster")
def get_cluster() -> dict:
    return cluster.status()


# The lab routes use "def", not "async def". FastAPI then runs them in a
# thread pool, and a slow kubectl call does not stop other requests.

@app.get("/api/labs")
def list_labs() -> list[dict]:
    return [labs.summary(lab) for lab in labs.load_all()]


@app.get("/api/needs")
def get_needs() -> dict:
    """Return the state of each need that a lab declares."""
    context = cluster.require_minikube()
    tokens = [t for lab in labs.load_all() for t in lab["needs"]]
    return needs.evaluate(tokens, context)


@app.get("/api/labs/{lab_id}")
def get_lab(lab_id: str) -> dict:
    return labs.summary(labs.load(lab_id))


@app.post("/api/labs/{lab_id}/setup")
def setup_lab(lab_id: str) -> dict:
    return labs.setup(lab_id)


@app.post("/api/labs/{lab_id}/verify")
def verify_lab(lab_id: str) -> dict:
    """Run the checks. If all checks pass, record the quest as done."""
    result = labs.verify(lab_id)
    if result["passed"]:
        result["progress"] = progress.mark(lab_id)
    return result


@app.post("/api/labs/{lab_id}/reset")
def reset_lab(lab_id: str) -> dict:
    return labs.reset(lab_id)


@app.get("/api/content")
def get_content() -> dict:
    """Return the acts and their quests in page order."""
    return {"acts": content.load()}


@app.get("/api/progress")
def get_progress() -> dict:
    return progress.load()


@app.put("/api/progress/{quest_id}")
def mark_quest(quest_id: str) -> dict:
    """Record a quest as done. A lab quest is done only when its checks pass."""
    if quest_id not in content.quest_ids():
        raise progress.ProgressError(f"No quest has the id '{quest_id}'.")
    if labs.exists(quest_id):
        raise progress.ProgressError(
            f"The quest '{quest_id}' is a lab. Click \"Check my work\" to complete it."
        )
    return progress.mark(quest_id)


@app.delete("/api/progress/{quest_id}")
def unmark_quest(quest_id: str) -> dict:
    return progress.unmark(quest_id)


# Mount the frontend last. Then the /api routes have priority.
app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="frontend")
