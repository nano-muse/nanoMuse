"""What the coding agents leave on disk, read without asking them.

Cursor
    IDE and CLI chats are transcribed to
    ``~/.cursor/projects/<slug>/agent-transcripts/<id>/<id>.jsonl`` (one JSON object a
    line: ``{"role": "user"|"assistant", "message": {"content": [{"type": "text", ...}]}}``,
    ``{"type": "turn_ended"}``); ``<slug>`` is the workspace path with ``/`` turned into
    ``-`` (on Windows ``C:\\Users\\me\\app`` becomes ``C-Users-me-app``). CLI chats also have ``~/.cursor/chats/<hash>/<id>/meta.json`` with the ``cwd``.
Codex
    ``~/.codex/sessions/YYYY/MM/DD/rollout-<time>-<id>.jsonl``: a ``session_meta`` line
    (id, cwd, originator), ``response_item`` messages (``payload.role`` user / assistant,
    ``payload.content[].text``) and ``event_msg`` lines (``task_started`` / ``task_complete``).
Claude Code
    ``~/.claude/projects/<slug>/<id>.jsonl``: ``{"type": "user"|"assistant", "message":
    {"role", "content"}, "timestamp", "cwd", "sessionId"}``.
dsh (DeepSeek Harness)
    ``~/.dsh/sessions/<slug>/<id>/session.v4.jsonl.zstd``: the harness's own store, one
    zstd-compressed JSON object a line. A ``session`` header (``{id, createdAt, cwd}``),
    ``user/message`` and ``assistant/message`` events, tools as ``tool/call`` +
    ``tool/result``, and ``<id>`` is the session id itself. The file is many zstd frames
    appended as the session is written, so it is read frame by frame.

Everything here is read-only and best effort: a line that does not parse is skipped, a
missing directory is an agent with no sessions.
"""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nanomuse.stdio import decode_output

# The agents nanoMuse knows how to read and drive; `bins` are tried in order.
AGENTS: dict[str, dict[str, Any]] = {
    "cursor": {
        "name": "Cursor",
        "bins": ("cursor-agent", "agent"),
        "process": ("cursor-agent", "cursor"),
    },
    "codex": {"name": "Codex", "bins": ("codex",), "process": ("codex",)},
    "claude": {"name": "Claude Code", "bins": ("claude",), "process": ("claude",)},
    "dsh": {"name": "DeepSeek Harness", "bins": ("dsh",), "process": ("dsh",)},
}

# A session whose transcript changed this recently is "active" (the agent is working or
# the person is typing); newer than RUNNING_S with an open turn is "running".
ACTIVE_S = 180
RUNNING_S = 45
TAG_RE = re.compile(
    r"<(timestamp|system_reminder|system-reminder|attached_files|user_info|git_status|environment_context|app-context|multi_agent_role|permissions[^>]*)>.*?</\1>",
    re.S,
)
USER_QUERY_RE = re.compile(r"<user_query>(.*?)</user_query>", re.S)


@dataclass
class AgentInfo:
    id: str
    name: str
    installed: bool
    cli: str | None
    version: str = ""
    sessions_root: str = ""
    running: int = 0  # processes alive right now

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "installed": self.installed,
            "cli": self.cli,
            "version": self.version,
            "sessions_root": self.sessions_root,
            "running": self.running,
        }


@dataclass
class Session:
    agent: str
    id: str
    title: str
    workspace: str
    path: str
    created_at: float
    updated_at: float
    messages: int = 0
    status: str = "idle"  # idle | active | running
    last_user: str = ""
    last_assistant: str = ""
    source: str = ""  # cursor: ide | cli; codex: originator; claude: -
    resumable: bool = True
    transcript: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self, with_transcript: bool = False) -> dict[str, Any]:
        d = {
            "agent": self.agent,
            "id": self.id,
            "title": self.title,
            "workspace": self.workspace,
            "path": self.path,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "messages": self.messages,
            "status": self.status,
            "last_user": self.last_user,
            "last_assistant": self.last_assistant,
            "source": self.source,
            "resumable": self.resumable,
        }
        if with_transcript:
            d["transcript"] = self.transcript
        return d


# ---------------------------------------------------------------------- detection
def home() -> Path:
    return Path(os.environ.get("NANOMUSE_CODING_HOME") or Path.home())


