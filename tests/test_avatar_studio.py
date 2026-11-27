"""The avatar studio: the words that ask for a face, the cost card, the four candidates, the pick, the poses, the clips."""

from __future__ import annotations

import asyncio
import base64
import io
import json
import time
from collections.abc import Iterator

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from nanomuse.avatar import studio as studio_mod
from nanomuse.avatar.studio import (
    CLIP_MOODS,
    PICTURES_PER_FACE,
    Endpoint,
    build_prompt,
    clip_prompt,
    parse_choice,
    parse_request,
)
from nanomuse.config import Settings
from nanomuse.llm import MockLLM
from nanomuse.server import create_app
from nanomuse.server.service import MuseService


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("换个形象：一只橘猫", "一只橘猫"),
        ("帮我把形象换成一只戴眼镜的柯基吧", "一只戴眼镜的柯基"),
        ("变成一只小龙", "一只小龙"),
        ("New avatar: a robot owl", "robot owl"),
        ("please change your avatar to a small fox with a scarf", "small fox with a scarf"),
        ("become a corgi", "corgi"),
        ("be quiet", None),
        ("今天天气怎么样", None),
        ("换个话题吧", None),
        ("", None),
    ],
)
def test_parse_request(text: str, expected: str | None) -> None:
    assert parse_request(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("第二个", 1),
        ("就第一个吧", 0),
        ("3", 2),
        ("选4号", 3),
        ("the first one", 0),
        ("I'll take 2", 1),
        ("top right", 1),
        ("右下", 3),
        ("重新生成", "regenerate"),
        ("try again", "regenerate"),
        ("算了", "cancel"),
        ("cancel", "cancel"),
        ("what about the weather", None),
        ("5", None),
    ],
)
def test_parse_choice(text: str, expected: int | str | None) -> None:
    assert parse_choice(text) == expected


def test_build_prompt_varies_by_index() -> None:
    a, b = build_prompt("一只橘猫。", 0), build_prompt("一只橘猫。", 1)
    assert "一只橘猫" in a and a != b
    assert "variation 1" in a and "variation 2" in b
    assert "white background" in a


def test_build_prompt_draws_in_the_phones_styles() -> None:
    # the same ids as the phone's AvatarStudio.Style; an unknown one is Muse's 3D toy
    assert "vinyl toy" in build_prompt("a robot owl", 0)
    assert "watercolour" in build_prompt("a robot owl", 0, "watercolor")
    assert "pixel art" in build_prompt("a robot owl", 0, "pixel")
    assert "vinyl toy" in build_prompt("a robot owl", 0, "no-such-style")
    assert "3D toy look" in clip_prompt("idle") and "3D toy look" not in clip_prompt("idle", "flat")


def _png(colour: tuple[int, int, int]) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (64, 64), colour).save(out, "PNG")
    return out.getvalue()


class FakeImages:
    """An OpenAI images endpoint that answers every call with a coloured square."""

    def __init__(self) -> None:
        self.generations: list[dict] = []
        self.edits: list[str] = []
        self.busy = 0  # how many of the next calls answer 429 first
        self.in_flight = 0
        self.peak = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/images/generations"):
            if self.busy > 0:
                self.busy -= 1
                return httpx.Response(
                    429,
                    json={
                        "error": {
                            "code": "provider_busy",
                            "message": "The image provider is busy right now; try again in a moment",
                        }
                    },
                )
            body = json.loads(request.content)
            self.generations.append(body)
            colour = (200, 40 * len(self.generations) % 255, 90)
        elif request.url.path.endswith("/images/edits"):
            self.edits.append(request.url.path)
            colour = (40, 120, 200)
        else:
            return httpx.Response(404, json={"error": {"message": "no such route"}})
        return httpx.Response(
            200, json={"data": [{"b64_json": base64.b64encode(_png(colour)).decode()}]}
        )


