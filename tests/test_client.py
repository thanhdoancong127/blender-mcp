import ast
import json
import socket
import threading

import pytest

from blender_mcp import client
from blender_mcp.snippets import TURNTABLE


def fake_addon(reply: bytes, chunks=1):
    """One-shot fake addon: records the command, replies (optionally in chunks)."""
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    seen = {}

    def run():
        conn, _ = srv.accept()
        seen["cmd"] = json.loads(conn.recv(65536).decode())
        step = max(1, len(reply) // chunks)
        for i in range(0, len(reply), step):
            conn.sendall(reply[i:i + step])
        threading.Event().wait(0.3)  # addon keeps the connection open
        conn.close()
        srv.close()

    threading.Thread(target=run, daemon=True).start()
    return srv.getsockname()[1], seen


def test_success_returns_result():
    port, seen = fake_addon(json.dumps({"status": "success", "result": {"a": 1}}).encode())
    assert client.call("get_scene_info", port=port) == {"a": 1}
    assert seen["cmd"] == {"type": "get_scene_info", "params": {}}


def test_partial_reply_is_reassembled():
    port, _ = fake_addon(json.dumps({"status": "success", "result": "x" * 5000}).encode(), chunks=7)
    assert client.call("t", port=port) == "x" * 5000


def test_error_status_raises():
    port, _ = fake_addon(json.dumps({"status": "error", "message": "boom"}).encode())
    with pytest.raises(client.BlenderError, match="boom"):
        client.call("t", port=port)


def test_timeout_when_reply_incomplete():
    port, _ = fake_addon(b'{"status": "succ')
    with pytest.raises(TimeoutError):
        client.call("t", port=port, timeout=0.2)


def test_unreachable_raises_oserror():
    with pytest.raises(OSError):
        client.call("t", port=1)


def test_turntable_snippet_is_valid_python():
    ast.parse(TURNTABLE.format(outdir="/tmp/x", n=4, size=256, engine="BLENDER_EEVEE", light=3.0))


# ---- launcher -------------------------------------------------------------
from blender_mcp import launcher


def test_find_blender_env_override(tmp_path, monkeypatch):
    exe = tmp_path / "blender.exe"
    exe.write_text("")
    monkeypatch.setenv("BLENDER_EXE", str(exe))
    assert launcher.find_blender() == str(exe)


def test_find_blender_env_missing_raises(monkeypatch):
    monkeypatch.setenv("BLENDER_EXE", "/nonexistent/blender.exe")
    with pytest.raises(FileNotFoundError):
        launcher.find_blender()


def test_find_blender_picks_newest_numeric(tmp_path, monkeypatch):
    monkeypatch.delenv("BLENDER_EXE", raising=False)
    root = tmp_path / "Blender Foundation"
    for v in ("4.2", "4.10", "5.2"):
        d = root / f"Blender {v}"
        d.mkdir(parents=True)
        (d / "blender.exe").write_text("")
    monkeypatch.setattr(launcher, "IS_WINDOWS", False)
    real_glob = launcher.glob.glob
    monkeypatch.setattr(launcher.glob, "glob", lambda pat: real_glob(str(root / "Blender *" / "blender.exe")))
    assert launcher.find_blender().endswith("Blender 5.2/blender.exe")


def test_is_up_false_when_unreachable(monkeypatch):
    monkeypatch.setattr(client, "PORT", 1)
    assert launcher.is_up(0.5) is False


def test_start_noop_when_already_up(monkeypatch):
    monkeypatch.setattr(launcher, "is_up", lambda timeout=3.0: True)
    r = launcher.start()
    assert r["started"] is False and r["ready"] is True


def test_stop_refuses_dirty_file(monkeypatch):
    monkeypatch.setattr(launcher, "is_up", lambda timeout=3.0: True)
    monkeypatch.setattr(client, "call", lambda *a, **k: True)
    r = launcher.stop()
    assert r["stopped"] is False and "unsaved" in r["note"]


def test_wait_ready_times_out(monkeypatch):
    monkeypatch.setattr(launcher, "is_up", lambda timeout=3.0: False)
    assert launcher.wait_ready(timeout=0.3, interval=0.1) is False
