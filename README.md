# blender-mcp

An [MCP](https://modelcontextprotocol.io) server that lets agents **see and drive a running
Blender**: take viewport screenshots, render turntable views, inspect the scene and run Python.
It talks to the socket of the Blender MCP addon (default `127.0.0.1:9876`).

The point: an agent that can *look at* a 3D result can judge its quality instead of guessing.

## Tools

| Tool | What it does |
|---|---|
| `blender_scene_info` | Objects, counts and active camera of the open scene |
| `blender_object_info(object_name)` | Transform, dimensions, materials, mesh stats |
| `blender_run_python(code, timeout)` | Run Python in Blender (`bpy`); assign `result` to return a value |
| `blender_screenshot(max_size)` | Screenshot of the 3D viewport, returned as an image (Blender UI must be open) |
| `blender_turntable(views, size, engine, timeout)` | Render N evenly spaced views of all visible meshes, returned as images. View 0 = front (-Y). Scene render settings are restored afterwards |

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

### WSL note

If Blender runs on Windows and the server runs in WSL, `127.0.0.1` in WSL does not reach the
Windows loopback. Either run the server with the Windows Python (so it connects locally), or
point `BLENDER_MCP_HOST` at an address the addon is reachable on.

## Safety

`blender_run_python` executes arbitrary code in your Blender session. Keep the addon bound to
localhost and do not expose its port to a network. The addon handles one command at a time;
this client serializes calls, and heavy renders may need a larger `timeout`.

## Tests

```bash
uv run --group dev pytest
```

Tests cover the socket protocol against a fake addon (partial replies, errors, timeouts) and
check that the generated Blender snippets are valid Python. They do **not** run Blender;
`blender_screenshot` and `blender_turntable` still need a manual run against a real Blender.

## License

MIT