@pytest.fixture()
def studio_server(settings: Settings) -> Iterator[tuple[TestClient, MuseService, FakeImages]]:
    settings.server.token = "secret-token"
    settings.llm.base_url = "https://images.example.test/v1"
    settings.llm.api_key = "k"
    settings.llm.image_model = "draw-1"
    service = MuseService(settings, llm=MockLLM([]))
    fake = FakeImages()
    app = create_app(settings, service)
    with TestClient(app) as client:
        service.avatar._http = httpx.AsyncClient(transport=httpx.MockTransport(fake.handler))
        client.headers["Authorization"] = "Bearer secret-token"
        yield client, service, fake


def _wait(pred, timeout: float = 5.0):  # noqa: ANN001
    deadline = time.time() + timeout
    while time.time() < deadline:
        v = pred()
        if v:
            return v
        time.sleep(0.05)
    raise AssertionError("condition not met in time")


def _avatar_event(client: TestClient) -> dict:
    events = client.get("/api/threads/main/events").json()["events"]
    return next(e for e in reversed(events) if e["type"] == "avatar")


def test_chat_request_becomes_a_card_and_the_agent_stays_out(studio_server) -> None:
    client, service, fake = studio_server
    assert client.get("/api/avatar").json() == {
        "available": True,
        "unavailable": "",
        "unavailable_zh": "",
        "image_model": "draw-1",
        "video_model": "",
        "cloud": False,
        "host": "images.example.test",
        "current": None,
        "face": None,
    }
    r = client.post("/api/threads/main/send", json={"text": "换个形象：一只橘猫"})
    assert r.status_code == 200
    ev = _wait(
        lambda: client.get("/api/threads/main/events").json()["events"] and _avatar_event(client)
    )
    assert ev["stage"] == "estimate" and ev["description"] == "一只橘猫"
    assert ev["cost"]["cloud"] is False and ev["cost"]["pictures"] == PICTURES_PER_FACE
    # the agent was not run for it: no assistant bubble, the thread is idle
    kinds = [e["type"] for e in client.get("/api/threads/main/events").json()["events"]]
    assert "assistant" not in kinds
    assert not service.threads["main"].busy
    assert fake.generations == []


def test_draw_pick_pose_sets_the_profile(studio_server, settings: Settings) -> None:
    client, service, fake = studio_server
    client.post("/api/threads/main/send", json={"text": "new avatar: a robot owl"})
    ev = _wait(lambda: _avatar_event(client))
    sid = ev["session"]
    r = client.post("/api/avatar/start", json={"session": sid})
    assert r.status_code == 200 and r.json()["stage"] == "drawing"
    ev = _wait(lambda: (e := _avatar_event(client))["stage"] == "choose" and e)
    assert len(fake.generations) == 4 and all(ev["candidates"])
    assert {g["model"] for g in fake.generations} == {"draw-1"}
    # each candidate is a webp in the workspace, reachable through the files API
    first = ev["candidates"][0]
    assert first.startswith("avatar/sessions/")
    got = client.get(f"/api/files/{first}")
    assert got.status_code == 200 and got.headers["content-type"].startswith("image/webp")
    # the pick by words
    client.post("/api/threads/main/send", json={"text": "第二个"})
    ev = _wait(lambda: (e := _avatar_event(client))["stage"] == "done" and e)
    assert ev["chosen"] == 1 and ev["face"].startswith("face-")
    assert set(ev["moods"]) == {"idle", "working", "waiting", "happy", "error"}
    assert len(fake.edits) == 4
    face_dir = service.workspace() / "avatar" / ev["face"]
    assert sorted(p.name for p in face_dir.iterdir()) == [
        "error.webp",
        "face.json",
        "happy.webp",
        "idle.webp",
        "waiting.webp",
        "working.webp",
    ]
    assert client.get("/api/settings").json()["profile"]["avatar"] == ev["face"]
    # the candidates of the finished session are cleared later; the face stays, with its record
    view = client.get("/api/avatar").json()
    assert view["current"]["stage"] == "done"
    assert view["face"]["id"] == ev["face"]
    assert view["face"]["description"] == "robot owl" and view["face"]["model"] == "draw-1"
    assert view["face"]["style"] == "muse" and view["face"]["created"] > 0


