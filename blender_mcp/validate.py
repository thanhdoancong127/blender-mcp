"""Bridge to an external asset validator script (e.g. the 3d-pipeline repo's scripts/validate_asset.py).

Set ASSET_VALIDATOR_PY to that file. Its deps (trimesh, pygltflib) are in the optional `validate` extra:
`uv sync --extra validate`.
"""
import importlib.util
import json
import os
from pathlib import Path

from .paths import to_native


def _load():
    p = os.environ.get("ASSET_VALIDATOR_PY")
    if not p:
        raise RuntimeError("set ASSET_VALIDATOR_PY to the validate_asset.py path")
    p = to_native(p)
    if not os.path.isfile(p):
        raise FileNotFoundError(p)
    try:
        spec = importlib.util.spec_from_file_location("_asset_validator", p)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except ImportError as e:
        raise RuntimeError(f"validator dependency missing ({e}); run `uv sync --extra validate`") from None
    return mod


def validate(glb_path, height_m, tri_budget, tol=0.02, nonmanifold_max=0, asset_json=""):
    mod = _load()
    glb = to_native(glb_path)
    try:
        if asset_json:
            doc = json.loads(Path(to_native(asset_json)).read_text(encoding="utf-8"))
            return mod.validate_with_doc(glb, doc, height_m=height_m, tri_budget=tri_budget, tol=tol,
                                         nonmanifold_max=nonmanifold_max)
        return mod.validate(glb, height_m, tri_budget, tol=tol, nonmanifold_max=nonmanifold_max)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
