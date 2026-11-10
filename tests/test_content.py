"""Tests for the content loader and the content route.

These tests do not need a running minikube.
"""
import copy

import pytest
import yaml
from fastapi.testclient import TestClient

from backend import labs, content
from backend.main import app

client = TestClient(app)


def quest(**over):
    q = {"id": "q1", "type": "READ", "tags": ["k8s"], "minutes": 30,
         "title": "A quest", "task": "Do the task.",
         "links": [{"title": "Docs", "url": "https://kubernetes.io/docs/"}]}
    q.update(over)
    return q


def act(aid="I", quests=None):
    return {"id": aid, "title": "An act", "duration": "about 1 hour", "description": "The act.",
            "quests": quests if quests is not None else [quest()]}


def write(tmp_path, acts, labs=()):
    """Write the act files, an index and empty lab files. Return the two directories."""
    cdir, ldir = tmp_path / "content", tmp_path / "labs"
    cdir.mkdir()
    ldir.mkdir()
    names = []
    for i, a in enumerate(acts):
        name = f"act-{i}.yaml"
        (cdir / name).write_text(yaml.safe_dump(a))
        names.append(name)
    (cdir / "index.yaml").write_text(yaml.safe_dump({"acts": names}))
    for lab_id in labs:
        (ldir / f"{lab_id}.yaml").write_text("")
    return cdir, ldir


def load(tmp_path, acts, labs=()):
    return content.load(*write(tmp_path, acts, labs))


# The loader

def test_good_file_loads(tmp_path):
    acts = load(tmp_path, [act("I", [quest(), quest(id="q2", type="LAB")]),
                           act("Side", [quest(id="x1", answer="An answer.")])],
                labs=["q2"])
    assert [a["id"] for a in acts] == ["I", "Side"]
    assert [q["id"] for q in acts[0]["quests"]] == ["q1", "q2"]
    assert acts[1]["quests"][0]["answer"] == "An answer."
    assert acts[0]["quests"][0]["links"] == [{"title": "Docs", "url": "https://kubernetes.io/docs/"}]


def test_duplicate_quest_id_across_acts(tmp_path):
    with pytest.raises(content.ContentError, match="'q1' is not unique"):
        load(tmp_path, [act("I"), act("II")])


def test_duplicate_act_id(tmp_path):
    with pytest.raises(content.ContentError, match="act id 'I'"):
        load(tmp_path, [act("I"), act("I", [quest(id="q2")])])


@pytest.mark.parametrize("over,msg", [
    ({"type": "QUIZ"}, "type 'QUIZ'"),
    ({"tags": ["k8s", "go"]}, "tags"),
    ({"tags": []}, "tags"),
    ({"xp": 20}, "unknown keys: xp"),
    ({"minutes": "45"}, "minutes must be a positive integer"),
    ({"minutes": True}, "minutes must be a positive integer"),
    ({"type": "LAB", "code": "kubectl get pods"}, "Only a READ quest can have 'code'"),
    ({"type": "BOSS", "code": "kubectl get pods"}, "Only a READ quest can have 'code'"),
    ({"title": ""}, "title"),
    ({"min": 45}, "unknown keys: min"),
    ({"id": "../x"}, "is not valid"),
    ({"links": [{"title": "Bad", "url": "javascript:alert(1)"}]}, "url must start"),
    ({"links": [["Docs", "https://kubernetes.io/"]]}, "keys 'title' and 'url'"),
])
def test_bad_quest(tmp_path, over, msg):
    with pytest.raises(content.ContentError, match=msg) as e:
        load(tmp_path, [act(quests=[quest(**over)])])
    assert "act-0.yaml" in str(e.value)


def test_read_quest_can_have_code(tmp_path):
    acts = load(tmp_path, [act(quests=[quest(code="kubectl get pods")])])
    assert acts[0]["quests"][0]["code"] == "kubectl get pods"


def test_act_has_duration(tmp_path):
    assert load(tmp_path, [act()])[0]["duration"] == "about 1 hour"


