"""MCP server exposing a running Blender (via its MCP addon socket) to agents."""
import json
import os
import tempfile
from pathlib import Path

from mcp.server.fastmcp import FastMCP, Image

from . import client, launcher, ops, validate
from .paths import to_native

mcp = FastMCP("blender")


def _img(p) -> Image:
    return Image(data=Path(p).read_bytes(), format="png")


# ---- lifecycle -----------------------------------------------------------------------------------------

@mcp.tool()
def blender_status() -> dict:
    """Is Blender's MCP addon socket reachable right now?"""
    return {"ready": launcher.is_up(), "host": client.HOST, "port": client.PORT}


@mcp.tool()
def blender_start(blend_file: str = "", timeout: float = 90.0) -> dict:
    """Launch Blender (optionally opening `blend_file`) and wait until the addon socket answers.

    No-op if it is already up. Finds blender.exe in Program Files or via $BLENDER_EXE.
    """
    return launcher.start(to_native(blend_file) if blend_file else None, timeout)


@mcp.tool()
def blender_stop(force: bool = False) -> dict:
    """Quit Blender. Refuses when the file has unsaved changes unless force=True (which kills it)."""
    return launcher.stop(force)


# ---- inspect / scripting -------------------------------------------------------------------------------

@mcp.tool()
def blender_scene_info() -> dict:
    """Summary of the open Blender scene (objects, counts, active camera)."""
    return client.call("get_scene_info")


@mcp.tool()
def blender_object_info(object_name: str) -> dict:
    """Transform, dimensions, materials and mesh stats for one object."""
    return client.call("get_object_info", {"object_name": object_name})


@mcp.tool()
def blender_run_python(code: str, timeout: float = 60.0):
    """Run Python inside Blender (bpy available). The reply is the code's stdout: use print().

    Executes arbitrary code in the user's Blender session. Keep edits reproducible:
    record meaningful changes in your build scripts, not only in the live scene.
    """
    return client.call("execute_code", {"code": code}, timeout=timeout)


@mcp.tool()
def blender_screenshot(max_size: int = 1024) -> Image:
    """Screenshot of the Blender 3D viewport (needs the Blender UI open). Returns an image."""
    path = os.path.join(tempfile.gettempdir(), "blender_mcp_viewport.png")
    client.call("get_viewport_screenshot", {"max_size": max_size, "filepath": path, "format": "png"})
    return _img(path)


# ---- rendering -----------------------------------------------------------------------------------------

@mcp.tool()
def blender_turntable(views: int = 4, size: int = 512, elevation: float = 20.0, mode: str = "material",
                      engine: str = "BLENDER_EEVEE", light: float = 3.0, ignore_gpu_guard: bool = False,
                      timeout: float = 300.0):
    """Render evenly spaced turntable views of all visible meshes; returns the images. View 0 = front (-Y).

    mode: material (scene materials + temporary offset key light of strength `light`), solid (Workbench,
    fast), wireframe (Cycles on CPU), normal (world-space), mask (alpha silhouette). solid and wireframe
    skip the GPU guard. The scene is restored.
    Refuses to render while ComfyUI is running a job or VRAM is low, unless ignore_gpu_guard=True.
    """
    paths = ops.turntable(views, elevation, size=size, engine=engine, light=light, mode=mode,
                          ignore_gpu_guard=ignore_gpu_guard, timeout=timeout)
    return [_img(p) for p in paths]


@mcp.tool()
def blender_render(views: list[dict], size: int = 512, mode: str = "material", ortho: bool = False,
                   objects: list[str] | None = None, engine: str = "BLENDER_EEVEE", light: float = 3.0,
                   focus: dict | None = None, ignore_gpu_guard: bool = False, timeout: float = 300.0):
    """Render explicit camera views: views=[{"az": degrees, "el": degrees}, ...] (az 0 = front/-Y, +az toward +X,
    el = elevation). `objects` limits the framed/rendered meshes; ortho=True gives an orthographic camera.
    focus={"center": [x, y, z], "radius": r} frames that world-space region (e.g. the head of a full body).
    Modes as in blender_turntable. Returns the images.
    """
    paths = ops.render(views, size=size, engine=engine, light=light, mode=mode, ortho=ortho, objects=objects,
                       focus=focus, ignore_gpu_guard=ignore_gpu_guard, timeout=timeout)
    return [_img(p) for p in paths]


@mcp.tool()
def blender_render_scene(width: int = 640, height: int = 640, mode: str = "beauty", frames: list[int] | None = None,
                         objects: list[str] | None = None, hide: list[str] | None = None,
                         engine: str = "BLENDER_EEVEE", ignore_gpu_guard: bool = False, timeout: float = 300.0):
    """Render through the scene's OWN active camera and lights (shot rendering), one image per frame.
    mode: beauty | mask (needs `objects`: only they are drawn, white, silhouette in alpha) | normal.
    `hide` hides objects for this render (e.g. actors -> clean background plate). Returns the images."""
    paths = ops.render_scene((width, height), mode, frames or [1], objects, hide, engine,
                             ignore_gpu_guard=ignore_gpu_guard, timeout=timeout)
    return [_img(p) for p in paths]


# ---- files / assets ------------------------------------------------------------------------------------

@mcp.tool()
def blender_import_glb(path: str) -> dict:
    """Import a GLB/glTF/FBX into the open scene. Returns new objects, triangle count and dimensions (x,y,z in m)."""
    return ops.import_glb(path)


