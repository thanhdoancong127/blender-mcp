"""MCP server exposing a running Blender (via its MCP addon socket) to agents."""
import base64
import os
import tempfile
from pathlib import Path

from mcp.server.fastmcp import FastMCP, Image

from . import client, launcher
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
    """Run Python inside Blender (bpy available). The reply is the code's stdout: use print().

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
                      light: float = 3.0, timeout: float = 300.0):
    """Render evenly spaced turntable views of all visible meshes; returns the images.

    View 0 is the front (-Y). Uses the scene's lights/world as-is. `engine` is a Blender
    engine id (BLENDER_EEVEE, BLENDER_WORKBENCH, CYCLES); the scene's render settings are restored.
    """
    if not 1 <= views <= 16:
        raise ValueError("views must be 1..16")
    outdir = tempfile.mkdtemp(prefix="blender_mcp_tt_")
    code = TURNTABLE.format(outdir=outdir, n=views, size=size, engine=engine, light=light)
    client.call("execute_code", {"code": code}, timeout=timeout)
    paths = [Path(outdir) / f"view_{i:02d}.png" for i in range(views)]
    missing = [p.name for p in paths if not p.exists()]
    if missing:
        raise RuntimeError(f"turntable did not write: {missing}")
    return [Image(data=p.read_bytes(), format="png") for p in paths]


@mcp.tool()
def blender_status() -> dict:
    """Is Blender's MCP addon socket reachable right now?"""
    return {"ready": launcher.is_up(), "host": client.HOST, "port": client.PORT}


@mcp.tool()
def blender_start(blend_file: str = "", timeout: float = 90.0) -> dict:
    """Launch Blender (optionally opening `blend_file`) and wait until the addon socket answers.

    No-op if it is already up. Finds blender.exe in Program Files or via $BLENDER_EXE.
    """
    return launcher.start(blend_file or None, timeout)


@mcp.tool()
def blender_stop(force: bool = False) -> dict:
    """Quit Blender. Refuses when the file has unsaved changes unless force=True (which kills it)."""
    return launcher.stop(force)


def main():
    mcp.run()


if __name__ == "__main__":
    main()