def which(agent: str) -> str | None:
    for b in AGENTS[agent]["bins"]:
        p = shutil.which(b)
        if p:
            return p
    return None


def version_of(cli: str) -> str:
    try:
        out = subprocess.run([cli, "--version"], capture_output=True, text=True, timeout=8)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    text = (out.stdout or out.stderr or "").strip().splitlines()
    return text[0][:60] if text else ""


def running_processes(agent: str) -> int:
    """How many processes of that agent are alive right now. Linux reads /proc; macOS asks
    `ps` once for every process; Windows `tasklist` (and, for the node-bundled Cursor CLI,
    the command lines of node.exe). Never `pgrep -f`, whose match would include our own
    command line. The process table is read once per call for all agents and kept two
    seconds, since the apps ask about the three agents together."""
    return _process_table().get(agent, 0)


_PROCESS_CACHE: tuple[float, dict[str, int]] = (0.0, {})


def _process_table() -> dict[str, int]:
    global _PROCESS_CACHE
    at, counts = _PROCESS_CACHE
    if time.time() - at < 2.0:
        return counts
    counts = {aid: 0 for aid in AGENTS}
    for comm, argv in _processes():
        base = os.path.basename(comm).lower()
        if base.endswith(".exe"):
            base = base[:-4]
        for aid, spec in AGENTS.items():
            if base in spec["process"]:
                counts[aid] += 1
                break
        else:
            # the Cursor CLI is a node bundle: its name is "node"; look at the argv
            if base in ("node", "node.exe") and "cursor-agent" in argv:
                counts["cursor"] += 1
    _PROCESS_CACHE = (time.time(), counts)
    return counts


def _processes() -> list[tuple[str, str]]:
    """(executable name, first arguments) of every process, the platform's way."""
    plat = sys.platform  # through a name: mypy would otherwise drop the other platforms' branches
    if plat.startswith("linux"):
        out: list[tuple[str, str]] = []
        proc = Path("/proc")
        if not proc.is_dir():
            return out
        for p in proc.iterdir():
            if not p.name.isdigit():
                continue
            try:
                comm = (p / "comm").read_text().strip()
                argv = b" ".join((p / "cmdline").read_bytes().split(b"\0")[:3]).decode(
                    "utf-8", "replace"
                )
            except (OSError, UnicodeDecodeError):
                continue
            out.append((comm, argv))
        return out
    if plat == "darwin":
        try:
            ps = subprocess.run(
                ["ps", "-axo", "comm=,args="], capture_output=True, text=True, timeout=8
            )
        except (OSError, subprocess.TimeoutExpired):
            return []
        rows = []
        for line in ps.stdout.splitlines():
            parts = line.strip().split(None, 1)
            if parts:
                rows.append((parts[0], " ".join(parts[1].split()[:3]) if len(parts) > 1 else ""))
        return rows
    if plat == "win32":
        try:
            tl = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, timeout=8)
        except (OSError, subprocess.TimeoutExpired):
            return []
        rows = []
        node_lines: list[str] | None = None
        for line in decode_output(tl.stdout).splitlines():
            name = line.split('","', 1)[0].strip('" ')
            if not name:
                continue
            argv = ""
            if name.lower() == "node.exe":
                if node_lines is None:
                    node_lines = _windows_node_command_lines()
                argv = node_lines.pop(0) if node_lines else ""
            rows.append((name, argv))
        return rows
    return []


def _windows_node_command_lines() -> list[str]:
    """The command lines of the node.exe processes (tasklist has none); one PowerShell call."""
    try:
        ps = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-CimInstance Win32_Process -Filter \"Name='node.exe'\" | ForEach-Object { $_.CommandLine }",
            ],
            capture_output=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [line.strip() for line in decode_output(ps.stdout).splitlines() if line.strip()]


def sessions_root(agent: str) -> Path:
    h = home()
    return {
        "cursor": h / ".cursor" / "projects",
        "codex": h / ".codex" / "sessions",
        "claude": h / ".claude" / "projects",
        "dsh": h / ".dsh" / "sessions",
    }[agent]


