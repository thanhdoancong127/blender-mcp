import json
import urllib.error

import numpy as np
import pytest
from PIL import Image as PILImage

from blender_mcp import client, gpu, ops, paths, refcompare, validate


# ---- paths ----
def test_to_native_converts_on_windows(monkeypatch):
    monkeypatch.setattr(paths, "IS_WINDOWS", True)
    assert paths.to_native("/mnt/d/comfy-ui/a b/x.glb") == "D:\\comfy-ui\\a b\\x.glb"
    assert paths.to_native("/mnt/c") == "C:\\"
    assert paths.to_native("D:\\already\\native.glb") == "D:\\already\\native.glb"
    assert paths.to_native("/tmp/x") == "/tmp/x"


def test_to_native_noop_off_windows(monkeypatch):
    monkeypatch.setattr(paths, "IS_WINDOWS", False)
    assert paths.to_native("/mnt/d/x") == "/mnt/d/x"


# ---- run_json ----
def _fake_call(result_text):
    return lambda *a, **k: {"executed": True, "result": result_text}


def test_run_json_parses_last_marker_line(monkeypatch):
    monkeypatch.setattr(client, "call", _fake_call('noise\n@@JSON@@{"a": 1}\n'))
    assert client.run_json("pass") == {"a": 1}


def test_run_json_injects_params(monkeypatch):
    seen = {}
    monkeypatch.setattr(client, "call", lambda t, p=None, **k: seen.update(code=p["code"]) or {"result": '@@JSON@@1\n'})
    client.run_json("pass", {"x": 'quote"s\n and \\ slash'})
    ns = {}
    exec(seen["code"], ns)  # the injected prelude must reproduce the params exactly
    assert ns["P"] == {"x": 'quote"s\n and \\ slash'}


def test_run_json_no_marker_raises(monkeypatch):
    monkeypatch.setattr(client, "call", _fake_call("just prints"))
    with pytest.raises(client.BlenderError, match="no result"):
        client.run_json("pass")


# ---- ops validation (no Blender needed) ----
def test_render_rejects_bad_args():
    with pytest.raises(ValueError):
        ops.render([{"az": 0, "el": 0}], mode="bogus")
    with pytest.raises(ValueError):
        ops.render([], mode="solid")
    with pytest.raises(ValueError):
        ops.render([{"az": 0, "el": 0}], size=8, mode="solid")
    with pytest.raises(ValueError):
        ops.turntable(0)


def test_timeout_adds_busy_hint(monkeypatch):
    def boom(*a, **k):
        raise TimeoutError("no reply")
    monkeypatch.setattr(client, "run_json", boom)
    with pytest.raises(TimeoutError, match="blender_stop"):
        ops.import_glb("x.glb")


# ---- gpu guard ----
def _patch_comfy(monkeypatch, queue, free_gb):
    monkeypatch.setattr(gpu, "URLS", ["http://c"])
    def get(url, timeout=2.0):
        if url.endswith("/queue"):
            return {"queue_running": queue}
        return {"devices": [{"vram_free": int(free_gb * 2**30)}]}
    monkeypatch.setattr(gpu, "_get", get)


def test_gpu_blocks_when_job_running(monkeypatch):
    _patch_comfy(monkeypatch, [["job"]], 20)
    with pytest.raises(gpu.GpuBusy, match="running a job"):
        gpu.check("BLENDER_EEVEE")


def test_gpu_blocks_on_low_vram(monkeypatch):
    _patch_comfy(monkeypatch, [], 2)
    with pytest.raises(gpu.GpuBusy, match="VRAM"):
        gpu.check("CYCLES")


def test_gpu_allows_and_exemptions(monkeypatch):
    _patch_comfy(monkeypatch, [["job"]], 1)
    gpu.check("BLENDER_WORKBENCH")
    gpu.check("BLENDER_EEVEE", ignore=True)
    _patch_comfy(monkeypatch, [], 20)
    gpu.check("BLENDER_EEVEE")


def test_gpu_unreachable_comfy_is_ok(monkeypatch):
    monkeypatch.setattr(gpu, "URLS", ["http://c"])
    def down(url, timeout=2.0):
        raise urllib.error.URLError("down")
    monkeypatch.setattr(gpu, "_get", down)
    gpu.check("BLENDER_EEVEE")


# ---- silhouette compare ----
def _rect_png(path, box, size=(200, 300), alpha=True):
    arr = np.zeros(size[::-1] + (4,), np.uint8)
    arr[..., :3] = 255 if not alpha else 0
    x0, y0, x1, y1 = box
    arr[y0:y1, x0:x1, :3] = 128
    arr[y0:y1, x0:x1, 3] = 255
    if not alpha:
        arr[..., 3] = 255
    PILImage.fromarray(arr).save(path)


def test_iou_identical_shape_different_position_and_scale(tmp_path):
    _rect_png(tmp_path / "a.png", (20, 30, 80, 150))          # 60x120
    _rect_png(tmp_path / "b.png", (100, 60, 160, 180), size=(300, 300))  # same shape, other place
    r = refcompare.silhouette_iou(tmp_path / "a.png", tmp_path / "b.png")
    assert r["iou"] > 0.97 and r["aspect_ratio_diff"] < 0.02


def test_iou_detects_proportion_mismatch(tmp_path):
    _rect_png(tmp_path / "a.png", (20, 30, 80, 150))           # aspect 0.5
    _rect_png(tmp_path / "b.png", (20, 30, 140, 150))          # aspect 1.0
    r = refcompare.silhouette_iou(tmp_path / "a.png", tmp_path / "b.png")
    assert abs(r["aspect_ratio_diff"] - 1.0) < 0.05  # 0.5 vs 1.0 -> 2x taller/wider


def test_ref_without_alpha_uses_background(tmp_path):
    _rect_png(tmp_path / "a.png", (20, 30, 80, 150), alpha=False)  # white bg, opaque
    _rect_png(tmp_path / "b.png", (20, 30, 80, 150))
    assert refcompare.silhouette_iou(tmp_path / "a.png", tmp_path / "b.png")["iou"] > 0.97


def test_empty_silhouette_raises(tmp_path):
    PILImage.fromarray(np.zeros((50, 50, 4), np.uint8)).save(tmp_path / "e.png")
    _rect_png(tmp_path / "b.png", (20, 30, 80, 150))
    with pytest.raises(ValueError, match="empty"):
        refcompare.silhouette_iou(tmp_path / "e.png", tmp_path / "b.png")


# ---- validator bridge ----
def test_validate_requires_env(monkeypatch):
    monkeypatch.delenv("ASSET_VALIDATOR_PY", raising=False)
    with pytest.raises(RuntimeError, match="ASSET_VALIDATOR_PY"):
        validate.validate("x.glb", 1.0, 100)


def test_validate_wraps_valueerror(monkeypatch, tmp_path):
    f = tmp_path / "v.py"
    f.write_text("def validate(p, h, t, tol=0.02, nonmanifold_max=0):\n    raise ValueError('dims bad')\n")
    monkeypatch.setenv("ASSET_VALIDATOR_PY", str(f))
    assert validate.validate("x.glb", 1.0, 100) == {"ok": False, "error": "dims bad"}
