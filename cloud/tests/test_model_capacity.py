"""Capacity belongs to the served route, never its billing reference."""

import dataclasses
import time

import httpx
import pytest
from test_cloud import make_stack, sign_up

from nanomuse_cloud.catalog import Catalog, Entry, Probe
from nanomuse_cloud.config import ModelSpec, Settings


@pytest.mark.asyncio
async def test_login_list_and_single_model_publish_the_same_capacity():
    model = ModelSpec("test-chat", "Test", "test-chat", context_length=98304, max_output_tokens=4096)
    _, client, sender, _, _ = make_stack(models=(model,), catalog_enabled=False)
    async with client:
        signed = await sign_up(client, sender, identifier="capacity@example.org")
        headers = {"Authorization": f"Bearer {signed['api_key']}"}
        listed = (await client.get("/v1/models", headers=headers)).json()["data"][0]
        single = (await client.get("/v1/models/test-chat", headers=headers)).json()
        assert signed["models"][0] == listed == single
        assert listed["context_length"] == 98304
        assert listed["max_output_tokens"] == 4096


@pytest.mark.asyncio
async def test_discovered_model_has_the_same_capacity_in_list_and_lookup():
    app, client, sender, _, _ = make_stack(allowed_identifiers="capacity@example.org")
    catalog = app.state.catalog
    catalog.store = None
    catalog.entries = [Entry("extra-chat", "chat", context_length=98304, max_output_tokens=4096)]
    catalog.fetched_at = time.time()
    async with client:
        signed = await sign_up(client, sender, identifier="capacity@example.org")
        headers = {"Authorization": f"Bearer {signed['api_key']}"}
        listed = (await client.get("/v1/models", headers=headers)).json()["data"]
        extra = next(m for m in listed if m["id"] == "extra-chat")
        single = (await client.get("/v1/models/extra-chat?kind=chat", headers=headers)).json()
        assert single["context_length"] == extra["context_length"] == 98304
        assert single["max_output_tokens"] == extra["max_output_tokens"] == 4096


def test_public_capacity_is_optional_and_not_borrowed_for_billing():
    model = ModelSpec("test-chat", "Test", "test-chat", context_length=98304, max_output_tokens=4096)
    assert model.to_public()["context_length"] == 98304
    assert model.to_public()["max_output_tokens"] == 4096
    unknown = Settings(models=(model,)).unlisted_model("other-chat", "chat")
    assert unknown.priced_as == model.id
    assert "context_length" not in unknown.to_public()
    assert "max_output_tokens" not in unknown.to_public()


@pytest.mark.parametrize("value", [True, 0, -1, 1.5, "8192", 2**31])
@pytest.mark.parametrize("field", ["context_length", "max_output_tokens"])
def test_config_rejects_invalid_capacity(field, value):
    with pytest.raises(ValueError, match=field):
        ModelSpec("test-chat", "Test", "test-chat", **{field: value})


@pytest.mark.asyncio
async def test_discovery_and_vision_probe_preserve_capacity():
    async def upstream(request):
        return httpx.Response(
            200,
            json={
                "data": [
                    {"id": "test-chat", "context_length": 98304, "max_output_tokens": 4096},
                    {"id": "unknown-chat", "context_length": True, "max_output_tokens": -1},
                    {"id": "router-chat", "context_length": 131072, "top_provider": {"max_completion_tokens": 8192}},
                ]
            },
        )

    catalog = Catalog()
    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
        entries = await catalog.get(client, "https://provider.invalid/v1", "test-key")
    known = next(e for e in entries if e.id == "test-chat")
    assert known.context_length == 98304
    assert known.max_output_tokens == 4096
    unknown = next(e for e in entries if e.id == "unknown-chat")
    assert unknown.context_length is None and unknown.max_output_tokens is None
    router = next(e for e in entries if e.id == "router-chat")
    assert router.context_length == 131072
    assert router.max_output_tokens == 8192
    catalog._probes[known.id] = Probe(known.id, True, True, 0)
    catalog._apply()
    probed = next(e for e in catalog.entries if e.id == known.id)
    assert dataclasses.replace(probed, vision=known.vision, verified=known.verified) == known
