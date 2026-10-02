# blender-mcp

An [MCP](https://modelcontextprotocol.io) server that lets agents **see and drive a running
Blender**: take viewport screenshots, render turntable views, inspect the scene and run Python.
It talks to the socket of the Blender MCP addon (default `127.0.0.1:9876`).

The point: an agent that can *look at* a 3D result can judge its quality instead of guessing.

## Tools

**Lifecycle**

| Tool | What it does |
|---|---|
| `blender_status` | Is the addon socket reachable? |
| `blender_start(blend_file, timeout)` | Launch Blender (optionally opening a file) and wait until the addon answers. No-op if already up |
| `blender_stop(force)` | Quit Blender. Refuses if the file has unsaved changes unless `force=True` (kills it) |

**Inspect / script**

| Tool | What it does |
|---|---|
| `blender_scene_info`, `blender_object_info(name)` | Objects, counts, transforms, materials |
| `blender_run_python(code, timeout)` | Run Python in Blender (`bpy`). The reply is the code's **stdout**, so use `print()` |
| `blender_screenshot(max_size)` | Viewport screenshot as an image (Blender UI must be open) |

**Rendering** (all return images; the scene is restored afterwards)

| Tool | What it does |
|---|---|
| `blender_turntable(views, size, elevation, mode, ...)` | Evenly spaced views of all visible meshes. View 0 = front (-Y) |
| `blender_render(views=[{az, el}], size, mode, ortho, objects, ...)` | Explicit camera views (az 0 = front, +az toward +X; el = elevation) |

`mode`: `material` (scene materials + temporary offset key light), `solid` (Workbench, fast), `wireframe`
(Cycles on CPU; needs enough pixels per polygon to show lines), `normal` (world-space, rgb = n*0.5+0.5),
`mask` (RGBA, silhouette in alpha). `material`/`normal`/`mask` use the GPU, see *GPU guard*.

**Files / assets**

| Tool | What it does |
|---|---|
| `blender_import_glb(path)` | Import GLB/glTF; returns new objects, triangle count, dimensions (m) |
| `blender_export_glb(path, objects)` | Export the scene or the listed objects |
| `blender_open(path)`, `blender_save(path)`, `blender_new_scene(keep)` | Open / save a .blend, clear the scene |
| `blender_validate_asset(glb_path, height_m, tri_budget, ...)` | Run an external asset validator (see below) |

**Rig / range of motion**

| Tool | What it does |
|---|---|
| `blender_rig_info(armature)` | Bones (parent, head/tail) and bound meshes |
| `blender_set_pose(armature, rotations)`, `blender_reset_pose` | Local Euler rotations in degrees per bone |
| `blender_pose_metrics(armature, mesh)` | Deformation of the current pose vs rest: face-area ratio percentiles, fraction stretched >2x / squashed <0.4x, volume ratio, zero-weight vertices |
| `blender_rom_test(armature, mesh, poses, ...)` | For each pose: apply, measure, render; JSON report + one image per pose; rig reset afterwards. The built-in Mixamo pose table has **uncalibrated axes**: check the images or pass your own `poses` |

**Likeness**

| Tool | What it does |
|---|---|
| `blender_compare_ref(ref_image, azimuth, elevation)` | Silhouette IoU between an orthographic mask render and a reference image, plus proportion mismatch and an overlay image. Coarse: both silhouettes are cropped to their bounding boxes |

Paths: `/mnt/<drive>/...` (WSL) is converted to `D:\...` when the server runs on Windows.

## Requirements

- Blender with the MCP addon enabled and its server listening (default port 9876)
- Python >= 3.10 and [`uv`](https://docs.astral.sh/uv/)

## Install

```bash
git clone https://github.com/thanhdoancong127/blender-mcp.git
cd blender-mcp
uv sync
```

### Claude Code

```bash
claude mcp add blender -- uv --directory /path/to/blender-mcp run python -m blender_mcp.server
```

### opencode / other stdio clients

Register a stdio server whose command is
`uv --directory /path/to/blender-mcp run python -m blender_mcp.server`.

### Configuration

| Env var | Default | Meaning |
|---|---|---|
| `BLENDER_MCP_HOST` | `127.0.0.1` | Host running Blender |
| `BLENDER_MCP_PORT` | `9876` | Addon socket port |
| `ASSET_VALIDATOR_PY` | unset | Path to a `validate_asset.py` exposing `validate(path, height_m, tri_budget, tol, nonmanifold_max)` (and optionally `validate_with_doc`). Its deps: `uv sync --extra validate` |
| `COMFY_URLS` | `http://127.0.0.1:8188,http://127.0.0.1:8189` | ComfyUI instances sharing the GPU (GPU guard) |
| `MIN_FREE_VRAM_GB` | `6` | GPU guard threshold |
| `BLENDER_EXE` | auto | Path to `blender.exe`; default is the newest install under `Program Files\Blender Foundation` |

### WSL note

If Blender runs on Windows and the server runs in WSL, `127.0.0.1` in WSL does not reach the
Windows loopback. Either run the server with the Windows Python (so it connects locally), or
point `BLENDER_MCP_HOST` at an address the addon is reachable on.

## GPU guard

If ComfyUI shares the GPU, GPU renders (`material`, `normal`, `mask`) are refused while a ComfyUI job is
running or free VRAM is below `MIN_FREE_VRAM_GB`; pass `ignore_gpu_guard=True` to override. `solid` and
`wireframe` do not use the GPU. An unreachable ComfyUI is treated as idle.

## Safety

`blender_run_python` executes arbitrary code in your Blender session. Keep the addon bound to
localhost and do not expose its port to a network. The addon handles one command at a time;
this client serializes calls, and heavy renders may need a larger `timeout`.

## Tests

```bash
uv sync --extra validate --group dev
uv run pytest
```

Unit tests cover the socket protocol against a fake addon, path conversion, the GPU guard, silhouette
comparison, the validator bridge and syntax of every Blender snippet. They do not run Blender.

Verified by hand against Blender 5.2 on Windows (through a real stdio MCP client): lifecycle, all render
modes, import/export, save/open, rig + pose metrics + ROM on a synthetic skinned tube, silhouette compare,
a 1.3M-triangle model (turntable < 2 s, GLB 135 MB, import 6.5 s) and the timeout path. Not yet verified:
real character rigs (the Mixamo pose table), Cycles GPU renders and the GPU guard against a busy ComfyUI.

## License

MIT
