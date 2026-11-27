"""The current and released Cloud media wire formats against an isolated Qianfan upstream."""

import base64
import json
import sqlite3

import httpx
import pytest
from test_cloud import APP_UA, sign_up

from nanomuse_cloud.api import create_app
from nanomuse_cloud.config import QIANFAN_IMAGE, QIANFAN_MODELS, QIANFAN_VIDEO, Settings
from nanomuse_cloud.db import Database
from nanomuse_cloud.qianfan_media import video_payload
from nanomuse_cloud.senders import LogSender
from nanomuse_cloud.service import Cloud, CloudError

BASE = "https://qianfan.baidubce.com/v2"
PHOTO = "https://materials.example/portrait.jpg"
AUDIO = "https://materials.example/voice.wav"
INPUT = {"model": QIANFAN_VIDEO, "prompt": "nod", "avatar_url": PHOTO, "reference_audio_url": AUDIO, "duration": 4}
VIDEO_ENDPOINT = "/api/v1/services/aigc/video-generation/video-synthesis"


@pytest.fixture
async def media_stack(monkeypatch):
    monkeypatch.setenv("QIANFAN_API_KEY", "test-upstream")
    requests = []
    responses = {}
    image_url = "http://qianfan-modelbuilder-img-gen.bj.bcebos.com/image.jpg?signature=fake"
    video_url = "http://qianfan-mm-router.bj.bcebos.com/clip.mp4?signature=fake"

    def respond(request):
        requests.append(request)
        if request.url.path in responses:
            return responses[request.url.path]
        if request.url.host == "qianfan-modelbuilder-img-gen.bj.bcebos.com":
            return httpx.Response(200, content=b"\xff\xd8\xffjpeg")
        if request.url.path == "/v2/musesteamer/images/generations":
            return httpx.Response(200, json={"data": [{"url": image_url}]})
        if request.url.path == "/v2/mm/ernie/ernie-wizshot-me":
            return httpx.Response(200, json={"task_id": "sample-task"})
        if request.url.path == "/v2/mm/ernie/tasks":
            return httpx.Response(
                200,
                json={
                    "task_id": "sample-task",
                    "status": "succeeded",
                    "content": {"video_url": video_url},
                    "usage": {"duration": 4.47, "resolution": "1080P"},
                },
            )
        raise AssertionError(f"unexpected request path {request.url.path}")

    s = Settings(
        database=":memory:",
        secret="test",
        models=QIANFAN_MODELS,
        upstream_base=BASE,
        upstream_key="test-upstream",
        media_enabled=True,
        allowance_cny=10,
        signup_tokens=50000,
    )
    sender = LogSender()
    cloud = Cloud(s, Database(":memory:"), sender)
    app = create_app(s, cloud, upstream_transport=httpx.MockTransport(respond))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://cloud.test", headers=APP_UA) as client:
        account = await sign_up(client, sender)
        headers = {"Authorization": "Bearer " + account["api_key"]}
        yield app, client, headers, cloud, requests, responses, sender
    cloud.db.close()


async def test_legacy_image_response_downloads_with_https_and_without_key(media_stack):
    _, client, headers, _, requests, _, _ = media_stack
    r = await client.post("/v1/images/generations", headers=headers, json={"model": QIANFAN_IMAGE, "prompt": "red cup", "size": "1280x720"})
    assert r.status_code == 200, r.text
    assert base64.b64decode(r.json()["data"][0]["b64_json"]) == b"\xff\xd8\xffjpeg"
    api, download = requests
    assert api.url == BASE + "/musesteamer/images/generations"
    assert api.headers["authorization"] == "Bearer test-upstream"
    assert json.loads(api.content) == {
        "model": QIANFAN_IMAGE,
        "prompt": "red cup",
        "size": "1280x720",
        "prompt_extend": False,
        "response_format": "url",
    }
    assert download.url.scheme == "https" and download.url.query == b"signature=fake"
    assert "authorization" not in download.headers


