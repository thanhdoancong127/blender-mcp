"""High-level Blender operations. No `mcp` dependency, so they are usable and testable on their own."""
import tempfile
from pathlib import Path

from . import client, gpu, snippets
from .paths import to_native

BUSY_HINT = (" Blender may still be rendering and busy: check blender_status; "
             "blender_stop(force=True) kills it if it is hung.")


def _run(body, params, timeout):
    try:
        return client.run_json(body, params, timeout)
    except TimeoutError as e:
        raise TimeoutError(str(e) + BUSY_HINT) from None


def render(views, size=512, engine="BLENDER_EEVEE", light=3.0, mode="material", ortho=False,
           objects=None, outdir=None, prefix="view_", timeout=300.0, ignore_gpu_guard=False):
    """Render each {az, el} view (degrees; az=0 is front/-Y). mode: material|solid|wireframe|normal|mask.

    Returns the list of PNG paths. `normal` is world-space (rgb = n*0.5+0.5); `mask` is RGBA with the
    silhouette in alpha.
    """
    if mode not in ("material", "solid", "wireframe", "normal", "mask"):
        raise ValueError("mode must be material|solid|wireframe|normal|mask")
    if not views:
        raise ValueError("no views")
    if not 16 <= size <= 4096:
        raise ValueError("size must be 16..4096")
    # solid (Workbench) and wireframe (Cycles on CPU) do not use the GPU
    gpu.check("BLENDER_WORKBENCH" if mode in ("solid", "wireframe") else engine, ignore_gpu_guard)
    outdir = to_native(outdir) if outdir else tempfile.mkdtemp(prefix="blender_mcp_")
    params = dict(outdir=outdir, views=views, size=size, engine=engine, light=light, mode=mode,
                  ortho=ortho, objects=objects or [], prefix=prefix)
    paths = _run(snippets.RENDER, params, timeout)
    missing = [p for p in paths if not Path(p).exists()]
    if missing:
        raise RuntimeError(f"render did not write: {missing}")
    return paths


def turntable(n=4, elevation=20.0, **kw):
    if not 1 <= n <= 16:
        raise ValueError("views must be 1..16")
    return render([{"az": 360.0 * i / n, "el": elevation} for i in range(n)], **kw)


def import_glb(path, timeout=300.0):
    return _run(snippets.IMPORT_GLB, {"path": to_native(path)}, timeout)


def export_glb(path, objects=None, timeout=300.0):
    return _run(snippets.EXPORT_GLB, {"path": to_native(path), "objects": objects or []}, timeout)


def save(path="", timeout=120.0):
    return _run(snippets.SAVE, {"path": to_native(path) if path else ""}, timeout)


def open_blend(path, timeout=120.0):
    return _run(snippets.OPEN, {"path": to_native(path)}, timeout)


def clear_scene(keep=None, timeout=60.0):
    """Delete all objects (and purge orphans). keep: object types to keep, e.g. ["CAMERA", "LIGHT"]."""
    return _run(snippets.CLEAR, {"keep": keep or []}, timeout)


def rig_info(armature, timeout=60.0):
    return _run(snippets.RIG_INFO, {"armature": armature}, timeout)


def set_pose(armature, rotations, reset=True, timeout=60.0):
    return _run(snippets.SET_POSE, {"armature": armature, "rotations": rotations, "reset": reset}, timeout)


def reset_pose(armature, timeout=60.0):
    return set_pose(armature, {}, True, timeout)


def pose_metrics(armature, mesh, timeout=120.0):
    return _run(snippets.POSE_METRICS, {"armature": armature, "mesh": mesh}, timeout)


# Starting point only: bone names follow Mixamo/Make-It-Animatable, but the rotation AXES depend on each
# rig's bone roll and are NOT calibrated. Always look at the returned images and adjust.
ROM_POSES_MIXAMO = {
    "arms_up": {"mixamorig:LeftArm": [0, 0, 150], "mixamorig:RightArm": [0, 0, -150]},
    "elbow_90": {"mixamorig:LeftForeArm": [0, 0, 90], "mixamorig:RightForeArm": [0, 0, -90]},
    "knee_90": {"mixamorig:LeftLeg": [90, 0, 0], "mixamorig:RightLeg": [90, 0, 0]},
    "hip_flex_90": {"mixamorig:LeftUpLeg": [-90, 0, 0], "mixamorig:RightUpLeg": [-90, 0, 0]},
    "head_turn_90": {"mixamorig:Head": [0, 90, 0]},
}


def rom_test(armature, mesh, poses=None, size=384, views=None, mode="material", outdir=None,
             ignore_gpu_guard=False, timeout=300.0):
    """For each named pose: apply, measure deformation vs rest, render. The pose is always reset after.

    poses: {name: {bone: [x, y, z] degrees}}; default is the uncalibrated Mixamo table.
    Returns {"report": [...], "images": [...]} where each report row has metrics and its image paths.
    """
    names = {b["name"] for b in rig_info(armature)["bones"]}
    table, source = poses, "custom"
    if table is None:
        table = {k: v for k, v in ROM_POSES_MIXAMO.items() if all(b in names for b in v)}
        source = "builtin-mixamo (uncalibrated axes)"
        if not table:
            raise ValueError("no pose table given and the rig has no Mixamo bone names; pass poses=")
    views = views or [{"az": 0, "el": 5}]
    outdir = to_native(outdir) if outdir else tempfile.mkdtemp(prefix="blender_mcp_rom_")
    report, images = [], []
    try:
        for pname, rot in table.items():
            set_pose(armature, rot, True)
            row = {"pose": pname, **pose_metrics(armature, mesh)}
            paths = render(views, size=size, mode=mode, outdir=outdir, prefix=f"{pname}_",
                           ignore_gpu_guard=ignore_gpu_guard, timeout=timeout)
            row["images"] = paths
            images += paths
            report.append(row)
    finally:
        reset_pose(armature)
    return {"pose_table": source, "report": report, "images": images}


def compare_ref(ref_path, azimuth=0.0, elevation=0.0, objects=None, size=512, outdir=None):
    """Silhouette IoU between an orthographic mask render and a reference image (coarse)."""
    from . import refcompare
    ref = to_native(ref_path)
    paths = render([{"az": azimuth, "el": elevation}], size=size, mode="mask", ortho=True, objects=objects,
                   outdir=outdir, prefix="mask_", engine="BLENDER_EEVEE")
    res = refcompare.silhouette_iou(paths[0], ref)
    crops = res.pop("_overlay")
    res["overlay_png"] = refcompare.overlay_png(crops, Path(paths[0]).with_name("overlay.png"))
    res["render_png"] = paths[0]
    return res