def detect(with_versions: bool = False) -> list[AgentInfo]:
    out = []
    for aid, spec in AGENTS.items():
        cli = which(aid)
        root = sessions_root(aid)
        has_data = root.is_dir()
        info = AgentInfo(
            id=aid,
            name=spec["name"],
            installed=bool(cli) or has_data,
            cli=cli,
            version=version_of(cli) if (cli and with_versions) else "",
            sessions_root=str(root) if has_data else "",
            running=running_processes(aid) if (cli or has_data) else 0,
        )
        out.append(info)
    return out


# ---------------------------------------------------------------------- transcripts
def _clean(text: str) -> str:
    """A user message as the person typed it: the IDE's wrapper tags stripped."""
    if not text:
        return ""
    m = USER_QUERY_RE.search(text)
    if m:
        text = m.group(1)
    text = TAG_RE.sub("", text)
    text = re.sub(r"<[a-z_-]+>\s*</[a-z_-]+>", "", text)
    return text.strip()


def _title(text: str, limit: int = 80) -> str:
    line = " ".join(text.split())
    return line if len(line) <= limit else line[: limit - 1] + "…"


def _is_dir(path: str) -> bool:
    try:
        return os.path.isdir(path)
    except (OSError, ValueError):
        return False


def _slug_to_path(
    slug: str, platform: str | None = None, is_dir: Callable[[str], bool] = _is_dir
) -> str:
    """``ssd-code-appagent-openmuse`` → ``/ssd/code/appagent/openmuse`` when such a
    directory exists; hyphenated names are tried as one component when the split does not
    exist. Falls back to the slug itself.

    On Windows the slug starts with the drive: Cursor drops the colon (``C:\\Users\\me\\app``
    → ``C-Users-me-app``), Claude Code turns it into a dash too (``C--Users-me-app``), and
    either may lower-case the letter. Both read back as ``C:\\Users\\me\\app``. ``platform``
    and ``is_dir`` are taken so the tests can run both shapes on every OS."""
    platform = platform or sys.platform
    parts = slug.split("-")
    sep = "\\" if platform == "win32" else "/"
    path = ""
    i = 0
    if platform == "win32" and len(parts) > 1 and re.fullmatch(r"[A-Za-z]", parts[0]):
        path = parts[0].upper() + ":"
        i = 2 if parts[1] == "" else 1
    start = i
    while i < len(parts):
        # the longest run of parts (joined with "-") that is an existing directory
        chosen = None
        for j in range(len(parts), i, -1):
            candidate = path + sep + "-".join(parts[i:j])
            if is_dir(candidate):
                chosen = (candidate, j)
                break
        if chosen is None:
            return path + sep + "-".join(parts[i:]) if i > start else slug
        path, i = chosen
    return path if i > start else slug


def _status(updated_at: float, open_turn: bool) -> str:
    age = time.time() - updated_at
    if open_turn and age < RUNNING_S * 4:
        return "running"
    if age < ACTIVE_S:
        return "active"
    return "idle"


def _read_lines(path: Path, limit_bytes: int = 64 * 1024 * 1024) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        if path.stat().st_size > limit_bytes:
            return out
        with path.open("rb") as f:
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    obj = json.loads(raw)
                except ValueError:
                    continue
                if isinstance(obj, dict):
                    out.append(obj)
    except OSError:
        pass
    return out


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for c in content:
            if isinstance(c, dict):
                if c.get("type") in ("text", "input_text", "output_text") and c.get("text"):
                    parts.append(str(c["text"]))
                elif c.get("type") == "tool_use":
                    parts.append(f"[tool: {c.get('name', '')}]")
        return "\n".join(parts)
    return ""


# -- Cursor --------------------------------------------------------------------------------
def _cursor_sessions(limit: int, workspace: str | None) -> list[Session]:
    root = sessions_root("cursor")
    if not root.is_dir():
        return []
    files: list[tuple[float, Path, str]] = []
    for project in root.iterdir():
        tdir = project / "agent-transcripts"
        if not tdir.is_dir():
            continue
        ws = _slug_to_path(project.name)
        if workspace and os.path.realpath(ws) != os.path.realpath(workspace):
            continue
        for sdir in tdir.iterdir():
            f = sdir / f"{sdir.name}.jsonl" if sdir.is_dir() else sdir
            if f.suffix == ".jsonl" and f.is_file():
                try:
                    files.append((f.stat().st_mtime, f, ws))
                except OSError:
                    continue
    files.sort(key=lambda t: -t[0])
    cli_meta = _cursor_cli_meta()
    out = []
    for _mtime, f, ws in files[:limit]:
        s = _cursor_session(f, ws, cli_meta, full=False)
        if s is not None:
            out.append(s)
    return out