@mcp.tool()
def blender_export_glb(path: str, objects: list[str] | None = None) -> dict:
    """Export to a .glb. With `objects`, only those; otherwise the whole scene."""
    return ops.export_glb(path, objects)


@mcp.tool()
def blender_open(path: str) -> dict:
    """Open a .blend (replaces the current scene; unsaved changes are lost)."""
    return ops.open_blend(path)


@mcp.tool()
def blender_save(path: str = "") -> dict:
    """Save the current file, or save as `path` when given."""
    return ops.save(path)


@mcp.tool()
def blender_new_scene(keep: list[str] | None = None) -> dict:
    """Remove all objects (orphan data purged). keep: object types to keep, e.g. ["CAMERA", "LIGHT"]."""
    return ops.clear_scene(keep)


@mcp.tool()
def blender_validate_asset(glb_path: str, height_m: float, tri_budget: int, tol: float = 0.02,
                           nonmanifold_max: int = 0, asset_json: str = "") -> dict:
    """Run the asset validator (dims within tol of height_m, tri budget, NaN, zero-area faces, non-manifold,
    PBR maps). With asset_json also cross-checks the sidecar. Needs ASSET_VALIDATOR_PY (see README)."""
    return validate.validate(glb_path, height_m, tri_budget, tol, nonmanifold_max, asset_json)


# ---- rigging / ROM -------------------------------------------------------------------------------------

@mcp.tool()
def blender_rig_info(armature: str) -> dict:
    """Bones (name, parent, head/tail in rest pose) of an armature and the meshes bound to it."""
    return ops.rig_info(armature)


@mcp.tool()
def blender_set_pose(armature: str, rotations: dict, reset: bool = True) -> dict:
    """Set local Euler rotations (degrees) on pose bones: rotations={"bone": [x, y, z]}. reset=True clears
    other bones first. Use blender_reset_pose afterwards to go back to rest."""
    return ops.set_pose(armature, rotations, reset)


@mcp.tool()
def blender_pose_aim(armature: str, aim: dict, reset: bool = True) -> dict:
    """Pose by direction, no bone-axis knowledge needed: aim={"RightArm": [1, 0, 0.2], "Spine": [0, 0, 1]}
    points each bone's limb (its head to the head of its continuing child, not the bone tail) along that WORLD direction, parents first. Returns the residual angle per
    bone in degrees. Prefer this over blender_set_pose for authoring poses."""
    return ops.aim_pose(armature, aim, reset)


@mcp.tool()
def blender_key_pose(armature: str, frame: int, with_object: bool = True) -> dict:
    """Keyframe the current pose of the armature at `frame` (all bones, plus the object's location/rotation).
    Workflow for a clip: blender_timeline(frame=f) -> blender_pose_aim(...) -> blender_key_pose(frame=f), repeat."""
    return ops.key_pose(armature, frame, with_object)


@mcp.tool()
def blender_timeline(start: int | None = None, end: int | None = None, fps: int | None = None,
                     frame: int | None = None) -> dict:
    """Set the frame range / fps and/or jump to a frame (which evaluates existing keyframes)."""
    return ops.timeline(start, end, fps, frame)


@mcp.tool()
def blender_reset_pose(armature: str) -> dict:
    """Return all pose bones of the armature to the rest pose."""
    return ops.reset_pose(armature)


@mcp.tool()
def blender_pose_metrics(armature: str, mesh: str) -> dict:
    """Deformation metrics of the CURRENT pose vs rest: face-area ratio percentiles, fraction of faces
    stretched >2x or squashed <0.4x, volume ratio (volume loss = candy-wrapper joints), and the number of
    vertices with zero skin weight."""
    return ops.pose_metrics(armature, mesh)


@mcp.tool()
def blender_rom_test(armature: str, mesh: str, poses: dict | None = None, size: int = 384,
                     mode: str = "material", ignore_gpu_guard: bool = False, timeout: float = 300.0):
    """Range-of-motion test: for each pose apply it, measure deformation and render. Returns a JSON report
    followed by one image per pose; the rig is reset to rest afterwards.

    poses={"name": {"bone": [x, y, z]}} in degrees. Default is a Mixamo-named table whose rotation axes are
    NOT calibrated: check the images and pass your own poses if they look wrong.
    """
    res = ops.rom_test(armature, mesh, poses, size=size, mode=mode, ignore_gpu_guard=ignore_gpu_guard,
                       timeout=timeout)
    return [json.dumps({"pose_table": res["pose_table"], "report": res["report"]}, indent=1)] + \
           [_img(p) for p in res["images"]]


@mcp.tool()
def blender_compare_ref(ref_image: str, azimuth: float = 0.0, elevation: float = 0.0,
                        objects: list[str] | None = None):
    """Coarse likeness check: silhouette IoU between an orthographic render of the model (from azimuth/
    elevation) and a reference image (alpha, or plain background). Both are cropped to their bounding boxes,
    so position/scale are ignored; aspect_ratio_diff reports proportion mismatch. Returns JSON and an overlay
    image (red = reference only, green = render only, yellow = both)."""
    res = ops.compare_ref(ref_image, azimuth, elevation, objects)
    return [json.dumps({k: v for k, v in res.items() if k != "overlay_png"}), _img(res["overlay_png"])]


def main():
    mcp.run()


if __name__ == "__main__":
    main()