def test_a_picture_with_the_request_is_the_reference(studio_server) -> None:
    """The phone's "make it look like my cat": one picture attached to the request, and the
    four candidates are edits of it rather than drawings from the words alone."""
    client, service, fake = studio_server
    pytest.importorskip("PIL")
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (1400, 900), (200, 120, 40)).save(buf, "PNG")
    up = client.post("/api/files/upload?name=cat.png", content=buf.getvalue())
    assert up.status_code == 200, up.text
    path = up.json()["path"]
    client.post("/api/threads/main/send", json={"text": "换个形象：像这只猫", "files": [path]})
    ev = _wait(lambda: _avatar_event(client))
    assert ev["stage"] == "estimate" and ev["reference"] == path
    client.post("/api/avatar/start", json={"session": ev["session"]})
    ev = _wait(lambda: (e := _avatar_event(client))["stage"] == "choose" and e)
    assert fake.generations == [] and len(fake.edits) == 4 and all(ev["candidates"])
    assert not service.threads["main"].busy
    # two pictures (or a file that is not one) is the agent's message, not the studio's
    kinds_before = len(client.get("/api/threads/main/events").json()["events"])
    client.post(
        "/api/threads/main/send", json={"text": "换个形象：像这只猫", "files": [path, path]}
    )
    _wait(lambda: not service.threads["main"].busy and service.threads["main"].inbox.empty())
    events = client.get("/api/threads/main/events").json()["events"][kinds_before:]
    assert [e["type"] for e in events][:1] == ["user"] and not any(
        e["type"] == "avatar" for e in events
    )


def test_the_studio_screen_runs_a_session_without_a_card(studio_server) -> None:
    """From the studio screen (thread ""): no card in the chat, the session is reported over
    the socket as "studio" messages, and the poses can be drawn again from the menu."""
    client, service, fake = studio_server
    q = service.ui.bus.subscribe()  # what a web socket would receive
    r = client.post(
        "/api/avatar/begin", json={"description": "a tiny whale", "thread": "", "style": "pixel"}
    )
    assert r.status_code == 200 and r.json()["stage"] == "estimate"
    sid = r.json()["session"]
    events = client.get("/api/threads/main/events").json()["events"]
    assert not any(e["type"] == "avatar" for e in events)
    client.post("/api/avatar/start", json={"session": sid})
    _wait(lambda: service.avatar.current and service.avatar.current.stage == "choose")
    client.post("/api/avatar/choose", json={"session": sid, "index": 2})
    _wait(lambda: service.avatar.current and service.avatar.current.stage == "done")
    face = service.profile.avatar
    assert face.startswith("face-")
    seen = []
    while not q.empty():
        msg = q.get_nowait()
        if msg.get("kind") == "studio":
            seen.append(msg)
    assert [m["current"]["stage"] for m in seen][:2] == ["estimate", "drawing"]
    assert seen[-1]["current"]["stage"] == "done" and seen[-1]["current"]["face"] == face
    assert not any(
        e["type"] in ("avatar", "notice")
        for e in client.get("/api/threads/main/events").json()["events"]
    )
    # the poses again, from the face's idle still
    edits_before = len(fake.edits)
    r = client.post("/api/avatar/moods")
    assert r.status_code == 200 and r.json()["stage"] == "posing" and r.json()["face"] == face
    _wait(lambda: service.avatar.current and service.avatar.current.stage == "done")
    assert len(fake.edits) == edits_before + 4
    assert service.profile.avatar == face
    assert client.get("/api/avatar").json()["face"]["description"] == "a tiny whale"