def _cursor_cli_meta() -> dict[str, dict[str, Any]]:
    """CLI chats by id: their cwd and times (`~/.cursor/chats/<hash>/<id>/meta.json`)."""
    root = home() / ".cursor" / "chats"
    out: dict[str, dict[str, Any]] = {}
    if not root.is_dir():
        return out
    for h in root.iterdir():
        if not h.is_dir():
            continue
        for c in h.iterdir():
            meta = c / "meta.json"
            if meta.is_file():
                try:
                    out[c.name] = json.loads(meta.read_text("utf-8"))
                except (OSError, ValueError):
                    continue
    return out


def _cursor_session(
    f: Path, ws: str, cli_meta: dict[str, dict[str, Any]], full: bool
) -> Session | None:
    lines = _read_lines(f)
    sid = f.stem
    try:
        st = f.stat()
    except OSError:
        return None
    transcript: list[dict[str, Any]] = []
    first_user = ""
    last_user = last_assistant = ""
    open_turn = False
    n = 0
    for obj in lines:
        role = obj.get("role")
        if role in ("user", "assistant"):
            msg = obj.get("message") or {}
            text = _text_of(msg.get("content")) if isinstance(msg, dict) else ""
            if role == "user":
                text = _clean(text)
                if not text:
                    continue
                first_user = first_user or text
                last_user = text
                open_turn = True
            else:
                text = text.strip()
                if not text:
                    continue
                last_assistant = text
            n += 1
            if full:
                transcript.append({"role": role, "text": text})
        elif obj.get("type") == "turn_ended":
            open_turn = False
    meta = cli_meta.get(sid) or {}
    created = float(meta.get("createdAtMs", 0) or 0) / 1000 or st.st_ctime
    workspace = str(meta.get("cwd") or ws)
    if full:
        transcript = transcript[-400:]
    return Session(
        agent="cursor",
        id=sid,
        title=_title(first_user) or "Untitled chat",
        workspace=workspace,
        path=str(f),
        created_at=created,
        updated_at=st.st_mtime,
        messages=n,
        status=_status(st.st_mtime, open_turn),
        last_user=_title(last_user, 160),
        last_assistant=_title(last_assistant, 160),
        source="cli" if sid in cli_meta else "ide",
        # the CLI resumes its own chats by id. An IDE chat it cannot reopen: a message sent
        # there starts a fresh CLI chat in the same workspace with the last exchange quoted
        # (the runner does this at once rather than trying and failing first)
        resumable=sid in cli_meta,
        transcript=transcript,
    )


# -- Codex -------------------------------------------------------------------------------
def _codex_files(limit: int, workspace: str | None = None) -> list[Path]:
    root = sessions_root("codex")
    if not root.is_dir():
        return []
    files: list[tuple[float, Path]] = []
    for f in root.rglob("rollout-*.jsonl"):
        try:
            files.append((f.stat().st_mtime, f))
        except OSError:
            continue
    files.sort(key=lambda t: -t[0])
    # A filtered list may need to pass many newer transcripts from other workspaces.
    # The session reader below uses the transcript's cwd before counting toward limit.
    candidates = files if workspace else files[: max(limit * 3, 30)]
    return [f for _, f in candidates]


