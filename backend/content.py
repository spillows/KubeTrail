"""Load and validate the quest content.

The content is in the content/ directory. index.yaml gives the act files in
page order. Each act file has one act and its quests. The validator is strict:
it refuses unknown keys, and it gives the file name in each error message.
The content is repo data and not user input. Thus, the API gives HTTP 500 for
a ContentError.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from backend import labs, progress

CONTENT_DIR = Path(__file__).resolve().parent.parent / "content"
INDEX = "index.yaml"

FILE_RE = re.compile(r"^[a-z0-9][a-z0-9-]*\.yaml$")
URL_RE = re.compile(r"^https?://\S+$")

ACT_KEYS = {"id", "title", "duration", "description", "quests"}
QUEST_KEYS = {"id", "type", "tags", "minutes", "title", "task", "code", "links", "answer"}
LINK_KEYS = {"title", "url"}
TYPES = ("READ", "LAB", "RECON", "BOSS")
TAGS = ("k8s", "helm", "tf", "int")
# A lab file can belong to a quest of these types.
LAB_TYPES = ("LAB", "BOSS")


class ContentError(RuntimeError):
    """A content file is not valid."""


def _fail(name: str, msg: str) -> ContentError:
    return ContentError(f"Content file '{name}': {msg}")


def _text(name: str, where: str, v, optional: bool = False) -> str | None:
    if v is None and optional:
        return None
    if not isinstance(v, str) or not v.strip():
        raise _fail(name, f"{where} must be a text that is not empty.")
    return v


def _positive(name: str, where: str, v) -> int:
    if isinstance(v, bool) or not isinstance(v, int) or v <= 0:
        raise _fail(name, f"{where} must be a positive integer.")
    return v


def _read_yaml(path: Path, name: str):
    try:
        return yaml.safe_load(path.read_text())
    except OSError as e:
        raise _fail(name, f"cannot read the file ({e}).") from None
    except yaml.YAMLError as e:
        raise _fail(name, f"the file is not valid YAML: {e}") from None


def _quest(name: str, i: int, q) -> dict:
    if not isinstance(q, dict):
        raise _fail(name, f"quests[{i}] must be a mapping.")
    qid = q.get("id")
    if not isinstance(qid, str) or not progress.QUEST_ID_RE.match(qid):
        raise _fail(name, f"quests[{i}] has the id '{qid}'. The id is not valid.")
    where = f"quest '{qid}'"
    extra = set(q) - QUEST_KEYS
    if extra:
        raise _fail(name, f"{where} has unknown keys: {', '.join(sorted(extra))}.")
    if q.get("type") not in TYPES:
        raise _fail(name, f"{where} has the type '{q.get('type')}'. Use one of: {', '.join(TYPES)}.")
    tags = q.get("tags")
    if not isinstance(tags, list) or not tags or len(set(tags)) != len(tags) \
            or not all(t in TAGS for t in tags):
        raise _fail(name, f"{where} must have a list of different tags from: {', '.join(TAGS)}.")
    out = {
        "id": qid,
        "type": q["type"],
        "tags": tags,
        "minutes": _positive(name, f"{where}.minutes", q.get("minutes")),
        "title": _text(name, f"{where}.title", q.get("title")),
        "task": _text(name, f"{where}.task", q.get("task")),
    }
    # A LAB or BOSS quest states an end state. It gives no command to copy.
    if "code" in q and q["type"] != "READ":
        raise _fail(name, f"{where} has 'code'. Only a READ quest can have 'code'.")
    for key in ("code", "answer"):
        if key in q:
            out[key] = _text(name, f"{where}.{key}", q[key])
    if "links" in q:
        if not isinstance(q["links"], list):
            raise _fail(name, f"{where}.links must be a list.")
        out["links"] = [_link(name, f"{where}.links[{j}]", link) for j, link in enumerate(q["links"])]
    return out


def _link(name: str, where: str, link) -> dict:
    if not isinstance(link, dict) or set(link) != LINK_KEYS:
        raise _fail(name, f"{where} must be a mapping with the keys 'title' and 'url'.")
    title = _text(name, f"{where}.title", link["title"])
    # The page puts the url in an href. Thus, permit only http and https.
    if not isinstance(link["url"], str) or not URL_RE.match(link["url"]):
        raise _fail(name, f"{where}.url must start with 'http://' or 'https://'.")
    return {"title": title, "url": link["url"]}


def _act(name: str, doc) -> dict:
    if not isinstance(doc, dict):
        raise _fail(name, "the file must contain a mapping.")
    extra = set(doc) - ACT_KEYS
    if extra:
        raise _fail(name, f"unknown keys: {', '.join(sorted(extra))}.")
    aid = doc.get("id")
    if not isinstance(aid, str) or not progress.QUEST_ID_RE.match(aid):
        raise _fail(name, f"the act id '{aid}' is not valid.")
    quests = doc.get("quests")
    if not isinstance(quests, list) or not quests:
        raise _fail(name, "the act must have one or more quests.")
    return {
        "id": aid,
        "title": _text(name, "title", doc.get("title")),
        "duration": _text(name, "duration", doc.get("duration")),
        "description": _text(name, "description", doc.get("description")),
        "quests": [_quest(name, i, q) for i, q in enumerate(quests)],
    }


def _act_files(content_dir: Path) -> list[str]:
    index = _read_yaml(content_dir / INDEX, INDEX)
    if not isinstance(index, dict) or set(index) != {"acts"} or not isinstance(index["acts"], list) \
            or not index["acts"]:
        raise _fail(INDEX, "the file must contain only the key 'acts' with a list of file names.")
    files = index["acts"]
    for f in files:
        # Examine the name before it goes into a path. Thus, "../x" cannot read other files.
        if not isinstance(f, str) or not FILE_RE.match(f) or f == INDEX:
            raise _fail(INDEX, f"'{f}' is not a valid act file name.")
    if len(set(files)) != len(files):
        raise _fail(INDEX, "the list has the same file two or more times.")
    on_disk = {p.name for p in content_dir.glob("*.yaml")} - {INDEX}
    missing = sorted(set(files) - on_disk)
    if missing:
        raise _fail(INDEX, f"these files do not exist: {', '.join(missing)}.")
    unlisted = sorted(on_disk - set(files))
    if unlisted:
        raise _fail(INDEX, f"these files are not in the list: {', '.join(unlisted)}.")
    return files


def load(content_dir: Path | None = None, labs_dir: Path | None = None) -> list[dict]:
    """Read and validate all acts. Return them in page order.

    Raise ContentError if a file is not valid, if two quests or two acts have
    the same id, or if a lab has no LAB or BOSS quest with the same id.
    """
    content_dir = content_dir if content_dir is not None else CONTENT_DIR
    labs_dir = labs_dir if labs_dir is not None else labs.LABS_DIR
    acts = []
    act_ids: set[str] = set()
    quests: dict[str, dict] = {}
    for name in _act_files(content_dir):
        act = _act(name, _read_yaml(content_dir / name, name))
        if act["id"] in act_ids:
            raise _fail(name, f"another file also has the act id '{act['id']}'.")
        act_ids.add(act["id"])
        for q in act["quests"]:
            if q["id"] in quests:
                raise _fail(name, f"the quest id '{q['id']}' is not unique.")
            quests[q["id"]] = q
        acts.append(act)
    for path in sorted(labs_dir.glob("*.yaml")):
        q = quests.get(path.stem)
        if q is None or q["type"] not in LAB_TYPES:
            raise ContentError(f"The lab '{path.stem}' has no LAB or BOSS quest with the same id in content/.")
    return acts


def quest_ids(content_dir: Path | None = None, labs_dir: Path | None = None) -> set[str]:
    """Return the ids of all quests."""
    return {q["id"] for act in load(content_dir, labs_dir) for q in act["quests"]}
