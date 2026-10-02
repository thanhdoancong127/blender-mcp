"""MCP server exposing a running Blender (via its MCP addon socket) to agents."""
import base64
import os
import tempfile
from pathlib import Path

from mcp.server.fastmcp import FastMCP, Image

from . import client
from .snippets import TURNTABLE

mcp = FastMCP("blender")


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
    """Run Python inside Blender (bpy available). Assign to `result` to return a value.

    Executes arbitrary code in the user's Blender session. Keep edits reproducible:
    record meaningful changes in your build scripts, not only in the live scene.
    """
    return client.call("execute_code", {"code": code}, timeout=timeout)


@mcp.tool()
def blender_screenshot(max_size: int = 1024) -> Image:
    """Screenshot of the Blender 3D viewport (needs the Blender UI open). Returns an image."""
    path = os.path.join(tempfile.gettempdir(), "blender_mcp_viewport.png")
    client.call("get_viewport_screenshot",
                {"max_size": max_size, "filepath": path, "format": "png"})
    return Image(data=Path(path).read_bytes(), format="png")


@mcp.tool()
def blender_turntable(views: int = 4, size: int = 512, engine: str = "BLENDER_EEVEE",
                      timeout: float = 300.0):
    """Render evenly spaced turntable views of all visible meshes; returns the images.

    View 0 is the front (-Y). Uses the scene's lights/world as-is. `engine` is a Blender
    engine id (BLENDER_EEVEE, BLENDER_WORKBENCH, CYCLES); the scene's render settings are restored.
    """
    if not 1 <= views <= 16:
        raise ValueError("views must be 1..16")
    outdir = tempfile.mkdtemp(prefix="blender_mcp_tt_")
    code = TURNTABLE.format(outdir=outdir, n=views, size=size, engine=engine)
    paths = client.call("execute_code", {"code": code}, timeout=timeout)
    # `result` from execute_code is nested by the addon: {"executed": True, "result": [...]}
    if isinstance(paths, dict):
        paths = paths.get("result", paths)
    return [Image(data=Path(p).read_bytes(), format="png") for p in paths]


def main():
    mcp.run()


if __name__ == "__main__":
    main()
