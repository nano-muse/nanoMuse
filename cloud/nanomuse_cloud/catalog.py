"""The models under the operator's key, read from the provider — for members to pick from.

A member may name any model of the right kind (config.unlisted_model); until 0.10 they had to
know the id and type it. The relay now asks the provider's own ``GET /models`` (the
OpenAI-shaped list every compatible endpoint has) with the operator's key, sorts what comes
back into chat, image and video by the shape of the id, and lists the usable ones in
``GET /v1/models`` for members after the menu, marked ``listed: false`` and ``catalog: true``
— so the apps' pickers show them and the person chooses rather than types.

What the provider lists carries no modalities (``id``, ``object``, ``owned_by`` and a date), so
the first sorting is by name: ``image`` in the id is a picture model, ``t2v``/``i2v`` and their
kin a clip model, speech / transcription / embedding / reranking / live-translation ids are
left out (they do not answer chat completions), everything else is a chat model, with a
vision hint for the families known to read pictures.

Names lie, though — DeepSeek V4.1 on Model Studio reads pictures and V4 does not, half the
``qwen-*`` ids are retired and answer 4xx — so since 0.11 the relay *asks each chat model*
once (``probe``): a
one-word text request, and if that is answered, a one-word question about a small red
picture. A model that refuses the text request is left off the list; one that names the
colour is marked as reading pictures (``input_modalities`` carries ``image``), one that does
not is marked text-only. The answers are kept in the database for ``CLOUD_CATALOG_PROBE_TTL_S``
(a week) and the probing runs in the background after each refresh of the list, a few models
at a time, so no request waits for it. ``CLOUD_CATALOG_PROBE=0`` leaves the names to speak for
themselves, as before. A wrong guess still costs nothing: the kind is checked again when the
model is used, and an id a member types works as before.

Cached for ``CLOUD_CATALOG_TTL_S`` (an hour); a provider that does not answer leaves the last
good list in place, or none. ``CLOUD_CATALOG=0`` switches the whole thing off.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
import time
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from typing import Protocol

import httpx

from .config import MODEL_ID_RE, positive_capacity

log = logging.getLogger("nanomuse_cloud.catalog")

# ids that are not chat, picture or clip models — spoken, heard, embedded, translated live
_NOT_FOR_US = re.compile(
    r"(^|[-/_.])(tts|asr|speech|audio|realtime|s2s|livetranslate|embedding|rerank|omni|sambert|"
    r"cosyvoice|paraformer|sensevoice|whisper|sre-gpu|voice|vc|vd)([-/_.]|$)"
)
_VIDEO = re.compile(r"(^|[-/_.])(t2v|i2v|kf2v|s2v|r2v|v2v|video|animate|seedance|veo|sora)([-/_.]|$)")
_IMAGE = re.compile(r"(^|[-/_.])(image|t2i|i2i|seedream|flux|stable-diffusion|sdxl|dall-e|imagen|z-image)([-/_.]|$)|image")
# chat models known to read pictures: the VL and QVQ lines, OCR, the GUI model, the Qwen
# generations that are multimodal from the start (3.5 on), Kimi K2.5 on, DeepSeek from
# V4.1 on (checked on Model Studio: v4.1-flash answers about a picture, v4-flash and
# v4-pro do not — they guess or return nothing), GPT-4o/5, Gemini, Claude — the guess
# before the probe answers
_VISION = re.compile(
    r"(^|[-/_.])(vl|qvq|vision|ocr|gui|gpt-4o|gpt-5|gemini|claude|kimi-k2\.[5-9]|kimi-k[3-9])([-/_.]|$)"
    r"|qwen3\.[5-9]|qwen[4-9]|deepseek-v4\.[1-9]|deepseek-v[5-9]"
)

# the probe: one word back, and the colour of a 32×32 magenta square (a PNG of 97 bytes).
# Magenta, not red: a model that cannot see guesses, and "red" is the guess it makes most —
# a 1.5B text model passed the red square on the first run. Nobody guesses magenta.
PROBE_TEXT = "Reply with the single word OK."
PROBE_PICTURE_QUESTION = "What colour is this picture? Answer with one word."
_PROBE_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAIAAAD8GO2jAAAAKElEQVR42u3NQQEAAAQEsKN/Z0rw2wqsJpNPnWcCgUAgEAgEAoHgygK1WwI+eS9jvgAAAABJRU5ErkJggg=="
)
_SEEN_WORDS = re.compile(r"magenta|fuchsia|purple|violet|pink|品红|洋红|紫|粉", re.IGNORECASE)
PROBE_TIMEOUT_S = 30.0
PROBE_CONCURRENCY = 3


def classify(model_id: str) -> tuple[str, bool]:
    """The kind of model an id names — ``chat``, ``image``, ``video`` or ``other`` — and, for
    chat, whether it is known to read pictures."""
    mid = model_id.strip().lower()
    if not mid or not MODEL_ID_RE.match(model_id.strip()):
        return "other", False
    bare = mid.rsplit("/", 1)[-1]  # a vendor prefix (``vanchin/deepseek-v3``) says nothing of the kind
    if _VIDEO.search(bare):
        return "video", False
    if _IMAGE.search(bare):
        return "image", False
    if _NOT_FOR_US.search(bare):
        return "other", False
    return "chat", bool(_VISION.search(bare))


@dataclass
class Entry:
    id: str
    kind: str
    vision: bool = False
    verified: bool = False  # the vision flag comes from the probe, not the name
    context_length: int | None = None
    max_output_tokens: int | None = None


@dataclass
class Probe:
    """What one chat model answered: whether it answers at all, whether it saw the picture."""

    model_id: str
    works: bool
    vision: bool
    checked_at: int
    note: str = ""


class ProbeStore(Protocol):
    """Where the probes are kept between restarts (db.py)."""

    def probes(self) -> list[Probe]: ...

    def save_probe(self, probe: Probe) -> None: ...


def _message_text(obj: object) -> str:
    if not isinstance(obj, dict):
        return ""
    for ch in obj.get("choices") or []:
        msg = ch.get("message") if isinstance(ch, dict) else None
        if isinstance(msg, dict):
            content = msg.get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                return " ".join(str(p.get("text") or "") for p in content if isinstance(p, dict))
    return ""


def _error_text(r: httpx.Response) -> str:
    try:
        obj = r.json()
        err = obj.get("error") if isinstance(obj, dict) else None
        if isinstance(err, dict):
            return " ".join(str(err.get("message") or err.get("code") or "").split())[:200]
    except ValueError:
        pass
    return f"HTTP {r.status_code}"


@dataclass
class Catalog:
    """The provider's list, sorted and cached; one fetch at a time; probed in the background."""

    ttl_s: int = 3600
    probe_ttl_s: int = 7 * 86400
    store: ProbeStore | None = None  # None: no probing, the names speak for themselves
    entries: list[Entry] = field(default_factory=list)
    fetched_at: float = 0.0
    error: str = ""
    _raw: list[Entry] = field(default_factory=list)  # the sorted list before the probes have their say
    _probes: dict[str, Probe] = field(default_factory=dict)
    _loaded: bool = False
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _probing: asyncio.Task | None = None

    @property
    def fresh(self) -> bool:
        return bool(self.fetched_at) and time.time() - self.fetched_at < self.ttl_s

    @property
    def probing(self) -> bool:
        return self._probing is not None and not self._probing.done()

    @property
    def probes(self) -> dict[str, Probe]:
        self._load()
        return self._probes

    def _load(self) -> None:
        if self._loaded or self.store is None:
            return
        self._loaded = True
        try:
            self._probes = {p.model_id: p for p in self.store.probes()}
        except Exception as exc:  # noqa: BLE001 — a database that cannot be read leaves the names
            log.warning("catalog: the probes could not be read (%s)", exc)

    async def get(self, http: httpx.AsyncClient, base: str, key: str) -> list[Entry]:
        """The usable models under the key, from the cache when it is fresh."""
        if self.fresh:
            return self.entries
        async with self._lock:
            # another request may have refreshed it while this one waited for the lock
            if not self.fresh:
                await self._refresh(http, base, key)
        if self.store is not None and self._raw and not self.probing:
            self._probing = asyncio.create_task(self.probe(http, base, key))
        return self.entries

    async def _refresh(self, http: httpx.AsyncClient, base: str, key: str) -> None:
        if not base or not key:
            self.error = "upstream_unconfigured"
            self.fetched_at = time.time()  # do not ask again for a while
            return
        try:
            r = await http.get(f"{base.rstrip('/')}/models", headers={"Authorization": f"Bearer {key}"}, timeout=10.0)
            r.raise_for_status()
            data = r.json()
        except (httpx.HTTPError, ValueError) as exc:
            # the last good list stands; a provider that is down is asked again in a tenth of the time
            self.error = type(exc).__name__
            self.fetched_at = time.time() - self.ttl_s * 0.9
            log.info("catalog: the provider's /models did not answer (%s); %d models kept", self.error, len(self.entries))
            return
        rows = data.get("data") if isinstance(data, dict) else data
        by_id = {str(m.get("id") or ""): m for m in rows if isinstance(m, dict)} if isinstance(rows, list) else {}
        ids = sorted(by_id)
        out: list[Entry] = []
        for mid in ids:
            kind, vision = classify(mid)
            if kind != "other":
                row = by_id[mid]
                top = row.get("top_provider")
                top = top if isinstance(top, dict) else {}
                out.append(
                    Entry(
                        id=mid,
                        kind=kind,
                        vision=vision,
                        context_length=positive_capacity(row.get("context_length")),
                        max_output_tokens=positive_capacity(row.get("max_output_tokens"))
                        or positive_capacity(top.get("max_completion_tokens")),
                    )
                )
        self._raw = out
        self._apply()
        self.error = ""
        self.fetched_at = time.time()
        log.info("catalog: %d models under the key, %d usable", len(ids), len(self.entries))

    def _apply(self) -> None:
        """The list the members see: the names' sorting, corrected by what the probes found —
        a model that does not answer is left off, the vision flag is the probe's."""
        self._load()
        out: list[Entry] = []
        for e in self._raw:
            p = self._probes.get(e.id) if e.kind == "chat" else None
            if p is None:
                out.append(replace(e))
            elif p.works:
                out.append(replace(e, vision=p.vision, verified=True))
        self.entries = out

    def _stale(self, entries: Iterable[Entry]) -> list[Entry]:
        self._load()
        cutoff = time.time() - self.probe_ttl_s
        return [e for e in entries if e.kind == "chat" and (e.id not in self._probes or self._probes[e.id].checked_at < cutoff)]

    async def probe(self, http: httpx.AsyncClient, base: str, key: str) -> int:
        """Ask every chat model the probes have no fresh word on; a few at a time. Returns
        how many were asked. A model that does not answer at all (timeout, 5xx) is asked
        again next time; only a 4xx — the provider's "no" — is written down."""
        todo = self._stale(self._raw)
        if not todo:
            return 0
        sem = asyncio.Semaphore(PROBE_CONCURRENCY)
        asked = 0

        async def one(entry: Entry) -> None:
            nonlocal asked
            async with sem:
                probe = await probe_model(http, base, key, entry.id)
            if probe is None:
                return
            asked += 1
            self._probes[entry.id] = probe
            if self.store is not None:
                try:
                    self.store.save_probe(probe)
                except Exception as exc:  # noqa: BLE001 — the answer still serves this run
                    log.warning("catalog: probe of %s not saved (%s)", entry.id, exc)

        await asyncio.gather(*(one(e) for e in todo))
        self._apply()
        seen = [p for p in self._probes.values() if p.model_id in {e.id for e in self._raw}]
        log.info(
            "catalog: probed %d models; %d answer, %d of them read pictures, %d do not answer",
            asked,
            sum(1 for p in seen if p.works),
            sum(1 for p in seen if p.works and p.vision),
            sum(1 for p in seen if not p.works),
        )
        return asked

    def summary(self) -> dict:
        """For the admin page: what the key has, and what the probes said."""
        self._load()
        raw_ids = {e.id for e in self._raw}
        refused = sorted((p for p in self._probes.values() if p.model_id in raw_ids and not p.works), key=lambda p: p.model_id)
        unusable = [{"id": p.model_id, "note": p.note, "checked_at": p.checked_at} for p in refused]
        return {
            "fetched_at": int(self.fetched_at) if self.fetched_at else None,
            "error": self.error,
            "probing": self.probing,
            "models": [{"id": e.id, "kind": e.kind, "vision": e.vision, "verified": e.verified} for e in self.entries],
            "unusable": unusable,
            "pending": len(self._stale(self._raw)),
        }


