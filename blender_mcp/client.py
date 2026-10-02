"""Minimal client for the Blender MCP addon socket protocol.

The addon (ahujasid "blender-mcp" addon, default 127.0.0.1:9876) reads ONE JSON
command per connection and replies with ONE JSON object (no newline), keeping the
connection open. So: send, read until the buffer parses as JSON, close.
"""
import json
import os
import socket
import threading

HOST = os.environ.get("BLENDER_MCP_HOST", "127.0.0.1")
PORT = int(os.environ.get("BLENDER_MCP_PORT", "9876"))

# The addon handles one command at a time; serialize calls from this process.
_lock = threading.Lock()


class BlenderError(RuntimeError):
    pass


def call(cmd_type, params=None, host=None, port=None, timeout=30.0):
    """Send one command and return the addon's `result` payload.

    Raises BlenderError if the addon reports an error, TimeoutError if no complete
    reply arrives in `timeout` seconds, OSError if Blender is unreachable.
    """
    payload = json.dumps({"type": cmd_type, "params": params or {}}).encode("utf-8")
    with _lock:
        s = socket.create_connection((host or HOST, port or PORT), timeout=5)
        try:
            s.settimeout(timeout)
            s.sendall(payload)
            buf = b""
            while True:
                try:
                    chunk = s.recv(65536)
                except socket.timeout:
                    raise TimeoutError(f"no complete reply from Blender in {timeout}s")
                if not chunk:
                    raise BlenderError("Blender closed the connection before a complete reply")
                buf += chunk
                try:
                    resp = json.loads(buf.decode("utf-8"))
                    break
                except json.JSONDecodeError:
                    continue  # partial reply
        finally:
            s.close()
    if resp.get("status") != "success":
        raise BlenderError(resp.get("message") or str(resp))
    return resp.get("result")


MARK = "@@JSON@@"


def run_json(body, params=None, timeout=60.0):
    """Run a snippet body in Blender with params injected as `P`; return the JSON it printed.

    The addon returns the code's stdout, so snippets print one `@@JSON@@<json>` line.
    """
    code = "import json as _j\nP = _j.loads(%s)\n%s" % (json.dumps(json.dumps(params or {})), body)
    out = call("execute_code", {"code": code}, timeout=timeout)
    text = out.get("result", "") if isinstance(out, dict) else str(out)
    for line in reversed(str(text).splitlines()):
        if line.startswith(MARK):
            return json.loads(line[len(MARK):])
    raise BlenderError("Blender code produced no result; stdout tail: " + str(text)[-300:])
