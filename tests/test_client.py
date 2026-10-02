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
    ast.parse(TURNTABLE.format(outdir="/tmp/x", n=4, size=256, engine="BLENDER_EEVEE"))