async def probe_model(http: httpx.AsyncClient, base: str, key: str, model_id: str) -> Probe | None:
    """Two small requests to one chat model. None when the provider did not answer (the
    question stays open); a Probe otherwise — `works` false on a 4xx, `vision` from whether
    the model named the colour of the magenta square."""
    url = f"{base.rstrip('/')}/chat/completions"
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    async def ask(messages: list[dict], thinking_off: bool) -> httpx.Response | None:
        body: dict = {"model": model_id, "messages": messages, "max_tokens": 16}
        if thinking_off:
            body["enable_thinking"] = False
        try:
            return await http.post(url, headers=headers, content=json.dumps(body).encode(), timeout=PROBE_TIMEOUT_S)
        except httpx.HTTPError as exc:
            log.debug("catalog: probe of %s did not get through (%s)", model_id, type(exc).__name__)
            return None

    r = await ask([{"role": "user", "content": PROBE_TEXT}], thinking_off=True)
    if r is not None and r.status_code == 400 and "thinking" in _error_text(r).lower():
        r = await ask([{"role": "user", "content": PROBE_TEXT}], thinking_off=False)  # a thinking-only model
    # 5xx and 429 (the key's rate, not the model) say nothing about the model: ask again later
    if r is None or r.status_code >= 500 or r.status_code == 429:
        return None
    checked = int(time.time())
    if r.status_code >= 400:
        return Probe(model_id=model_id, works=False, vision=False, checked_at=checked, note=_error_text(r))
    picture = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": PROBE_PICTURE_QUESTION},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(_PROBE_PNG).decode()}},
            ],
        }
    ]
    p = await ask(picture, thinking_off=True)
    if p is None or p.status_code >= 500 or p.status_code == 429:
        return None  # the first half was answered, but the question of pictures stays open
    if p.status_code >= 400:
        return Probe(model_id=model_id, works=True, vision=False, checked_at=checked, note=_error_text(p))
    try:
        answer = _message_text(p.json())
    except ValueError:
        answer = ""
    return Probe(model_id=model_id, works=True, vision=bool(_SEEN_WORDS.search(answer)), checked_at=checked, note=answer.strip()[:60])