def test_weeks_is_refused(tmp_path):
    a = act()
    a["weeks"] = a.pop("duration")
    with pytest.raises(content.ContentError, match="unknown keys: weeks"):
        load(tmp_path, [a])


def test_duration_is_required(tmp_path):
    a = act()
    del a["duration"]
    with pytest.raises(content.ContentError, match="duration must be a text"):
        load(tmp_path, [a])


def test_lab_with_boss_quest(tmp_path):
    acts = load(tmp_path, [act(quests=[quest(id="b1", type="BOSS")])], labs=["b1"])
    assert acts[0]["quests"][0]["type"] == "BOSS"


def test_unknown_act_key(tmp_path):
    a = act()
    a["desc"] = "Old key."
    with pytest.raises(content.ContentError, match="unknown keys: desc"):
        load(tmp_path, [a])


def test_lab_without_lab_quest(tmp_path):
    with pytest.raises(content.ContentError, match="lab 'k9' has no LAB or BOSS quest"):
        load(tmp_path, [act()], labs=["k9"])


def test_lab_with_read_quest_of_same_id(tmp_path):
    with pytest.raises(content.ContentError, match="lab 'q1' has no LAB or BOSS quest"):
        load(tmp_path, [act()], labs=["q1"])


def test_file_not_in_index(tmp_path):
    cdir, ldir = write(tmp_path, [act()])
    (cdir / "extra.yaml").write_text(yaml.safe_dump(act("X", [quest(id="q9")])))
    with pytest.raises(content.ContentError, match="not in the list: extra.yaml"):
        content.load(cdir, ldir)


def test_index_refuses_path(tmp_path):
    cdir, ldir = write(tmp_path, [act()])
    (cdir / "index.yaml").write_text(yaml.safe_dump({"acts": ["../labs/k2.yaml"]}))
    with pytest.raises(content.ContentError, match="not a valid act file name"):
        content.load(cdir, ldir)


def test_bad_yaml(tmp_path):
    cdir, ldir = write(tmp_path, [act()])
    (cdir / "act-0.yaml").write_text("id: [")
    with pytest.raises(content.ContentError, match="act-0.yaml.*not valid YAML"):
        content.load(cdir, ldir)


def test_load_does_not_change_input(tmp_path):
    a = act()
    before = copy.deepcopy(a)
    load(tmp_path, [a])
    assert a == before


def test_repo_content_loads():
    """Load all content files and all lab files of the repo."""
    acts = content.load()
    assert acts and all(a["quests"] for a in acts)
    ids = [q["id"] for a in acts for q in a["quests"]]
    assert len(ids) == len(set(ids))
    assert set(ids) == content.quest_ids()
    for path in labs.LABS_DIR.glob("*.yaml"):
        q = next(q for a in acts for q in a["quests"] if q["id"] == path.stem)
        assert q["type"] in content.LAB_TYPES, path.stem


def test_each_repo_lab_quest_has_a_lab():
    """The app checks every LAB and BOSS quest. No such quest has a "Mark done" button."""
    for a in content.load():
        for q in a["quests"]:
            if q["type"] in content.LAB_TYPES:
                assert labs.exists(q["id"]), q["id"]


# The route

def test_content_route():
    r = client.get("/api/content")
    assert r.status_code == 200
    acts = r.json()["acts"]
    assert [a["id"] for a in acts] == [a["id"] for a in content.load()]
    assert acts[0]["id"] == "I"
    assert [q["id"] for q in acts[0]["quests"]][:3] == ["k1", "k2", "k3"]


def test_content_error_is_500(monkeypatch, tmp_path):
    cdir, _ = write(tmp_path, [act(quests=[quest(type="QUIZ")])])
    monkeypatch.setattr(content, "CONTENT_DIR", cdir)
    r = client.get("/api/content")
    assert r.status_code == 500
    assert "type 'QUIZ'" in r.json()["detail"]
