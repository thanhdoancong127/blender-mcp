"""GPU guard: the 24GB card is shared by ComfyUI (:8188/:8189) and Blender. Refuse a heavy render
while ComfyUI is running a job or has little free VRAM. Unreachable ComfyUI = nothing to protect."""
import json
import os
import urllib.request

URLS = [u.strip() for u in os.environ.get(
    "COMFY_URLS", "http://127.0.0.1:8188,http://127.0.0.1:8189").split(",") if u.strip()]
MIN_FREE_GB = float(os.environ.get("MIN_FREE_VRAM_GB", "6"))


class GpuBusy(RuntimeError):
    pass


def _get(url: str, timeout: float = 2.0):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def check(engine: str, ignore: bool = False) -> None:
    """Raise GpuBusy if a GPU render would collide with ComfyUI. Workbench is exempt."""
    if ignore or engine == "BLENDER_WORKBENCH":
        return
    for base in URLS:
        try:
            q = _get(base + "/queue")
            running = q.get("queue_running") or []
            stats = _get(base + "/system_stats")
        except Exception:
            continue  # that instance is down
        if running:
            raise GpuBusy(f"ComfyUI {base} is running a job; wait or pass ignore_gpu_guard=True")
        for d in stats.get("devices", []):
            free = d.get("vram_free")
            if free is not None and free / 2**30 < MIN_FREE_GB:
                raise GpuBusy(
                    f"ComfyUI {base} leaves only {free / 2**30:.1f}GB VRAM free (< {MIN_FREE_GB}GB); "
                    "POST /free on it first, or pass ignore_gpu_guard=True")