def test_redrawing_the_poses_needs_a_drawn_face(studio_server) -> None:
    client, _service, _fake = studio_server
    r = client.post("/api/avatar/moods")
    assert r.status_code == 409 and "no face" in r.json()["detail"]


def test_a_busy_provider_is_waited_out_two_pictures_at_a_time(studio_server, monkeypatch) -> None:
    """A 429 from the provider (or the relay's `provider_busy`) is tried again after a pause
    rather than shown; the candidates are drawn two at a time so as not to provoke it."""
    client, service, fake = studio_server
    naps: list[float] = []

    real_sleep = asyncio.sleep

    async def no_sleep(seconds: float) -> None:
        naps.append(seconds)
        await real_sleep(0)

    # (the studio's `asyncio` is the module itself: this patches sleep everywhere for the test)
    monkeypatch.setattr(asyncio, "sleep", no_sleep)
    fake.busy = 3
    client.post("/api/threads/main/send", json={"text": "new avatar: a robot owl"})
    ev = _wait(lambda: _avatar_event(client))
    client.post("/api/avatar/start", json={"session": ev["session"]})
    ev = _wait(lambda: (e := _avatar_event(client))["stage"] == "choose" and e)
    assert all(ev["candidates"]) and not ev["errors"]
    assert len(fake.generations) == 4
    assert sorted(naps)[:1] == [3.0] and len(naps) == 3  # three 429s, three pauses

    # a provider that never clears: the sentence, not the status line
    fake.busy = 99
    client.post("/api/avatar/start", json={"session": ev["session"]})
    ev = _wait(lambda: (e := _avatar_event(client))["stage"] == "failed" and e)
    assert ev["message"] == "The image provider is busy right now; try again in a minute."
    fake.busy = 0


def test_cancel_and_redraw(studio_server) -> None:
    client, service, fake = studio_server
    # the picker in Settings sends the style too (the phone's list); the card carries it
    r = client.post("/api/avatar/begin", json={"description": "a small fox", "style": "pixel"})
    assert r.status_code == 200 and r.json()["stage"] == "estimate"
    assert r.json()["style"] == "pixel"
    sid = r.json()["session"]
    client.post("/api/avatar/start", json={"session": sid})
    _wait(lambda: _avatar_event(client)["stage"] == "choose")
    assert all("pixel art" in g["prompt"] for g in fake.generations[:4])
    # "regenerate" by words draws four more
    client.post("/api/threads/main/send", json={"text": "重新生成"})
    _wait(lambda: len(fake.generations) >= 8)
    _wait(lambda: _avatar_event(client)["stage"] == "choose")
    r = client.post("/api/avatar/cancel", json={"session": sid})
    assert r.status_code == 200 and r.json()["stage"] == "cancelled"
    assert not (service.workspace() / "avatar" / "sessions" / sid).exists()
    # a session that is over cannot be driven
    assert client.post("/api/avatar/choose", json={"session": sid, "index": 0}).status_code == 200
    assert client.post("/api/avatar/start", json={"session": "nope"}).status_code == 409


def test_without_an_image_model_the_chat_says_so(settings: Settings) -> None:
    settings.server.token = "secret-token"
    settings.llm.base_url = "https://api.deepseek.com"
    settings.llm.api_key = "k"
    service = MuseService(settings, llm=MockLLM([]))
    app = create_app(settings, service)
    with TestClient(app) as client:
        client.headers["Authorization"] = "Bearer secret-token"
        assert client.get("/api/avatar").json()["available"] is False
        client.post("/api/threads/main/send", json={"text": "换个形象：一只橘猫"})
        notice = _wait(
            lambda: next(
                (
                    e
                    for e in client.get("/api/threads/main/events").json()["events"]
                    if e["type"] == "notice"
                ),
                None,
            )
        )
        assert notice["code"] == "no_image_model"
        assert "avatar" not in [
            e["type"] for e in client.get("/api/threads/main/events").json()["events"]
        ]