@pytest.mark.parametrize("url", ["https://unrelated.example/a", "https://qianfan-modelbuilder-img-gen.bj.bcebos.com.unrelated.example/a"])
async def test_image_refuses_unexpected_output_host(media_stack, url):
    _, client, headers, _, requests, responses, _ = media_stack
    responses["/v2/musesteamer/images/generations"] = httpx.Response(200, json={"data": [{"url": url}]})
    r = await client.post("/v1/images/generations", headers=headers, json={"model": QIANFAN_IMAGE, "prompt": "red cup"})
    assert r.status_code == 502
    assert len(requests) == 1


async def test_wizshot_known_task_ownership_and_actual_duration_charged_once(media_stack):
    app, client, headers, cloud, requests, responses, sender = media_stack
    r = await client.post("/v1/videos/generations", headers=headers, json=INPUT)
    assert r.status_code == 200, r.text
    assert r.json()["output"] == {"task_id": "sample-task", "task_status": "PENDING"}
    payload = json.loads(requests[0].content)
    assert payload["model"] == QIANFAN_VIDEO and "input" not in payload
    assert payload["personas"]["Speaker"]["mid"] == AUDIO
    assert payload["fragments"][0]["shots"][0]["camera_settings"]["shot_image"] == PHOTO
    assert cloud.db.video_task("sample-task")["cost_uy"] == 3_500_000
    path = "/api/v1/tasks/sample-task"
    other = await sign_up(client, sender, identifier="other@sample.test")
    assert (await client.get(path, headers={"Authorization": "Bearer " + other["api_key"]})).status_code == 404
    assert (await client.get(path)).status_code == 401
    assert len(requests) == 1
    responses["/v2/mm/ernie/tasks"] = httpx.Response(200, json={"status": "processing"})
    assert (await client.get(path, headers=headers)).json()["output"]["task_status"] == "RUNNING"
    assert not cloud.db.video_task("sample-task")["charged"]
    responses.clear()
    with cloud.db.tx() as c:
        c.execute("UPDATE video_tasks SET created_at=created_at-3010 WHERE task_id='sample-task'")
    assert await app.state.settle_video_tasks() == 1
    assert (await client.get(path, headers=headers)).json()["output"]["video_url"].startswith("https://qianfan-mm-router.")
    assert cloud.db.video_task("sample-task")["cost_uy"] == 3_129_000
    with cloud.db.tx() as c:
        assert c.execute("SELECT count(*), sum(cost_uy) FROM ledger WHERE kind='video'").fetchone()[:] == (1, 3_129_000)
    assert requests[-1].url.params.get("task_id") == "sample-task"


async def test_missing_materials_do_not_submit_and_edits_do_not_send_key_to_legacy_provider(media_stack):
    _, client, headers, cloud, requests, _, _ = media_stack
    r = await client.post(VIDEO_ENDPOINT, headers=headers, json={"model": QIANFAN_VIDEO, "input": {"prompt": "a clip"}})
    assert r.status_code == 400 and r.json()["error"]["code"] == "wizshot_materials_required"
    assert r.json()["error"]["open"] == "/app/?video=wizshot"
    r = await client.get("/api/v1/uploads", headers=headers, params={"model": QIANFAN_VIDEO, "action": "getPolicy"})
    assert r.status_code == 400
    r = await client.post(
        "/v1/images/edits",
        headers=headers,
        data={"model": QIANFAN_IMAGE, "prompt": "edit"},
        files={"image": ("img.jpg", b"test", "image/jpeg")},
    )
    assert r.status_code == 400 and r.json()["error"]["code"] == "image_edit_unsupported"
    assert not requests
    with cloud.db.tx() as c:
        assert c.execute("SELECT count(*) FROM ledger WHERE kind IN ('image','video')").fetchone()[0] == 0


