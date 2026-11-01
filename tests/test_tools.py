from __future__ import annotations

import contextlib
import os
import socket
import sys
from pathlib import Path

import httpx
import pytest

from nanomuse.schema import RiskLevel
from nanomuse.tools import Files, PythonExecute, Shell, Terminate
from nanomuse.tools.email_tool import scrub_email_secrets
from nanomuse.tools.shell import code_reach, scrubbed_env
from nanomuse.tools.web import fetch_public, host_of, html_to_markdown


async def test_files_writes_the_lines_it_was_given(tmp_path: Path):
    """A write puts the text the model asked for on disk: the text mode on Windows turned
    every "\\n" into "\\r\\n", so `#!/bin/sh` arrived as `#!/bin/sh\\r` (a script WSL and git
    bash refuse to run), and reading the file back was not reading what was written."""
    files = Files(workspace=tmp_path)
    r = await files.execute(action="write", path="run.sh", content="#!/bin/sh\necho hi\n")
    assert r.ok and "18 chars" in r.output
    assert (tmp_path / "run.sh").read_bytes() == b"#!/bin/sh\necho hi\n"
    r = await files.execute(action="append", path="run.sh", content="exit 0\n")
    assert r.ok
    assert (tmp_path / "run.sh").read_bytes() == b"#!/bin/sh\necho hi\nexit 0\n"
    r = await files.execute(action="read", path="run.sh")
    assert r.output == "#!/bin/sh\necho hi\nexit 0\n"
    # text that already carries a carriage return is written as it is, not doubled
    r = await files.execute(action="write", path="win.txt", content="a\r\nb\r\n")
    assert (tmp_path / "win.txt").read_bytes() == b"a\r\nb\r\n"


async def test_files_reads_a_file_the_way_it_reads_a_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A file is often a command's output: PowerShell 5's ``>`` and ``reg export`` write
    UTF-16LE, Notepad offers UTF-8 with a mark, a redirect on a Chinese console writes code
    page 936. Read as plain UTF-8, the model got NULs and replacement characters instead of
    the text; the file now goes through the shell tool's own decoder."""
    import nanomuse.stdio as stdio

    files = Files(workspace=tmp_path)
    (tmp_path / "powershell.txt").write_bytes("第一行\nsecond\n".encode("utf-16"))
    r = await files.execute(action="read", path="powershell.txt")
    assert r.ok and r.output == "第一行\nsecond\n"

    (tmp_path / "notepad.txt").write_bytes(b"\xef\xbb\xbf" + "中文".encode())
    r = await files.execute(action="read", path="notepad.txt")
    assert r.ok and r.output == "中文"

    (tmp_path / "plain.txt").write_bytes(b"plain\n")
    r = await files.execute(action="read", path="plain.txt")
    assert r.ok and r.output == "plain\n"

    # the console's code page is the last resort, as in the shell tool (asked of the console
    # itself, so the test names it rather than depending on the machine running it)
    (tmp_path / "cmd.txt").write_bytes("中文目录".encode("cp936"))
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(stdio, "console_encoding", lambda: "cp936")
        r = await files.execute(action="read", path="cmd.txt")
        assert r.ok and r.output == "中文目录"