# ----------------------------------------------------------------------------- clips
@pytest.mark.parametrize(
    ("base", "host"),
    [
        ("https://cloud.nanomuse.cn/v1", "https://cloud.nanomuse.cn"),
        ("https://dashscope.aliyuncs.com/compatible-mode/v1", "https://dashscope.aliyuncs.com"),
        ("https://dashscope.aliyuncs.com/api/v1", "https://dashscope.aliyuncs.com"),
    ],
)
def test_video_host_is_the_root_of_the_model_url(base: str, host: str) -> None:
    ep = Endpoint(
        base_url=base,
        api_key="k",
        image_model="i",
        cloud="nanomuse" in base,
        video_model="wan2.2-i2v-flash",
    )
    assert ep.video_host == host and ep.clips


def test_a_plain_openai_provider_has_stills_only() -> None:
    ep = Endpoint(
        base_url="https://api.openai.com/v1",
        api_key="k",
        image_model="gpt-image-1",
        cloud=False,
        video_model="x",
    )
    assert not ep.clips


def test_hosted_media_uses_current_menu_without_submitting_voice_free_avatar_clips(
    studio_server,
) -> None:
    _, service, _ = studio_server
    service.hub.cloud.base_url = "https://cloud.nanomuse.cn"
    service.settings.llm.base_url = "https://cloud.nanomuse.cn/v1"
    service.settings.llm.image_model = "qwen-image-3.0"
    service.settings.llm.video_model = "wan2.2-i2v-flash"
    service.hub.models = [
        {"id": "qwen-image-3.0", "nanomuse": {"kind": "image"}},
        {"id": "wan2.2-i2v-flash", "nanomuse": {"kind": "video"}},
    ]
    assert service.avatar.endpoint() is None
    service.hub.models.extend(
        [
            {"id": "musesteamer-air-image", "nanomuse": {"kind": "image"}},
            {"id": "ernie-wizshot-me", "nanomuse": {"kind": "video"}},
        ]
    )
    ep = service.avatar.endpoint()
    assert ep is not None and ep.image_model == "musesteamer-air-image"
    assert ep.video_model == "ernie-wizshot-me" and not ep.clips


def test_a_relaying_host_names_where_the_video_api_lives() -> None:
    # the showcase gateway: the chat model behind an address nobody recognises, and the video
    # API at the same address (`[llm] video_base_url`) — clips, through that host
    ep = Endpoint(
        base_url="http://gateway:8000/llm/abc/main",
        api_key="k",
        image_model="qwen-image-3.0",
        cloud=False,
        video_model="wan2.2-i2v-flash",
        video_base_url="http://gateway:8000/llm/abc/main/",
    )
    assert ep.clips and ep.video_host == "http://gateway:8000/llm/abc/main"


def test_clip_prompts_loop_on_a_white_background() -> None:
    for mood in CLIP_MOODS:
        p = clip_prompt(mood)
        assert "white background" in p and "loops naturally" in p