def _codex_session(f: Path, full: bool) -> Session | None:
    lines = _read_lines(f)
    try:
        st = f.stat()
    except OSError:
        return None
    sid = ""
    cwd = ""
    originator = ""
    created = st.st_ctime
    first_user = last_user = last_assistant = ""
    open_turn = False
    n = 0
    transcript: list[dict[str, Any]] = []
    for obj in lines:
        t = obj.get("type")
        payload = obj.get("payload") or {}
        if t == "session_meta" and isinstance(payload, dict):
            sid = str(payload.get("id") or payload.get("session_id") or "")
            cwd = str(payload.get("cwd") or "")
            originator = str(payload.get("originator") or payload.get("source") or "")
            ts = payload.get("timestamp")
            if isinstance(ts, str):
                created = _iso_to_ts(ts) or created
        elif (
            t == "response_item" and isinstance(payload, dict) and payload.get("type") == "message"
        ):
            role = payload.get("role")
            text = _text_of(payload.get("content"))
            if role == "user":
                text = _clean(text)
                if not text or text.startswith("<"):
                    continue
                first_user = first_user or text
                last_user = text
            elif role == "assistant":
                text = text.strip()
                if not text:
                    continue
                last_assistant = text
            else:
                continue
            n += 1
            if full:
                transcript.append({"role": role, "text": text})
        elif t == "event_msg" and isinstance(payload, dict):
            k = payload.get("type")
            if k == "task_started":
                open_turn = True
            elif k in ("task_complete", "turn_aborted", "error"):
                open_turn = False
            elif k == "agent_message" and full and payload.get("message"):
                # newer rollouts carry the assistant's final text here too; keep one copy
                pass
    if not sid:
        m = re.search(r"-([0-9a-f-]{36})\.jsonl$", f.name)
        sid = m.group(1) if m else f.stem
    if full:
        transcript = transcript[-400:]
    return Session(
        agent="codex",
        id=sid,
        title=_title(first_user) or "Untitled thread",
        workspace=cwd,
        path=str(f),
        created_at=created,
        updated_at=st.st_mtime,
        messages=n,
        status=_status(st.st_mtime, open_turn),
        last_user=_title(last_user, 160),
        last_assistant=_title(last_assistant, 160),
        source=originator,
        transcript=transcript,
    )


def _codex_sessions(limit: int, workspace: str | None) -> list[Session]:
    out = []
    for f in _codex_files(limit, workspace):
        s = _codex_session(f, full=False)
        if s is None or (
            workspace and os.path.realpath(s.workspace or "") != os.path.realpath(workspace)
        ):
            continue
        out.append(s)
        if len(out) >= limit:
            break
    return out


# -- Claude Code ------------------------------------------------------------------------------
def _claude_sessions(limit: int, workspace: str | None) -> list[Session]:
    root = sessions_root("claude")
    if not root.is_dir():
        return []
    files: list[tuple[float, Path]] = []
    for project in root.iterdir():
        if not project.is_dir():
            continue
        for f in project.glob("*.jsonl"):
            try:
                files.append((f.stat().st_mtime, f))
            except OSError:
                continue
    files.sort(key=lambda t: -t[0])
    out = []
    # Directory slugs are lossy: repo-tools and repo/tools can share a slug. Only
    # the transcript's cwd below can decide whether it belongs to this workspace.
    candidates = files if workspace else files[: max(limit * 2, 20)]
    for _, f in candidates:
        s = _claude_session(f, full=False)
        if s is None or (
            workspace and os.path.realpath(s.workspace or "") != os.path.realpath(workspace)
        ):
            continue
        out.append(s)
        if len(out) >= limit:
            break
    return out


def _claude_session(f: Path, full: bool) -> Session | None:
    lines = _read_lines(f)
    try:
        st = f.stat()
    except OSError:
        return None
    cwd = ""
    sid = f.stem
    first_user = last_user = last_assistant = ""
    created = st.st_ctime
    n = 0
    transcript: list[dict[str, Any]] = []
    last_role = ""
    for obj in lines:
        t = obj.get("type")
        if t not in ("user", "assistant"):
            continue
        cwd = cwd or str(obj.get("cwd") or "")
        sid = str(obj.get("sessionId") or sid)
        msg = obj.get("message") or {}
        text = _text_of(msg.get("content")) if isinstance(msg, dict) else ""
        if t == "user":
            text = _clean(text)
            if not text or text.startswith("<") or obj.get("isMeta"):
                continue
            if not first_user:
                first_user = text
                ts = obj.get("timestamp")
                if isinstance(ts, str):
                    created = _iso_to_ts(ts) or created
            last_user = text
        else:
            text = text.strip()
            if not text:
                continue
            last_assistant = text
        last_role = t
        n += 1
        if full:
            transcript.append({"role": t, "text": text})
    if full:
        transcript = transcript[-400:]
    return Session(
        agent="claude",
        id=sid,
        title=_title(first_user) or "Untitled session",
        workspace=cwd or _slug_to_path(f.parent.name.lstrip("-")),
        path=str(f),
        created_at=created,
        updated_at=st.st_mtime,
        messages=n,
        status=_status(st.st_mtime, last_role == "user"),
        last_user=_title(last_user, 160),
        last_assistant=_title(last_assistant, 160),
        transcript=transcript,
    )