async def test_files_read_cut_inside_a_character_stays_utf8(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """The byte window can end inside a multi-byte character. The strict UTF-8 read then
    failed on the tail, and a console code page that takes any byte (cp1252) read the whole
    file as mojibake: `€€€` came back as `â‚¬â‚¬â‚¬`. The unfinished character is cut off
    before the bytes are read."""
    import nanomuse.stdio as stdio
    from nanomuse.tools import files as files_module

    # a 52-byte window: seventeen 3-byte characters and the first byte of the next
    monkeypatch.setattr(files_module, "MAX_READ_CHARS", 11)
    monkeypatch.setattr(stdio, "console_encoding", lambda: "cp1252")
    (tmp_path / "euro.txt").write_text("€" * 100, encoding="utf-8")
    r = await Files(workspace=tmp_path).execute(action="read", path="euro.txt")
    assert r.ok and r.output.startswith("€" * 11) and "â" not in r.output
    # the trim is only for a cut that lands inside a character
    assert files_module.whole_utf8(b"abc") == b"abc"
    assert files_module.whole_utf8("中文".encode()) == "中文".encode()
    assert files_module.whole_utf8("中文".encode()[:-1]) == "中".encode()
    assert files_module.whole_utf8("中文".encode()[:-2]) == "中".encode()
    assert files_module.whole_utf8(b"\xff\xfe") == b"\xff\xfe"  # not UTF-8 at all: untouched


async def test_files_read_cuts_between_characters(tmp_path: Path):
    """The cap is characters, not bytes: a long file is cut at the cap with a trailing
    character whole, never half of one (which would read as U+FFFD)."""
    from nanomuse.tools import files as files_module

    text = "中" * (files_module.MAX_READ_CHARS + 50)
    (tmp_path / "big.txt").write_text(text, encoding="utf-8")
    r = await Files(workspace=tmp_path).execute(action="read", path="big.txt")
    assert r.ok and "truncated" in r.output and "�" not in r.output
    assert r.output.startswith("中" * 100)


async def test_files_workspace_scoping(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    files = Files(workspace=ws)
    r = await files.execute(action="write", path="notes/a.md", content="hello")
    assert r.ok and (ws / "notes" / "a.md").read_text() == "hello"
    r = await files.execute(action="append", path="notes/a.md", content=" world")
    assert (ws / "notes" / "a.md").read_text() == "hello world"
    r = await files.execute(action="read", path="notes/a.md")
    assert r.output == "hello world"
    r = await files.execute(action="list", path=".")
    assert "[dir] notes" in r.output
    r = await files.execute(action="search", pattern="**/*.md")
    assert "notes/a.md" in r.output
    # escape attempts
    r = await files.execute(action="read", path="../outside.txt")
    assert r.error and "outside the workspace" in r.error
    r = await files.execute(action="read", path="/etc/passwd")
    assert r.error
    # assessment: writes are moderate, reads inside safe, reads outside private
    assert files.assess({"action": "write", "path": "x"}).risk == RiskLevel.MODERATE
    assert files.assess({"action": "read", "path": "x"}).risk == RiskLevel.SAFE
    outside = Files(workspace=ws, extra_roots=[tmp_path])
    a = outside.assess({"action": "read", "path": str(tmp_path / "secret.txt")})
    assert a.reads_private_data and a.risk == RiskLevel.MODERATE
    # a search under an extra root names its matches in full (it used to raise)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "x.md").write_text("x")
    r = await outside.execute(action="search", path=str(tmp_path / "docs"), pattern="*.md")
    assert r.ok and r.output == str(tmp_path / "docs" / "x.md")


async def test_a_windows_device_name_is_refused_before_the_write_reaches_the_device(
    tmp_path, monkeypatch
):
    from nanomuse.tools import files as files_module

    files = Files(workspace=tmp_path)
    # the module's own switch, not os.name: patching os.name makes Path() build a
    # WindowsPath on Python 3.11 and earlier, which is not what these tests are about
    monkeypatch.setattr(files_module, "ON_WINDOWS", True, raising=False)
    r = await files.execute(action="write", path="NUL", content="gone")
    assert r.error and "device name" in r.error
    assert list(tmp_path.iterdir()) == []


async def test_a_name_windows_would_change_is_refused_with_the_name_it_would_land_as(
    tmp_path, monkeypatch
):
    from nanomuse.tools import files as files_module

    files = Files(workspace=tmp_path)
    monkeypatch.setattr(files_module, "ON_WINDOWS", True, raising=False)
    r = await files.execute(action="write", path="report.", content="x")
    assert r.error and "'report'" in r.error
    assert list(tmp_path.iterdir()) == []
    # Win32 reserves the device basename even when an extension follows it.
    r = await files.execute(action="write", path="NUL.txt", content="kept")
    assert r.error and "device name" in r.error
    assert list(tmp_path.iterdir()) == []


async def test_files_says_when_a_listing_or_a_search_was_cut(tmp_path: Path):
    from nanomuse.tools import files as files_module

    for name in ("a.md", "b.md", "c.md"):
        (tmp_path / name).write_text("x")
    files = Files(workspace=tmp_path)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(files_module, "LIST_MAX", 2)
        r = await files.execute(action="list", path=".")
        assert r.ok and "3 entries in all; the first 2 are listed" in r.output
        patch.setattr(files_module, "SEARCH_MAX_MATCHES", 2)
        r = await files.execute(action="search", pattern="*.md")
        # the walk's order is the file system's (APFS hands names back unsorted), so the
        # two kept are any two of the three
        assert r.ok and sum(line.endswith(".md") for line in r.output.splitlines()) == 2
        assert "stopped at 2 matches; narrow the pattern" in r.output
    r = await files.execute(action="list", path=".")
    assert "entries in all" not in r.output
    r = await files.execute(action="search", pattern="*.md")
    assert "stopped" not in r.output


async def test_files_read_truncates_without_loading_the_whole_file(tmp_path: Path):
    from nanomuse.tools import files as files_module

    big = tmp_path / "big.log"
    big.write_text("x" * (files_module.MAX_READ_CHARS + 5000))
    r = await Files(workspace=tmp_path).execute(action="read", path="big.log")
    assert r.ok and r.output.startswith("x" * files_module.MAX_READ_CHARS)
    assert f"[truncated, {files_module.MAX_READ_CHARS + 5000} bytes total]" in r.output
    small = tmp_path / "small.txt"
    small.write_text("tiny")
    r = await Files(workspace=tmp_path).execute(action="read", path="small.txt")
    assert r.output == "tiny"


async def test_files_write_repairs_double_escaped_newlines(tmp_path: Path):
    files = Files(workspace=tmp_path)
    # a small model's itinerary: one line, "\n" spelled out between the days
    flat = "Day 1: Fushimi Inari\\nDay 2: Gion\\nDay 3: Arashiyama"
    r = await files.execute(action="write", path="kyoto.md", content=flat)
    assert "escaped newlines" in r.output
    assert (tmp_path / "kyoto.md").read_text().splitlines() == [
        "Day 1: Fushimi Inari",
        "Day 2: Gion",
        "Day 3: Arashiyama",
    ]
    # code with real newlines keeps its escape sequences
    code = 'print("a\\nb")\nprint("c\\nd")\n'
    await files.execute(action="write", path="x.py", content=code)
    assert (tmp_path / "x.py").read_text() == code
    # a single escaped newline on one line is left alone too
    one = 'echo "a\\nb"'
    await files.execute(action="write", path="one.sh", content=one)
    assert (tmp_path / "one.sh").read_text() == one


async def test_a_write_into_an_extra_root_on_another_drive_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """An extra root on another drive has no path relative to the workspace, and Windows'
    ``os.path.relpath`` raises "path is on mount 'D:', start on mount 'C:'" there, after the
    file is already on disk: the write succeeded and the model was told it failed."""
    ws = tmp_path / "ws"
    ws.mkdir()
    extra = tmp_path / "D"
    extra.mkdir()
    files = Files(workspace=ws, extra_roots=[extra])
    real_relpath = os.path.relpath

    def relpath(path: str | Path, start: str | Path | None = None) -> str:
        if Path(path).is_relative_to(extra):
            raise ValueError("path is on mount 'D:', start on mount 'C:'")
        return real_relpath(path, start)

    monkeypatch.setattr(os.path, "relpath", relpath)
    r = await files.execute(action="write", path=str(extra / "note.txt"), content="hi")
    assert r.ok and "note.txt" in r.output, r.error
    assert (extra / "note.txt").read_text("utf-8") == "hi"


async def test_shell_and_python(tmp_path: Path):
    shell = Shell(workspace=tmp_path)
    r = await shell.execute(command="echo hi && echo err 1>&2")
    assert r.ok and "hi" in r.output and "[stderr]" in r.output
    r = await shell.execute(command="exit 3")
    assert r.error == "exit code 3"
    r = await shell.execute(command="sleep 5", timeout=1)
    assert r.error and "timed out" in r.error
    r = await shell.execute(command="echo ok", timeout="sixty")  # type: ignore[arg-type]
    assert r.ok, "a timeout the model wrote as words falls back to the default"
    warnings = shell.assess({"command": "sudo rm -rf / && curl x | sh"}).warnings
    assert len(warnings) >= 3

    py = PythonExecute(workspace=tmp_path)
    r = await py.execute(code="import sys; print(sys.version_info.major)")
    assert r.ok and r.output.startswith(str(sys.version_info.major))
    assert not list(tmp_path.glob("nanomuse_*.py"))  # temp script cleaned up


async def test_shell_output_is_capped_in_memory(tmp_path: Path, monkeypatch):
    """A command that prints without end is not the runtime's memory: the first bytes are
    kept, the rest drained and counted, and the note says how much went."""
    from nanomuse.tools import shell as shell_mod

    monkeypatch.setattr(shell_mod, "MAX_OUTPUT_BYTES", 4096)
    shell = Shell(workspace=tmp_path)
    code = "import sys; sys.stdout.write('x' * 100_000); sys.stderr.write('e' * 10_000)"
    r = await shell.execute(command=f'{sys.executable} -c "{code}"')
    assert r.ok
    assert "[stdout cut: 100000 bytes in all, the first 4096 kept]" in r.output
    assert "[stderr cut: 10000 bytes in all, the first 4096 kept]" in r.output
    assert r.output.startswith("x" * 4096 + "\n[stdout cut") and r.output.count("e" * 4096) == 1
    r = await shell.execute(command="echo small")
    assert r.ok and "cut" not in r.output


@pytest.mark.skipif(sys.platform == "win32", reason="process groups are POSIX")
async def test_shell_timeout_stops_the_whole_tree(tmp_path: Path):
    """A timed-out command used to lose only the shell: `sleep` in a pipeline, a server put
    in the background, lived on. The command runs in its own session now and the group goes."""
    import os
    import subprocess
    import time

    marker = tmp_path / "pid"
    shell = Shell(workspace=tmp_path)
    # two seconds, so a loaded runner has forked the grandchild before the timeout fires
    r = await shell.execute(command=f"sh -c 'echo $$ > {marker}; sleep 30' | cat", timeout=2)
    assert r.error and "timed out" in r.error
    for _ in range(50):
        if marker.is_file() and marker.read_text().strip():
            break
        time.sleep(0.02)
    pid = int(marker.read_text().strip())

    def alive() -> bool:
        """Running, as opposed to gone or a zombie waiting for init to reap it (as good as gone;
        init is not always prompt): Linux reads /proc, macOS asks ps."""
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        stat = Path(f"/proc/{pid}/stat")
        if stat.is_file():
            try:
                return stat.read_text().rsplit(")", 1)[-1].split()[0] != "Z"
            except (FileNotFoundError, ProcessLookupError):
                return False  # reaped between the two calls
        ps = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True)
        state = ps.stdout.strip()
        return bool(state) and not state.startswith("Z")

    for _ in range(100):  # the kill is delivered at once; the reap takes a moment
        if not alive():
            break
        time.sleep(0.02)
    assert not alive(), "the grandchild outlived the timeout"


def test_subprocess_env_is_scrubbed_of_credentials():
    env = scrubbed_env(
        {
            "PATH": "/usr/bin",
            "HOME": "/home/me",
            "LANG": "C.UTF-8",
            "OPENAI_API_KEY": "sk-1",
            "WQ_API_KEY": "x",
            "DEEPSEEK_API_KEY": "x",
            "NANOMUSE_VAULT_KEY": "x",
            "NANOMUSE_SERVER_TOKEN": "x",
            "GITHUB_TOKEN": "x",
            "AWS_SECRET_ACCESS_KEY": "x",
            "DB_PASSWORD": "x",
            "SSH_AUTH_SOCK": "/run/ssh",
            "HTTP_PROXY": "http://proxy:3128",
        }
    )
    assert set(env) == {"PATH", "HOME", "LANG", "HTTP_PROXY", "NANOMUSE_SANDBOX"}


async def test_python_and_shell_children_cannot_read_secrets(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("MY_SECRET_TOKEN", "hunter2")
    monkeypatch.setenv("NANOMUSE_VAULT_KEY", "k")
    monkeypatch.setenv("PLAIN_SETTING", "yes")
    py = PythonExecute(workspace=tmp_path)
    r = await py.execute(
        code="import os; print(os.environ.get('MY_SECRET_TOKEN'), "
        "os.environ.get('NANOMUSE_VAULT_KEY'), os.environ.get('PLAIN_SETTING'))"
    )
    assert r.ok and r.output.startswith("None None yes")
    if sys.platform == "win32":
        # cmd.exe leaves an unset %VAR% as it is — which shows the secret is not there
        r = await Shell(workspace=tmp_path).execute(
            command="echo [%MY_SECRET_TOKEN%] [%PLAIN_SETTING%]"
        )
        assert r.ok and r.output.startswith("[%MY_SECRET_TOKEN%] [yes]")
    else:
        r = await Shell(workspace=tmp_path).execute(
            command="echo [$MY_SECRET_TOKEN] [$PLAIN_SETTING]"
        )
        assert r.ok and r.output.startswith("[] [yes]")


def test_python_reach_decides_the_risk(tmp_path: Path):
    from nanomuse.config import SandboxSettings
    from nanomuse.sandbox import Sandbox

    # without a sandbox the static check is the only wall: every script is sensitive — the
    # level, said on the card, not a warning (auto mode and always_allow_tools may accept it)
    bare = PythonExecute(workspace=tmp_path)
    plain_code = "import csv\nrows = [1, 2]\nopen('out.csv', 'w').write('a,b')"
    unboxed = bare.assess({"code": plain_code})
    assert unboxed.risk == RiskLevel.SENSITIVE and not unboxed.warnings
    assert unboxed.summary.endswith("runs without a sandbox on this computer")
    box = Sandbox(SandboxSettings(mode="off"), workspace=tmp_path)
    box.active = True  # as on a Linux box with bubblewrap
    py = PythonExecute(workspace=tmp_path, sandbox=box)
    plain = py.assess({"code": plain_code})
    assert plain.risk == RiskLevel.MODERATE and not plain.warnings and not plain.egress
    net = py.assess({"code": "import requests\nrequests.get('https://x')"})
    assert (
        net.risk == RiskLevel.SENSITIVE and net.egress and "reaches the network" in net.warnings[0]
    )
    env = py.assess({"code": "import os\nprint(os.environ['HOME'])"})
    assert env.risk == RiskLevel.SENSITIVE and "environment" in env.warnings[0]
    outside = py.assess({"code": "open('/etc/passwd').read()"})
    assert outside.risk == RiskLevel.SENSITIVE and "outside the workspace" in outside.warnings[0]
    proc = py.assess({"code": "import subprocess\nsubprocess.run(['ls'])"})
    assert proc.risk == RiskLevel.SENSITIVE and proc.egress
    assert set(code_reach("import shutil\nshutil.rmtree('x')")) == {"deletion"}
    # modules fetched by name and attributes looked up by string are named on the card
    dynamic = py.assess({"code": "m = __import__('sub' + 'process')\nm.run(['ls'])"})
    assert (
        dynamic.risk == RiskLevel.SENSITIVE
        and "loads code or modules by name" in dynamic.warnings[0]
    )
    assert "dynamic code" in code_reach("import importlib\nimportlib.import_module('socket')")
    assert "dynamic code" in code_reach("getattr(os, 'sys' + 'tem')('id')")
    assert "dynamic code" in code_reach("exec(open('x.py').read())")
    assert "dynamic code" not in code_reach("x = {'a': 1}\nprint(x.get('a'))")
    # a workspace under /tmp or /home: absolute paths inside it are not "outside"
    inside = py.assess({"code": f"open('{tmp_path.as_posix()}/list.html', 'w').write('<p>')"})
    assert inside.risk == RiskLevel.MODERATE and not inside.warnings
    mixed = py.assess({"code": f"open('{tmp_path.as_posix()}/a').read(); open('/etc/hosts')"})
    assert mixed.risk == RiskLevel.SENSITIVE
    home = py.assess(
        {"code": f"import os\nopen(os.path.expanduser('~/x'))  # {tmp_path.as_posix()}"}
    )
    assert home.risk == RiskLevel.SENSITIVE


async def test_web_fetch_refuses_redirects_into_private_networks():
    hops: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        hops.append(str(request.url))
        if request.url.host == "public.example":
            return httpx.Response(
                302, headers={"location": "http://169.254.169.254/latest/meta-data"}
            )
        return httpx.Response(200, text="should never be reached")

    transport = httpx.MockTransport(handler)
    with pytest.raises(PermissionError, match="private/internal host '169.254.169.254'"):
        await fetch_public("http://public.example/start", timeout=5, transport=transport)
    assert hops == ["http://public.example/start"]

    def loop(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": str(request.url) + "x"})

    with pytest.raises(PermissionError, match="redirects"):
        await fetch_public(
            "http://public.example/a", timeout=5, transport=httpx.MockTransport(loop)
        )

    def fine(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/old":
            return httpx.Response(301, headers={"location": "/new"})
        return httpx.Response(200, text="moved here")

    resp = await fetch_public(
        "http://public.example/old", timeout=5, transport=httpx.MockTransport(fine)
    )
    assert resp.status_code == 200 and resp.text == "moved here" and str(resp.url).endswith("/new")


async def test_web_fetch_refuses_local_names_without_dns(monkeypatch: pytest.MonkeyPatch):
    """``localhost`` and ``.internal`` names are refused by name; the resolver is never asked,
    so the refusal does not depend on what the machine's DNS would answer (#339)."""

    def no_dns(*args: object, **kwargs: object) -> object:
        raise AssertionError(f"the resolver was asked: {args!r}")

    monkeypatch.setattr(socket, "getaddrinfo", no_dns)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="should never be reached")

    transport = httpx.MockTransport(handler)
    for url in ("http://localhost/admin", "http://metadata.internal/latest"):
        with pytest.raises(PermissionError, match="private/internal host"):
            await fetch_public(url, timeout=5, transport=transport)


def test_private_host_guard_refuses_every_non_global_address():
    """Numeric literals go to the resolver as they are, so the guard's answer depends on the
    address alone: every range that is not globally routable is refused, the carrier-grade
    NAT block (a Tailscale network) and IPv4-mapped IPv6 addresses among them; decimal and
    IPv6 spellings of loopback count as loopback."""
    from nanomuse.tools.web import _is_private_host

    refused = [
        "127.0.0.1",
        "10.1.2.3",
        "172.16.0.9",
        "192.168.1.1",
        "169.254.169.254",
        "100.64.0.1",
        "0.0.0.0",
        "224.0.0.1",
        "240.0.0.1",
        "::1",
        "::ffff:127.0.0.1",
        "::ffff:10.0.0.1",
        "fe80::1",
        "fd00::1",
    ]
    for host in refused:
        assert _is_private_host(host), host
    # 127.0.0.1 written as one number: loopback where the platform's resolver reads it so
    with contextlib.suppress(socket.gaierror):
        socket.getaddrinfo("2130706433", None)
        assert _is_private_host("2130706433")
    assert not _is_private_host("93.184.216.34")
    assert not _is_private_host("2606:2800:220:1:248:1893:25c8:1946")


async def test_web_fetch_stops_reading_at_the_body_cap(monkeypatch: pytest.MonkeyPatch):
    from nanomuse.tools import web as web_mod

    monkeypatch.setattr(web_mod, "MAX_BODY_BYTES", 1000)
    served = 0

    async def endless():
        nonlocal served
        while True:  # a stream that never ends: only the cap stops the read
            served += 4096
            yield b"x" * 4096

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, stream=_Chunks(endless()), headers={"content-type": "text/plain"}
        )

    resp = await fetch_public(
        "http://public.example/big", timeout=5, transport=httpx.MockTransport(handler)
    )
    assert len(resp.content) == 1000 and served <= 4096 * 2


async def test_web_fetch_reads_a_compressed_page_once(monkeypatch: pytest.MonkeyPatch):
    """#641: the streamed read already undoes the gzip, and the response handed back used
    to repeat the wire's `content-encoding`, so httpx decoded the body a second time and
    every compressed page failed with `incorrect header check`."""
    import gzip

    page = b"<html><body>" + b"hello gzip " * 40 + b"</body></html>"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=gzip.compress(page),
            headers={"content-encoding": "gzip", "content-type": "text/html", "x-a": "1"},
        )

    resp = await fetch_public(
        "http://public.example/zipped", timeout=5, transport=httpx.MockTransport(handler)
    )
    assert resp.content == page
    assert "content-encoding" not in resp.headers and resp.headers["x-a"] == "1"

    # the cap applies to the page as read, so a compressed page is cut where a plain one is
    from nanomuse.tools import web as web_mod

    monkeypatch.setattr(web_mod, "MAX_BODY_BYTES", 100)
    resp = await fetch_public(
        "http://public.example/zipped", timeout=5, transport=httpx.MockTransport(handler)
    )
    assert resp.content == page[:100]


class _Chunks(httpx.AsyncByteStream):
    def __init__(self, gen):  # noqa: ANN001
        self._gen = gen

    async def __aiter__(self):  # noqa: ANN204
        async for chunk in self._gen:
            yield chunk


async def test_terminate_stops():
    r = await Terminate().execute(status="success", summary="all done")
    assert r.stop and r.output == "all done"


def test_scrub_email_secrets():
    text = (
        "Your verification code is 483920. Reset here: https://x.com/reset?token=abc "
        "and read the news at https://news.example.com/article"
    )
    out = scrub_email_secrets(text)
    assert "483920" not in out and "[REDACTED-CODE]" in out
    assert "token=abc" not in out and "https://news.example.com/article" in out
    assert "验证码：[REDACTED-CODE]" in scrub_email_secrets("您的验证码：123456，5分钟内有效")


def test_imap_arguments_are_quoted_and_never_carry_a_second_command():
    from nanomuse.tools.email_tool import imap_quote, imap_search_args

    assert imap_quote("INBOX") == '"INBOX"'
    assert imap_quote('Sent "Items"\\x') == '"Sent \\"Items\\"\\\\x"'
    with pytest.raises(RuntimeError, match="control characters"):
        imap_quote("INBOX\r\nA1 DELETE INBOX")
    # an ASCII term travels as a quoted string, a Chinese one as a UTF-8 literal
    assert imap_search_args(False, None) == (None, ["ALL"], None)
    assert imap_search_args(True, "  ") == (None, ["UNSEEN"], None)
    assert imap_search_args(True, 'rent "oct"') == (
        None,
        ["UNSEEN", "TEXT", '"rent \\"oct\\""'],
        None,
    )
    assert imap_search_args(False, "房租\r\n") == ("UTF-8", ["TEXT"], "房租".encode())


async def test_number_arguments_from_the_model_never_crash_a_tool():
    from nanomuse.tools.base import int_arg, number_arg

    assert int_arg("30", 10, 1, 60) == 30
    assert int_arg("ten", 10, 1, 60) == 10
    assert int_arg(None, 10, 1, 60) == 10
    assert int_arg(True, 10, 1, 60) == 10
    assert int_arg(9000, 10, 1, 60) == 60
    assert number_arg("0.5", 1.0, 0.2, 10.0) == 0.5
    assert number_arg(float("nan"), 1.0, 0.2, 10.0) == 1.0
    assert number_arg(-3, 1.0, 0.2, 10.0) == 0.2


async def test_safe_execute_tells_a_bad_argument_from_a_crash(tmp_path: Path):
    from typing import Any

    from nanomuse.schema import ToolResult
    from nanomuse.tools.base import BaseTool, safe_execute

    class Strict(BaseTool):
        name: str = "strict"
        description: str = "takes `n` only"
        parameters: dict[str, Any] = {"type": "object", "properties": {}}

        async def execute(self, n: int = 0) -> ToolResult:  # type: ignore[override]
            return ToolResult(output=str(len(n)))  # type: ignore[arg-type]  # a bug inside

    bad = await safe_execute(Strict(), {"m": 1})
    assert bad.error and bad.error.startswith("bad arguments for strict")
    crash = await safe_execute(Strict(), {"n": 1})
    assert (
        crash.error and crash.error.startswith("TypeError:") and "bad arguments" not in crash.error
    )


def test_host_and_markdown():
    assert host_of("https://EN.Wikipedia.org/wiki/x") == "en.wikipedia.org"
    assert host_of("not a url") is None
    md = html_to_markdown(
        "<html><head><title>T</title><script>x()</script></head><body><h1>Hi</h1><p>para</p></body></html>"
    )
    assert md.startswith("# T") and "x()" not in md and "para" in md


def test_every_tool_takes_the_step_words_and_keeps_them_for_the_person(tmp_path: Path):
    """`step` is in every schema, comes off the arguments before the tool sees them, and is
    read back as the words for the status line — the same words the trace shows."""
    from nanomuse.schema import Function, ToolCall
    from nanomuse.tools.base import with_step

    shell = Shell(workspace=tmp_path)
    schema = shell.to_param()["function"]["parameters"]
    assert "step" in schema["properties"] and "step" not in schema.get("required", [])
    assert "step" not in shell.parameters["properties"], "the tool's own schema is left alone"
    assert with_step({"type": "object"}) == {"type": "object"}  # nothing to add to
    call = ToolCall(
        function=Function(name="shell", arguments='{"command": "ls", "step": " 打开  携程网站 "}')
    )
    assert call.arguments == {"command": "ls"} and call.step == "打开 携程网站"
    assert ToolCall(function=Function(name="shell", arguments='{"command": "ls"}')).step == ""
    assert (
        ToolCall(function=Function(name="shell", arguments='{"command": "ls", "step": 3}')).step
        == ""
    )
    assert ToolCall(function=Function(name="shell", arguments='{"command": "l')).step == ""


async def test_cut_off_arguments_tell_the_model_what_happened(tmp_path: Path):
    from nanomuse.tools.base import safe_execute

    files = Files(workspace=tmp_path)
    short = await safe_execute(files, {"__raw__": '{"action": "wri'})
    assert not short.ok and "not valid JSON" in short.error and "cut off" not in short.error
    long = await safe_execute(files, {"__raw__": '{"action": "write", "content": "' + "x" * 3000})
    assert "cut off in transit" in long.error and "append" in long.error
    assert len(long.error) < 600, "the broken payload itself is not echoed back in full"