@pytest.mark.parametrize(
    "result",
    [
        {"status": "succeeded", "content": {}},
        {"status": "succeeded", "content": {"video_url": "https://bogus.invalid/x.mp4"}},
        {"status": "almost_done"},
        {"status": "succeeded", "task_id": "different"},
        {"status": "processing", "task_id": "different"},
    ],
)
async def test_incomplete_or_unknown_task_result_is_not_success(media_stack, result):
    _, client, headers, cloud, _, responses, _ = media_stack
    assert (await client.post(VIDEO_ENDPOINT, headers=headers, json=INPUT)).status_code == 200
    responses["/v2/mm/ernie/tasks"] = httpx.Response(200, json=result)
    assert (await client.get("/api/v1/tasks/sample-task", headers=headers)).status_code == 502
    assert not cloud.db.video_task("sample-task")["charged"]


def test_native_and_spoken_wizshot_reservations():
    native, seconds = video_payload(INPUT)
    assert seconds == 5 and video_payload(native) == (native, 5)
    spoken = {**INPUT, "dialog": "words for the clip"}
    del spoken["duration"]
    payload, seconds = video_payload(spoken)
    assert seconds == 16 and "silence_duration" not in payload["fragments"][0]["shots"][0]["segments"][0]["production_elements"]
    for bad in [{"duration": 3}, {"duration": 17}, {"duration": True}, {"duration": float("nan")}, {"dialog": "words", "duration": 1}]:
        with pytest.raises(CloudError):
            video_payload({**INPUT, **bad})


async def test_failed_wizshot_includes_provider_code_and_releases_hold(media_stack):
    _, client, headers, cloud, _, responses, _ = media_stack
    assert (await client.post(VIDEO_ENDPOINT, headers=headers, json=INPUT)).status_code == 200
    responses["/v2/mm/ernie/tasks"] = httpx.Response(200, json={"status": "failed", "error": {"code": "invalid_video_generation_argument"}})
    r = await client.get("/api/v1/tasks/sample-task", headers=headers)
    assert r.status_code == 200
    assert r.json()["output"]["task_status"] == "FAILED"
    assert r.json()["output"]["code"] == "invalid_video_generation_argument"
    task = cloud.db.video_task("sample-task")
    assert task["status"] == "FAILED" and not task["charged"]
    assert cloud.db.pending_video_cost(task["account_id"]) == 0


@pytest.mark.parametrize(("usage", "charge"), [({"duration": 9, "resolution": "1080P"}, 3_500_000), ({}, 0)])
async def test_wizshot_charge_never_exceeds_hold_or_bills_an_unreported_duration(media_stack, usage, charge):
    _, client, headers, cloud, _, responses, _ = media_stack
    assert (await client.post("/v1/videos/generations", headers=headers, json=INPUT)).status_code == 200
    responses["/v2/mm/ernie/tasks"] = httpx.Response(
        200, json={"status": "succeeded", "content": {"video_url": "https://qianfan-mm-router.bj.bcebos.com/video.mp4"}, "usage": usage}
    )
    r = await client.get("/api/v1/tasks/sample-task", headers=headers)
    assert r.status_code == 200
    assert cloud.db.video_task("sample-task")["cost_uy"] == charge


async def test_failed_ledger_write_can_retry_wizshot_settlement(media_stack):
    _, client, headers, cloud, _, _, _ = media_stack
    assert (await client.post("/v1/videos/generations", headers=headers, json=INPUT)).status_code == 200
    task = cloud.db.video_task("sample-task")
    with cloud.db.tx() as c:
        c.execute("CREATE TRIGGER test_stop_charge BEFORE INSERT ON ledger BEGIN SELECT RAISE(ABORT, 'test'); END")

    with pytest.raises(sqlite3.IntegrityError):
        cloud.settle_video_task(task, "SUCCEEDED", cost_uy=3_000_000)
    assert not cloud.db.video_task("sample-task")["charged"]
    with cloud.db.tx() as c:
        c.execute("DROP TRIGGER test_stop_charge")
    assert (await client.get("/api/v1/tasks/sample-task", headers=headers)).status_code == 200
    assert cloud.db.video_task("sample-task")["charged"]
