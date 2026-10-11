import pytest
from fastapi.testclient import TestClient

from app import cases, config, db, elevenlabs, main
from app.main import app

client = TestClient(app)  # no "with": the app doesn't start or touch the database

AUDIO = bytes(range(256)) * 4  # 1024 bytes
CASE = {"id": 7, "conversation_ids": ["conv_a", "conv_b"]}
URL = "/api/cases/7/recordings/conv_a/audio"


@pytest.fixture(autouse=True)
def fakes(monkeypatch):
    monkeypatch.setattr(config, "DISPATCH_KEY", "test-key-123")

    async def get_case(case_id):
        return CASE if case_id == 7 else None

    async def get_audio(conversation_id):
        return (AUDIO, "audio/mpeg") if conversation_id == "conv_a" else None

    monkeypatch.setattr(db, "get_case", get_case)
    monkeypatch.setattr(elevenlabs, "get_conversation_audio", get_audio)


def test_needs_the_key_by_header_or_query():
    assert client.get(URL).status_code == 401
    assert client.get(URL + "?key=wrong").status_code == 401
    assert client.get(URL, headers={"X-Dispatch-Key": "wrong"}).status_code == 401
    assert client.get(URL + "?key=test-key-123").status_code == 200
    assert client.get(URL, headers={"X-Dispatch-Key": "test-key-123"}).status_code == 200


def test_wrong_header_is_not_rescued_by_query():
    r = client.get(URL + "?key=test-key-123", headers={"X-Dispatch-Key": "wrong"})
    assert r.status_code == 401


def test_only_this_cases_conversations():
    assert client.get("/api/cases/7/recordings/conv_other/audio?key=test-key-123").status_code == 404
    assert client.get("/api/cases/8/recordings/conv_a/audio?key=test-key-123").status_code == 404


def test_missing_recording_is_404():
    assert client.get("/api/cases/7/recordings/conv_b/audio?key=test-key-123").status_code == 404


def test_full_and_ranged_download():
    r = client.get(URL + "?key=test-key-123")
    assert r.content == AUDIO
    assert r.headers["content-type"] == "audio/mpeg"
    assert r.headers["accept-ranges"] == "bytes"

    r = client.get(URL + "?key=test-key-123", headers={"Range": "bytes=100-199"})
    assert r.status_code == 206
    assert r.content == AUDIO[100:200]
    assert r.headers["content-range"] == "bytes 100-199/1024"

    r = client.get(URL + "?key=test-key-123", headers={"Range": "bytes=1000-"})
    assert r.content == AUDIO[1000:]

    r = client.get(URL + "?key=test-key-123", headers={"Range": "bytes=-24"})
    assert r.content == AUDIO[-24:]

    r = client.get(URL + "?key=test-key-123", headers={"Range": "bytes=5000-"})
    assert r.status_code == 416


def test_byte_range_parsing():
    assert main._byte_range(None, 10) is None
    assert main._byte_range("bytes=0-", 10) == (0, 9)
    assert main._byte_range("bytes=2-50", 10) == (2, 9)
    assert main._byte_range("bytes=-3", 10) == (7, 9)
    assert main._byte_range("bytes=x-", 10) is None
    assert main._byte_range("bytes=0-1,4-5", 10) is None


def line(cid, call, t=0):
    return {"role": "user", "message": "hi", "call": call, "t": t, "conversation_id": cid}


def test_recordings_follow_call_order_and_labels():
    case = {"conversation_ids": ["a", "b", "c", "d"],
            "transcript": [line("a", "intake"), line("a", "intake", 3), line("b", "callback"),
                           line("c", "intake"), line("d", "callback")]}
    assert cases.recordings(case) == [
        {"conversation_id": "a", "call": "intake", "label": "Intake call"},
        {"conversation_id": "b", "call": "callback", "label": "Callback 1"},
        {"conversation_id": "c", "call": "intake", "label": "Call 2"},
        {"conversation_id": "d", "call": "callback", "label": "Callback 2"},
    ]


def test_recordings_skip_untagged_and_unknown_lines():
    case = {"conversation_ids": ["a"],
            "transcript": [{"role": "user", "message": "old line", "call": "intake", "t": 0},
                           line("a", "callback"), line("zzz", "intake")]}
    assert cases.recordings(case) == [{"conversation_id": "a", "call": "callback", "label": "Callback"}]


def test_serialize_exposes_recordings_not_conversation_ids():
    out = cases.serialize({"id": 1, "conversation_ids": ["a"], "transcript": [line("a", "intake")]})
    assert "conversation_ids" not in out
    assert out["recordings"][0]["conversation_id"] == "a"


def test_translation_gets_original_timing():
    lines = [line("a", "intake", 0), line("a", "intake", 4.5)]
    translated = [{"role": "caller", "message": "hello"}, {"role": "agent", "message": "ok"}]
    aligned = cases._align_translation(translated, lines)
    assert [l["t"] for l in aligned] == [0, 4.5]
    assert all(l["conversation_id"] == "a" for l in aligned)
    # counts differ: leave it alone rather than guess
    assert cases._align_translation(translated[:1], lines) == translated[:1]
