"""scripts/readme-contributors.py: the avatars between the markers follow GitHub's list, without
the maintainers and the bots, in every README."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "readme-contributors.py"

PEOPLE = [
    {"login": "lgy0404", "id": 63797388, "type": "User", "contributions": 900},
    {"login": "alice", "id": 1, "type": "User", "contributions": 22},
    {"login": "dependabot[bot]", "id": 49699333, "type": "Bot", "contributions": 5},
    {"login": "bob", "id": 2, "type": "User", "contributions": 1},
]

README = """# nanoMuse

## Community Contributors

Everyone whose change has landed on `main`.

<!-- contributors:start -->
<p>
<a href="https://github.com/old"><img src="https://avatars.githubusercontent.com/u/9?v=4&s=48" width="48" height="48" alt="old"></a>
</p>
<!-- contributors:end -->

## License
"""


@pytest.fixture(scope="module")
def script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("readme_contributors", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_block_lists_the_community_in_github_order_without_maintainers_or_bots(
    script: ModuleType,
) -> None:
    block = script.render(PEOPLE)
    assert block.splitlines()[0] == "<p>" and block.splitlines()[-1] == "</p>"
    links = [line for line in block.splitlines() if line.startswith("<a ")]
    assert [link.split('alt="')[1].split('"')[0] for link in links] == ["alice", "bob"]
    assert (
        '<a href="https://github.com/alice"><img src="https://avatars.githubusercontent.com/u/1'
        '?v=4&s=48" width="48" height="48" alt="alice"></a>'
    ) in block
    assert "lgy0404" not in block and "dependabot" not in block
    assert script.render([]) == "<p>\n</p>"


def test_rewrite_touches_only_the_part_between_the_markers(script: ModuleType) -> None:
    new = script.rewrite(README, script.render(PEOPLE))
    before, _, rest = new.partition(script.START)
    inside, _, after = rest.partition(script.END)
    assert before == README.partition(script.START)[0]
    assert after == README.partition(script.END)[2]
    assert inside == "\n" + script.render(PEOPLE) + "\n"
    assert "old" not in inside
    with pytest.raises(ValueError):
        script.rewrite("# no markers\n", "<p>\n</p>")


def test_main_rewrites_every_readme_and_check_reports_the_ones_behind(
    script: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    files = [tmp_path / "README.md", tmp_path / "docs" / "readme" / "README_zh.md"]
    for f in files:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(README, encoding="utf-8")
    people = tmp_path / "people.json"
    people.write_text(json.dumps(PEOPLE), encoding="utf-8")

    assert script.main(["--check", "--from-json", str(people), "--root", str(tmp_path)]) == 1
    assert "2 README(s) behind" in capsys.readouterr().out
    assert all("old" in f.read_text(encoding="utf-8") for f in files)  # --check writes nothing

    assert script.main(["--from-json", str(people), "--root", str(tmp_path)]) == 0
    assert "updated 2 README(s): alice, bob" in capsys.readouterr().out
    for f in files:
        text = f.read_text(encoding="utf-8")
        assert "old" not in text and 'alt="alice"' in text and 'alt="bob"' in text
        assert text.startswith("# nanoMuse\n") and text.endswith("## License\n")

    assert script.main(["--check", "--from-json", str(people), "--root", str(tmp_path)]) == 0
    assert "contributors current (alice, bob)" in capsys.readouterr().out
    assert script.main(["--from-json", str(people), "--root", str(tmp_path)]) == 0
    assert "nothing to do" in capsys.readouterr().out


def test_the_ten_readmes_carry_the_block_and_the_maintainer_card(script: ModuleType) -> None:
    paths = script.readmes()
    assert len(paths) == 10 and paths[0] == ROOT / "README.md"
    for path in paths:
        text = path.read_text(encoding="utf-8")
        assert text.count(script.START) == 1 and text.count(script.END) == 1, path.name
        assert text.index(script.START) < text.index(script.END), path.name
        assert 'href="https://github.com/lgy0404"' in text, path.name
        assert "komarev.com/ghpvc/?username=nano-muse-nanomuse" in text, path.name
        assert "lgy0404" not in text[text.index(script.START) : text.index(script.END)], path.name
