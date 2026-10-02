"""Coarse silhouette comparison between a rendered mask and a reference image."""
from pathlib import Path

import numpy as np
from PIL import Image as PILImage


def load_mask(path, size: int | None = None) -> np.ndarray:
    """Boolean foreground mask. Uses alpha if the image has real transparency, else distance from the
    corner colour (reference images are expected on a plain background)."""
    im = PILImage.open(path).convert("RGBA")
    a = np.asarray(im)
    alpha = a[..., 3]
    if alpha.min() < 250:
        return alpha > 127
    rgb = a[..., :3].astype(np.int16)
    corners = np.stack([rgb[0, 0], rgb[0, -1], rgb[-1, 0], rgb[-1, -1]])
    bg = np.median(corners, axis=0)
    return np.abs(rgb - bg).sum(axis=2) > 40


def _crop(mask: np.ndarray):
    ys, xs = np.where(mask)
    if len(ys) == 0:
        raise ValueError("empty silhouette")
    return mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def silhouette_iou(render_png, ref_png, size: int = 256) -> dict:
    """IoU after cropping both silhouettes to their bounding boxes and resampling to size x size.

    Crop-normalising removes position/scale differences; `aspect_*` (w/h of the bounding boxes) reports
    proportion mismatch that the resample would otherwise hide.
    """
    out = {}
    crops = {}
    for name, p in (("render", render_png), ("ref", ref_png)):
        c = _crop(load_mask(p))
        out[f"aspect_{name}"] = round(c.shape[1] / c.shape[0], 4)
        im = PILImage.fromarray((c * 255).astype(np.uint8)).resize((size, size), PILImage.NEAREST)
        crops[name] = np.asarray(im) > 127
    inter = np.logical_and(crops["render"], crops["ref"]).sum()
    union = np.logical_or(crops["render"], crops["ref"]).sum()
    out["iou"] = round(float(inter / union), 4)
    a, b = out["aspect_render"], out["aspect_ref"]
    out["aspect_ratio_diff"] = round(max(a, b) / min(a, b) - 1, 4)  # symmetric: 0 = same proportions
    out["_overlay"] = crops
    return out


def overlay_png(crops: dict, dest) -> str:
    """Red = reference only, green = render only, yellow = both."""
    r, g = crops["ref"], crops["render"]
    img = np.zeros(r.shape + (3,), np.uint8)
    img[..., 0] = r * 255
    img[..., 1] = g * 255
    PILImage.fromarray(img).save(dest)
    return str(dest)
