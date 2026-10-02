"""Start/stop a local Blender (Windows native or from WSL) and wait for its MCP addon socket."""
import glob
import os
import shutil
import subprocess
import sys
import time

from . import client

IS_WINDOWS = sys.platform == "win32"


def is_wsl() -> bool:
    try:
        with open("/proc/version") as f:
            return "microsoft" in f.read().lower()
    except OSError:
        return False


def find_blender() -> str:
    """Path to blender.exe: $BLENDER_EXE, else the newest 'Blender Foundation' install."""
    env = os.environ.get("BLENDER_EXE")
    if env:
        if not os.path.isfile(env):
            raise FileNotFoundError(f"BLENDER_EXE does not exist: {env}")
        return env
    roots = (["C:\\Program Files"] if IS_WINDOWS else ["/mnt/c/Program Files"])
    found = []
    for root in roots:
        found += glob.glob(os.path.join(root, "Blender Foundation", "Blender *", "blender.exe"))
    if not found:
        raise FileNotFoundError("blender.exe not found; set BLENDER_EXE")
    # numeric-aware: "Blender 5.2" > "Blender 4.10" > "Blender 4.2"
    def ver(p):
        name = os.path.basename(os.path.dirname(p)).split()[-1]
        return tuple(int(x) if x.isdigit() else 0 for x in name.split("."))
    return max(found, key=ver)


def launch_cmd(exe: str, blend_file: str | None = None) -> list[str]:
    """Command that starts Blender detached from this process."""
    args = [blend_file] if blend_file else []
    if IS_WINDOWS:
        return [exe, *args]
    # WSL: hand off to Windows via `cmd /c start` so Blender outlives this process
    wpath = lambda p: subprocess.check_output(["wslpath", "-w", p], text=True).strip()
    wargs = [wpath(a) if a.startswith("/") else a for a in args]
    return ["cmd.exe", "/c", "start", "", wpath(exe), *wargs]


def is_up(timeout: float = 3.0) -> bool:
    try:
        client.call("get_scene_info", timeout=timeout)
        return True
    except (OSError, TimeoutError, client.BlenderError):
        return False


def wait_ready(timeout: float = 90.0, interval: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if is_up():
            return True
        time.sleep(min(interval, max(0.0, deadline - time.monotonic())))
    return False


def start(blend_file: str | None = None, timeout: float = 90.0) -> dict:
    if is_up():
        return {"started": False, "ready": True, "note": "Blender addon socket already responding"}
    exe = find_blender()
    cmd = launch_cmd(exe, blend_file)
    kwargs = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if IS_WINDOWS:
        kwargs["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(cmd, **kwargs)
    ready = wait_ready(timeout)
    out = {"started": True, "ready": ready, "exe": exe}
    if not ready:
        out["note"] = (f"Blender launched but the addon socket {client.HOST}:{client.PORT} did not answer "
                       f"in {timeout}s. Check the MCP addon is enabled and its server started; "
                       "from WSL, 127.0.0.1 may not reach the Windows host (see README).")
    return out


def _taskkill() -> list[str]:
    return ["taskkill" if IS_WINDOWS else "taskkill.exe", "/IM", "blender.exe", "/F"]


def stop(force: bool = False, wait: float = 15.0) -> dict:
    """Quit Blender. Refuses if the open file has unsaved changes unless force=True."""
    if is_up():
        if not force:
            dirty = client.call("execute_code", {"code": "import bpy\nresult = bpy.data.is_dirty"})
            if isinstance(dirty, dict):
                dirty = dirty.get("result", dirty)
            if dirty:
                return {"stopped": False, "note": "unsaved changes; save first or pass force=True"}
        try:
            client.call("execute_code", {"code": "import bpy\nbpy.ops.wm.quit_blender()"}, timeout=5)
        except (OSError, TimeoutError, client.BlenderError):
            pass  # connection drops as Blender exits
    elif not force:
        return {"stopped": False, "note": "addon socket not responding; nothing to stop gracefully (force=True kills blender.exe)"}
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline and is_up(1.0):
        time.sleep(1)
    if is_up(1.0) or force:
        if not force:
            return {"stopped": False, "note": "still running after quit request; retry with force=True"}
        if shutil.which(_taskkill()[0]):
            subprocess.run(_taskkill(), capture_output=True)
    return {"stopped": not is_up(1.0)}
