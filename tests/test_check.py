import json
import subprocess
from pathlib import Path

import pytest

from impactgraph import check, to_markdown
from impactgraph.cli import main

DB = '''
def load_customers():
    return [1, 2, 3]


def unrelated():
    return 0
'''
MAIN = '''
from app.db import load_customers


def run():
    return load_customers()
'''


def _git(repo, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=repo, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "app" / "db.py").write_text(DB, encoding="utf-8")
    (tmp_path / "app" / "main.py").write_text(MAIN, encoding="utf-8")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "base")
    # change the body of load_customers only
    (tmp_path / "app" / "db.py").write_text(DB.replace("return [1, 2, 3]", "return [1, 2, 3, 4]"), encoding="utf-8")
    return tmp_path


def test_check_api_maps_diff_to_function_and_caller(repo):
    r = check(str(repo))
    assert r.changed_files == ["app/db.py"]
    assert any(i.endswith("::load_customers") for i in r.changed_ids)
    assert not any(i.endswith("::unrelated") for i in r.changed_ids)
    assert any(i.endswith("main.py::run") for i in r.analysis.affected)
    assert r.level in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
    assert r.breaches("LOW") and not r.breaches("NONE") and not r.breaches(None)
    md = to_markdown(r)
    assert "impactgraph" in md and "load_customers" in md and "run" in md


def test_cli_formats_and_fail_on(repo, capsys, tmp_path):
    gp = tmp_path / "g.json"
    assert main(["check", "--repo", str(repo), "--format", "json", "--save-graph", str(gp)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["changed_files"] == ["app/db.py"] and payload["risk"]["level"]
    assert gp.exists()
    # reuse the graph, markdown to file, html view, fail-on breach -> exit 1
    md = tmp_path / "c.md"
    html = tmp_path / "v.html"
    rc = main(["pr", "--repo", str(repo), "--graph", str(gp), "-o", str(md), "--html", str(html), "--fail-on", "LOW"])
    assert rc == 1
    assert "risk" in md.read_text(encoding="utf-8") and html.exists()
    # text format
    assert main(["check", "--repo", str(repo), "--graph", str(gp)]) == 0
    out = capsys.readouterr().out
    assert "changed files (1)" in out and "load_customers" in out


def test_no_changes_and_passthrough(repo, capsys, tmp_path):
    _git(repo, "commit", "-q", "-am", "apply")
    assert main(["check", "--repo", str(repo), "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["affected"] == {} and "no changes" in " ".join(payload["notes"])
    # base...head over the last commit finds the change again
    assert main(["check", "--repo", str(repo), "--base", "HEAD~1", "--head", "HEAD", "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out)["changed_files"] == ["app/db.py"]
    # anything else goes to datagraph
    gp = tmp_path / "g.json"
    assert main(["build", "--repo", str(repo), "-o", str(gp)]) == 0
    capsys.readouterr()
    assert main(["nodes", "--graph", str(gp), "--search", "load_customers"]) == 0
    assert "load_customers" in capsys.readouterr().out


def test_help_lists_passthrough(capsys):
    assert main([]) == 0
    assert "passed to datagraph" in capsys.readouterr().out


def test_markdown_never_crashes_a_legacy_console(repo, capsys, monkeypatch):
    """impactgraph pr on a Windows cp1252 console must not raise UnicodeEncodeError."""
    import io
    import sys

    from impactgraph.core import safe_console_text

    class Cp1252Stream(io.StringIO):
        encoding = "cp1252"

    md = to_markdown(check(str(repo)))
    assert any(ch in md for ch in ("\U0001f7e1", "\U0001f7e0", "\U0001f534", "\U0001f7e2"))  # emoji kept for GitHub
    plain = safe_console_text(md, stream=Cp1252Stream())
    plain.encode("cp1252")                       # the point: this must not raise
    assert "[" in plain and "impactgraph" in plain

    # the CLI path prints through the same helper
    monkeypatch.setattr(sys, "stdout", Cp1252Stream())
    rc = main(["pr", "--repo", str(repo)])
    printed = sys.stdout.getvalue()
    monkeypatch.undo()
    assert rc == 0 and "impactgraph" in printed
    printed.encode("cp1252")


def test_output_file_keeps_utf8(repo, tmp_path):
    out = tmp_path / "c.md"
    assert main(["pr", "--repo", str(repo), "-o", str(out)]) == 0
    text = out.read_text(encoding="utf-8")
    assert "impactgraph" in text