def _iso_to_ts(s: str) -> float:
    try:
        from datetime import datetime

        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


# -- dsh (DeepSeek Harness) -------------------------------------------------------------------
DSH_SESSION_FILE = "session.v4.jsonl.zstd"
# The zstd frame magic (RFC 8878): the store appends one frame per write.
_ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"


def _decompress_zstd_frames(buf: bytes) -> str:
    """Decompress a dsh session file, which is many zstd frames appended as it is written.

    A single decompression stops at the end of the first frame, so a long chat would lose
    everything after its opening lines; ``stream_reader`` follows the frames to the end.
    ``zstandard`` is imported here rather than at the top so that a machine without it
    reads dsh as an agent with no sessions instead of failing to import the module.
    """
    try:
        import zstandard
    except ImportError:
        return ""
    chunks: list[bytes] = []
    try:
        with zstandard.ZstdDecompressor().stream_reader(
            io.BytesIO(buf), read_across_frames=True
        ) as reader:
            while chunk := reader.read(1 << 16):
                chunks.append(chunk)
    except Exception:
        # a last frame cut short (a write in progress) keeps the frames before it; a broken
        # last line is then skipped like any other line that does not parse
        pass
    return b"".join(chunks).decode("utf-8", "replace")


def _read_zstd_lines(path: Path, limit_bytes: int = 64 * 1024 * 1024) -> list[dict[str, Any]]:
    """The JSON objects of a dsh session file: zstd-compressed JSONL, one object a line."""
    out: list[dict[str, Any]] = []
    try:
        if path.stat().st_size > limit_bytes:
            return out
        text = _decompress_zstd_frames(path.read_bytes())
    except OSError:
        return out
    for raw in text.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except ValueError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def _dsh_text_of(content: Any) -> str:
    """The words of a dsh content array: `text` parts only (reasoning is not the answer)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            str(c.get("text"))
            for c in content
            if isinstance(c, dict) and c.get("type") == "text" and c.get("text")
        )
    return ""


def _dsh_session(f: Path, full: bool) -> Session | None:
    lines = _read_zstd_lines(f)
    try:
        st = f.stat()
    except OSError:
        return None
    sid = f.parent.name
    cwd = ""
    created = st.st_ctime
    stored_title = ""
    first_user = last_user = last_assistant = ""
    open_turn = False
    n = 0
    transcript: list[dict[str, Any]] = []
    for obj in lines:
        t = obj.get("type")
        raw_data = obj.get("data")
        data: dict[str, Any] = raw_data if isinstance(raw_data, dict) else {}
        if t == "session":
            # a subagent (or a forked session) is the harness's own working session, not a
            # chat the person had: it has no place in the apps' list
            if obj.get("origin") == "subagent" or obj.get("parentSession") is not None:
                return None
            sid = str(obj.get("id") or sid)
            cwd = cwd or str(obj.get("cwd") or "")
            ms = obj.get("createdAt")
            if isinstance(ms, (int, float)) and ms:
                created = float(ms) / 1000
        elif t == "session/title":
            stored_title = stored_title or str(data.get("title") or "")
        elif t == "user/message":
            # only what the person typed: the store also carries runtime context, the skill
            # catalog and background-job notices as user messages, with `source.kind` naming them
            raw_source = data.get("source")
            source: dict[str, Any] = raw_source if isinstance(raw_source, dict) else {}
            if source.get("kind") != "user":
                continue
            text = _clean(_dsh_text_of(data.get("content")))
            if not text:
                continue
            first_user = first_user or text
            last_user = text
            open_turn = True
            n += 1
            if full:
                transcript.append({"role": "user", "text": text})
        elif t == "assistant/message":
            raw_msg = data.get("message")
            msg: dict[str, Any] = raw_msg if isinstance(raw_msg, dict) else {}
            text = _dsh_text_of(msg.get("content")).strip()
            if not text:
                continue
            last_assistant = text
            n += 1
            if full:
                transcript.append({"role": "assistant", "text": text})
        elif t == "turn/end":
            open_turn = False
    if full:
        transcript = transcript[-400:]
    slug = f.parent.parent.name.strip("-")
    return Session(
        agent="dsh",
        id=sid,
        title=_title(stored_title or first_user) or "Untitled session",
        workspace=cwd or _slug_to_path(slug),
        path=str(f),
        created_at=created,
        updated_at=st.st_mtime,
        messages=n,
        status=_status(st.st_mtime, open_turn),
        last_user=_title(last_user, 160),
        last_assistant=_title(last_assistant, 160),
        # `dsh headless --session-id` adopts a session of this store, so a chat read here continues
        resumable=True,
        transcript=transcript,
    )


def _dsh_sessions(limit: int, workspace: str | None) -> list[Session]:
    root = sessions_root("dsh")
    if not root.is_dir():
        return []
    files: list[tuple[float, Path]] = []
    for project in root.iterdir():
        if not project.is_dir():
            continue
        for sdir in project.iterdir():
            if not sdir.is_dir():
                continue
            f = sdir / DSH_SESSION_FILE
            if not f.is_file():
                f = sdir / "session.jsonl"
            try:
                files.append((f.stat().st_mtime, f))
            except OSError:
                continue
    files.sort(key=lambda t: -t[0])
    out = []
    # Directory slugs are lossy: repo-tools and repo/tools can share a slug. Only
    # the transcript's cwd below can decide whether it belongs to this workspace.
    candidates = files if workspace else files[: max(limit * 2, 20)]
    for _, f in candidates:
        s = _dsh_session(f, full=False)
        if s is None or (
            workspace and os.path.realpath(s.workspace or "") != os.path.realpath(workspace)
        ):
            continue
        out.append(s)
        if len(out) >= limit:
            break
    return out


# ---------------------------------------------------------------------- the public readers
def sessions(
    agent: str | None = None, limit: int = 30, workspace: str | None = None
) -> list[Session]:
    """Newest first, across the agents asked for (all when ``agent`` is None)."""
    limit = max(1, min(limit, 200))
    readers = {
        "cursor": _cursor_sessions,
        "codex": _codex_sessions,
        "claude": _claude_sessions,
        "dsh": _dsh_sessions,
    }
    picked = [agent] if agent else list(readers)
    out: list[Session] = []
    for a in picked:
        if a in readers:
            out.extend(readers[a](limit, workspace))
    out.sort(key=lambda s: -s.updated_at)
    return out[:limit]


def read_session(agent: str, session_id: str) -> Session | None:
    """One session with its transcript (the last 400 messages)."""
    session_id = session_id.strip()
    if not session_id or "/" in session_id or ".." in session_id:
        return None
    if agent == "cursor":
        root = sessions_root("cursor")
        if root.is_dir():
            for project in root.iterdir():
                f = project / "agent-transcripts" / session_id / f"{session_id}.jsonl"
                if f.is_file():
                    return _cursor_session(
                        f, _slug_to_path(project.name), _cursor_cli_meta(), full=True
                    )
    elif agent == "codex":
        root = sessions_root("codex")
        if root.is_dir():
            for f in root.rglob(f"rollout-*{session_id}.jsonl"):
                return _codex_session(f, full=True)
    elif agent == "claude":
        root = sessions_root("claude")
        if root.is_dir():
            for f in root.rglob(f"{session_id}.jsonl"):
                return _claude_session(f, full=True)
    elif agent == "dsh":
        # the session's own directory is named after its id: <slug>/<id>/session.v4.jsonl.zstd
        root = sessions_root("dsh")
        if root.is_dir():
            for project in root.iterdir():
                sdir = project / session_id
                for name in (DSH_SESSION_FILE, "session.jsonl"):
                    f = sdir / name
                    if f.is_file():
                        return _dsh_session(f, full=True)
    return None


__all__ = [
    "AGENTS",
    "AgentInfo",
    "Session",
    "detect",
    "read_session",
    "sessions",
    "sessions_root",
    "which",
]