class FakeModelStudio(FakeImages):
    """Model Studio's native endpoints: pictures from multimodal-generation, clips through the
    asynchronous video API (policy, upload, task, polling, file)."""

    def __init__(self) -> None:
        super().__init__()
        self.uploads: list[str] = []
        self.tasks: dict[str, dict] = {}
        self.polls = 0

    def handler(self, request: httpx.Request) -> httpx.Response:  # noqa: PLR0911
        path = request.url.path
        if path.endswith("/multimodal-generation/generation"):
            body = json.loads(request.content)
            content = body["input"]["messages"][0]["content"]
            if any("image" in c for c in content):
                self.edits.append(body["model"])
            else:
                self.generations.append(body)
            return httpx.Response(
                200,
                json={
                    "output": {
                        "choices": [
                            {"message": {"content": [{"image": "https://oss.example.test/p.png"}]}}
                        ]
                    }
                },
            )
        if path == "/p.png":
            return httpx.Response(
                200, content=_png((10, 200, 30)), headers={"content-type": "image/png"}
            )
        if path == "/api/v1/uploads":
            assert request.url.params["model"] == "wan2.2-i2v-flash"
            return httpx.Response(
                200,
                json={
                    "data": {
                        "upload_host": "https://oss.example.test/bucket",
                        "upload_dir": "tmp/dir",
                        "oss_access_key_id": "id",
                        "signature": "sig",
                        "policy": "pol",
                    }
                },
            )
        if path == "/bucket":
            assert b"first-frame.png" in request.content
            self.uploads.append(path)
            return httpx.Response(204)
        if path.endswith("/video-generation/video-synthesis"):
            assert request.headers["x-dashscope-async"] == "enable"
            body = json.loads(request.content)
            assert body["input"]["img_url"] == "oss://tmp/dir/first-frame.png"
            assert body["parameters"] == {"watermark": False, "resolution": "480P"}
            tid = f"task-{len(self.tasks)}"
            self.tasks[tid] = body
            return httpx.Response(200, json={"output": {"task_id": tid, "task_status": "PENDING"}})
        if path.startswith("/api/v1/tasks/"):
            self.polls += 1
            tid = path.rsplit("/", 1)[1]
            status = "SUCCEEDED" if self.polls > 2 else "RUNNING"
            out = {"task_status": status}
            if status == "SUCCEEDED":
                out["video_url"] = f"https://oss.example.test/{tid}.mp4"
            return httpx.Response(200, json={"output": out})
        if path.endswith(".mp4"):
            return httpx.Response(200, content=b"\x00\x00\x00\x18ftypmp42" + path.encode())
        return httpx.Response(404, json={"message": "no such route " + path})


def test_model_studio_face_gets_its_clips(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(studio_mod, "CLIP_POLL_S", 0.01)
    settings.server.token = "secret-token"
    settings.llm.base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    settings.llm.api_key = "k"
    service = MuseService(settings, llm=MockLLM([]))
    fake = FakeModelStudio()
    app = create_app(settings, service)
    with TestClient(app) as client:
        service.avatar._http = httpx.AsyncClient(transport=httpx.MockTransport(fake.handler))
        client.headers["Authorization"] = "Bearer secret-token"
        view = client.get("/api/avatar").json()
        assert view["available"] and view["video_model"] == "wan2.2-i2v-flash"
        client.post("/api/threads/main/send", json={"text": "new avatar: a robot owl"})
        ev = _wait(lambda: _avatar_event(client))
        assert ev["cost"]["clips"] == 4 and ev["cost"]["clip_model"] == "wan2.2-i2v-flash"
        client.post("/api/avatar/start", json={"session": ev["session"]})
        _wait(lambda: _avatar_event(client)["stage"] == "choose")
        client.post("/api/avatar/choose", json={"session": ev["session"], "index": 0})
        ev = _wait(lambda: (e := _avatar_event(client))["stage"] == "done" and e, timeout=15)
        assert set(ev["clips"]) == set(CLIP_MOODS)
        assert ev["errors"] == []
        face_dir = service.workspace() / "avatar" / ev["face"]
        names = sorted(p.name for p in face_dir.iterdir())
        assert [n for n in names if n.endswith(".mp4")] == [
            "happy.mp4",
            "idle.mp4",
            "waiting.mp4",
            "working.mp4",
        ]
        assert len(fake.tasks) == 4 and len(fake.uploads) == 4
        # the clips reach the web through the files API, as video
        got = client.get(f"/api/files/{ev['clips']['idle']}")
        assert got.status_code == 200 and got.headers["content-type"].startswith("video/mp4")
        # the face was on before the clips were made
        assert client.get("/api/settings").json()["profile"]["avatar"] == ev["face"]
