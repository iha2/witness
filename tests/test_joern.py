import shutil
import stat
from pathlib import Path

import pytest

from witness.engines import joern
from witness.shared import EnvError

FIX = Path(__file__).parent / "fixtures" / "joern"


def test_parse_export_single_node():
    g = joern.parse_export(
        '{"t":"node","id":7,"kind":"METHOD","path":"a.py","qname":"a.f","sig":"1","line":[1,4]}'
    )
    assert g.add_node("METHOD", ("a.py", "a.g", "1", ""), ("a.py", 5, 6), {}) == 1


def test_parse_export_edges():
    g = joern.parse_export((FIX / "calls_flow.jsonl").read_text())
    assert g.has_path(0, 1, {"calls"}, set())
    assert g.has_path(1, 2, {"dflow"}, set())
    assert not g.has_path(0, 2, {"calls"}, set())


def test_parse_export_sets_name_and_fingerprint():
    g = joern.parse_export((FIX / "calls_flow.jsonl").read_text())
    assert [n.attrs["name"] for n in g.nodes] == ["a.f", "a.g", "a.h"]
    assert all("fingerprint" not in n.attrs for n in g.nodes)
    g = joern.parse_export(
        '{"t":"node","id":1,"kind":"METHOD","path":"a.py","qname":"a.f","sig":"1",'
        '"line":[1,4],"fingerprint":"abc123"}'
    )
    assert g.nodes[0].attrs == {"name": "a.f", "fingerprint": "abc123"}


@pytest.mark.parametrize(
    "bad",
    [
        "[[[1]]]",
        "[" * 100000,
        "{not json",
        '{"t":"node","id":1,"kind":"METHOD","qname":"a.f"}',
        '{"t":"node","id":1,"kind":"METHOD","path":"a.py"}',
        '{"t":"node","kind":"METHOD","path":"a.py","qname":"a.f"}',
        '{"t":"node","id":1,"kind":"METHOD","path":"a.py","qname":"a.f","line":["x",2]}',
        '{"t":"edge","dst":1,"kind":"CALL"}',
        '{"t":"edge","src":[1],"dst":1,"kind":"CALL"}',
    ],
)
def test_parse_export_malformed_raises_enverror(bad):
    with pytest.raises(EnvError, match="line 1"):
        joern.parse_export(bad)


def test_parse_export_malformed_reports_line_number():
    good = '{"t":"node","id":1,"kind":"METHOD","path":"a.py","qname":"a.f"}'
    with pytest.raises(EnvError, match="line 2"):
        joern.parse_export(good + "\n[1]\n")
    assert len(joern.parse_export(good + "\n").nodes) == 1


def _fake(tmp_path, monkeypatch, body):
    for name in ("joern", "joern-parse"):
        p = tmp_path / name
        p.write_text("#!/bin/sh\n" + body)
        p.chmod(p.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{tmp_path}:/usr/bin:/bin")


def test_build_timeout_degrades(tmp_path, monkeypatch):
    _fake(tmp_path, monkeypatch, "sleep 5\n")
    (tmp_path / "a.py").write_text("x=1\n")
    with pytest.raises(EnvError, match="joern timeout"):
        joern.JoernEngine(timeout=1).build(tmp_path, ["a.py"], "1g")


def test_no_network(tmp_path, monkeypatch):
    log = tmp_path / "log"
    _fake(tmp_path, monkeypatch, f'echo "$@ PROXY=$HTTPS_PROXY$http_proxy" >> {log}\nexit 1\n')
    monkeypatch.setenv("HTTPS_PROXY", "http://p:1")
    monkeypatch.setenv("http_proxy", "http://p:1")
    (tmp_path / "a.py").write_text("x=1\n")
    with pytest.raises(EnvError):
        joern.JoernEngine().build(tmp_path, ["a.py"], "1g")
    text = log.read_text()
    assert "PROXY=\n" in text
    assert "://" not in text.replace("PROXY=", "")


@pytest.mark.joern
@pytest.mark.skipif(shutil.which("joern") is None, reason="joern missing")
def test_real_version():
    assert joern.joern_version()


def test_export_format_error_is_env_and_value_error():
    assert issubclass(joern.ExportFormatError, EnvError)
    assert issubclass(joern.ExportFormatError, ValueError)
    with pytest.raises(joern.ExportFormatError):
        joern.parse_export("not json")
