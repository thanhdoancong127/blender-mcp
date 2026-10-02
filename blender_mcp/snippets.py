"""Python source executed inside Blender (via the addon's execute_code).

Each body expects `P` (dict of params, injected by client.run_json) and prints one line
"@@JSON@@<json>" with its result (the addon returns stdout, not a `result` variable).
"""

RENDER = r'''
import bpy, math, os, mathutils
os.makedirs(P["outdir"], exist_ok=True)
sc = bpy.context.scene; vl = bpy.context.view_layer; r = sc.render
names = P.get("objects") or []
deps = bpy.context.evaluated_depsgraph_get()
meshes = [o for o in sc.objects if o.type == "MESH" and o.visible_get() and (not names or o.name in names)]
if not meshes:
    raise RuntimeError("no visible mesh objects to render")
pts = []
for o in meshes:
    eo = o.evaluated_get(deps)
    pts += [eo.matrix_world @ mathutils.Vector(c) for c in eo.bound_box]
lo = mathutils.Vector(map(min, zip(*pts))); hi = mathutils.Vector(map(max, zip(*pts)))
center = (lo + hi) / 2; radius = max((hi - lo).length / 2, 1e-3)
if P.get("focus"):  # zoom on a region (e.g. the head of a full-body character), world coordinates
    center = mathutils.Vector(P["focus"]["center"]); radius = max(float(P["focus"]["radius"]), 1e-3)
mode = P["mode"]
# wireframe needs Cycles (the Wireframe node does not work in EEVEE); CPU keeps the GPU free for ComfyUI
engine = "BLENDER_WORKBENCH" if mode == "solid" else ("CYCLES" if mode == "wireframe" else P["engine"])
sh = sc.display.shading
cy = sc.cycles
saved_cy = (cy.device, cy.samples, cy.use_denoising)
saved = dict(cam=sc.camera, engine=r.engine, rx=r.resolution_x, ry=r.resolution_y, pct=r.resolution_percentage,
             fp=r.filepath, ff=r.image_settings.file_format, cm=r.image_settings.color_mode,
             ft=r.film_transparent, mo=vl.material_override, light=sh.light, color=sh.color_type)
cam_data = bpy.data.cameras.new("_mcp_cam"); cam = bpy.data.objects.new("_mcp_cam", cam_data)
sc.collection.objects.link(cam); sc.camera = cam
extra = [cam]; sun_data = None; override = None
if P.get("ortho"):
    cam_data.type = "ORTHO"; cam_data.ortho_scale = radius * 2.2
    dist = radius * 3; cam_data.clip_start = max(dist - radius * 2, 0.001); cam_data.clip_end = dist + radius * 2
else:
    cam_data.lens = 50
    dist = radius / math.sin(cam_data.angle / 2) * 1.15
    cam_data.clip_start = max(radius * 0.01, 0.001); cam_data.clip_end = dist * 3 + radius * 2
if mode == "material":
    sun_data = bpy.data.lights.new("_mcp_sun", "SUN"); sun_data.energy = P["light"]
    sun = bpy.data.objects.new("_mcp_sun", sun_data); sc.collection.objects.link(sun); extra.append(sun)
    sun.parent = cam
    sun.rotation_euler = (math.radians(35), 0, math.radians(-30))  # offset from view axis so shading shows form
if mode in ("wireframe", "normal", "mask"):
    override = bpy.data.materials.new("_mcp_override"); override.use_nodes = True
    nt = override.node_tree; nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial"); em = nt.nodes.new("ShaderNodeEmission")
    if mode == "mask":
        em.inputs["Color"].default_value = (1, 1, 1, 1); nt.links.new(em.outputs[0], out.inputs[0])
    elif mode == "normal":
        g = nt.nodes.new("ShaderNodeNewGeometry"); m = nt.nodes.new("ShaderNodeVectorMath"); m.operation = "MULTIPLY_ADD"
        m.inputs[1].default_value = (0.5, 0.5, 0.5); m.inputs[2].default_value = (0.5, 0.5, 0.5)
        nt.links.new(g.outputs["Normal"], m.inputs[0]); nt.links.new(m.outputs[0], em.inputs["Color"])
        nt.links.new(em.outputs[0], out.inputs[0])
    else:
        w = nt.nodes.new("ShaderNodeWireframe"); w.use_pixel_size = True; w.inputs[0].default_value = 1.0
        dark = nt.nodes.new("ShaderNodeEmission"); dark.inputs["Color"].default_value = (0.02, 0.02, 0.02, 1)
        em.inputs["Color"].default_value = (1, 1, 1, 1)
        mix = nt.nodes.new("ShaderNodeMixShader")
        nt.links.new(w.outputs[0], mix.inputs[0]); nt.links.new(dark.outputs[0], mix.inputs[1])
        nt.links.new(em.outputs[0], mix.inputs[2]); nt.links.new(mix.outputs[0], out.inputs[0])
    vl.material_override = override
r.engine = engine
r.resolution_x = r.resolution_y = P["size"]; r.resolution_percentage = 100
r.image_settings.file_format = "PNG"
if mode == "mask":
    r.film_transparent = True; r.image_settings.color_mode = "RGBA"
if mode == "solid":
    sh.light = "STUDIO"; sh.color_type = "MATERIAL"
if mode == "wireframe":
    cy.device = "CPU"; cy.samples = 8; cy.use_denoising = False
paths = []
try:
    for i, v in enumerate(P["views"]):
        az = math.radians(v["az"]); el = math.radians(v["el"])
        # asset faces -Y (Blender front): az=0 is the front view, +az moves camera toward +X
        d = mathutils.Vector((math.sin(az) * math.cos(el), -math.cos(az) * math.cos(el), math.sin(el)))
        cam.location = center + d * dist
        cam.rotation_euler = (center - cam.location).to_track_quat("-Z", "Y").to_euler()
        p = os.path.join(P["outdir"], "%s%02d.png" % (P["prefix"], i))
        r.filepath = p
        bpy.ops.render.render(write_still=True)
        paths.append(p)
finally:
    for o in extra:
        sc.collection.objects.unlink(o); bpy.data.objects.remove(o)
    bpy.data.cameras.remove(cam_data)
    if sun_data: bpy.data.lights.remove(sun_data)
    if override: bpy.data.materials.remove(override)
    sc.camera = saved["cam"]; r.engine = saved["engine"]
    r.resolution_x = saved["rx"]; r.resolution_y = saved["ry"]; r.resolution_percentage = saved["pct"]
    r.filepath = saved["fp"]; r.image_settings.file_format = saved["ff"]; r.image_settings.color_mode = saved["cm"]
    r.film_transparent = saved["ft"]; vl.material_override = saved["mo"]; sh.light = saved["light"]; sh.color_type = saved["color"]
    cy.device, cy.samples, cy.use_denoising = saved_cy
import json
print("@@JSON@@" + json.dumps(paths))
'''

IMPORT_GLB = r'''
import bpy, json
before = set(bpy.data.objects.keys())
ext = P["path"].lower().rsplit(".", 1)[-1]
if ext in ("glb", "gltf"):
    bpy.ops.import_scene.gltf(filepath=P["path"])
elif ext == "fbx":
    bpy.ops.import_scene.fbx(filepath=P["path"])
else:
    raise RuntimeError("unsupported model format: ." + ext)
new = [bpy.data.objects[n] for n in bpy.data.objects.keys() if n not in before]
tris = 0; pts = []
import mathutils
for o in new:
    if o.type == "MESH":
        o.data.calc_loop_triangles(); tris += len(o.data.loop_triangles)
        pts += [o.matrix_world @ mathutils.Vector(c) for c in o.bound_box]
dims = None
if pts:
    lo = [min(p[i] for p in pts) for i in range(3)]; hi = [max(p[i] for p in pts) for i in range(3)]
    dims = [round(hi[i] - lo[i], 5) for i in range(3)]
print("@@JSON@@" + json.dumps({"objects": [{"name": o.name, "type": o.type} for o in new], "tri_count": tris, "dims_m_xyz": dims}))
'''

EXPORT_GLB = r'''
import bpy, json
names = P.get("objects") or []
if names:
    bpy.ops.object.select_all(action="DESELECT")
    for n in names:
        bpy.data.objects[n].select_set(True)
bpy.ops.export_scene.gltf(filepath=P["path"], export_format="GLB", use_selection=bool(names))
print("@@JSON@@" + json.dumps({"path": P["path"]}))
'''

SAVE = r'''
import bpy, json
if P.get("path"):
    bpy.ops.wm.save_as_mainfile(filepath=P["path"])
else:
    bpy.ops.wm.save_mainfile()
print("@@JSON@@" + json.dumps({"path": bpy.data.filepath}))
'''

OPEN = r'''
import bpy, json
bpy.ops.wm.open_mainfile(filepath=P["path"])
print("@@JSON@@" + json.dumps({"path": bpy.data.filepath, "objects": len(bpy.data.objects)}))
'''

CLEAR = r'''
import bpy, json
keep = set(P.get("keep") or [])
n = 0
for o in list(bpy.data.objects):
    if o.type not in keep:
        bpy.data.objects.remove(o, do_unlink=True); n += 1
bpy.ops.outliner.orphans_purge(do_recursive=True)
print("@@JSON@@" + json.dumps({"removed": n, "remaining": len(bpy.data.objects)}))
'''

RIG_INFO = r'''
import bpy, json
a = bpy.data.objects[P["armature"]]
if a.type != "ARMATURE":
    raise RuntimeError("%s is not an armature" % a.name)
bones = [{"name": b.name, "parent": b.parent.name if b.parent else None,
          "head": [round(x, 4) for x in b.head_local], "tail": [round(x, 4) for x in b.tail_local]} for b in a.data.bones]
meshes = [o.name for o in bpy.data.objects if o.type == "MESH" and any(m.type == "ARMATURE" and m.object == a for m in o.modifiers)]
print("@@JSON@@" + json.dumps({"bones": bones, "bound_meshes": meshes}))
'''

# Set (or reset) local euler rotations in degrees on pose bones. P: armature, rotations{bone:[x,y,z]}, reset(bool)
SET_POSE = r'''
import bpy, json, math
a = bpy.data.objects[P["armature"]]
if P.get("reset", True):
    for pb in a.pose.bones:
        pb.rotation_mode = "XYZ"; pb.rotation_euler = (0, 0, 0); pb.location = (0, 0, 0); pb.scale = (1, 1, 1)
missing = [b for b in P.get("rotations", {}) if b not in a.pose.bones]
if missing:
    raise RuntimeError("unknown bones: %s" % missing)
for b, rot in P.get("rotations", {}).items():
    pb = a.pose.bones[b]; pb.rotation_mode = "XYZ"
    pb.rotation_euler = [math.radians(x) for x in rot]
bpy.context.view_layer.update()
print("@@JSON@@" + json.dumps({"posed": list(P.get("rotations", {}))}))
'''

# Deformation metrics of the current pose vs the rest pose. P: armature, mesh
POSE_METRICS = r'''
import bpy, json, numpy as np
arm = bpy.data.objects[P["armature"]]; mesh = bpy.data.objects[P["mesh"]]
saved = [(pb, pb.location.copy(), pb.rotation_euler.copy(), pb.rotation_quaternion.copy(), pb.scale.copy(), pb.rotation_mode)
         for pb in arm.pose.bones]
res = {}
try:
    for state in ("rest", "pose"):
        for pb, loc, eul, quat, scl, mode in saved:
            if state == "rest":
                pb.location = (0, 0, 0); pb.rotation_euler = (0, 0, 0); pb.rotation_quaternion = (1, 0, 0, 0); pb.scale = (1, 1, 1)
            else:
                pb.location = loc; pb.rotation_euler = eul; pb.rotation_quaternion = quat; pb.scale = scl
        bpy.context.view_layer.update()
        eo = mesh.evaluated_get(bpy.context.evaluated_depsgraph_get()); me = eo.to_mesh()
        a = np.empty(len(me.polygons), np.float64); me.polygons.foreach_get("area", a)
        co = np.empty(len(me.vertices) * 3, np.float64); me.vertices.foreach_get("co", co); co = co.reshape(-1, 3)
        me.calc_loop_triangles(); t = np.empty(len(me.loop_triangles) * 3, np.int64)
        me.loop_triangles.foreach_get("vertices", t); t = t.reshape(-1, 3)
        vol = float(np.einsum("ij,ij->i", co[t[:, 0]], np.cross(co[t[:, 1]], co[t[:, 2]])).sum() / 6)
        res[state] = (a, vol); eo.to_mesh_clear()
finally:
    for pb, loc, eul, quat, scl, mode in saved:
        pb.location = loc; pb.rotation_euler = eul; pb.rotation_quaternion = quat; pb.scale = scl; pb.rotation_mode = mode
    bpy.context.view_layer.update()
ra, rv = res["rest"]; pa, pv = res["pose"]
ok = ra > 1e-12; ratio = pa[ok] / ra[ok]
zero_w = None
if len(mesh.data.vertices) <= 500000:
    zero_w = sum(1 for v in mesh.data.vertices if sum(g.weight for g in v.groups) <= 1e-6)
out = {"faces": int(len(ra)), "area_ratio_p01": float(np.percentile(ratio, 1)), "area_ratio_p50": float(np.percentile(ratio, 50)),
       "area_ratio_p99": float(np.percentile(ratio, 99)), "frac_stretched_gt2": float((ratio > 2).mean()),
       "frac_squashed_lt0.4": float((ratio < 0.4).mean()), "volume_ratio": (pv / rv) if abs(rv) > 1e-12 else None,
       "zero_weight_vertices": zero_w}
print("@@JSON@@" + json.dumps(out))
'''

# Aim bones along WORLD-space directions (no knowledge of bone axes needed). P: armature, aim{bone:[dx,dy,dz]}, reset(bool).
# Bones are processed parent-first; each is rotated about its head so its LIMB direction (head -> child head) points at the target.
AIM_POSE = r'''
import bpy, json, mathutils
a = bpy.data.objects[P["armature"]]
if P.get("reset", True):
    for pb in a.pose.bones:
        pb.rotation_mode = "XYZ"; pb.rotation_euler = (0, 0, 0); pb.location = (0, 0, 0); pb.scale = (1, 1, 1)
bpy.context.view_layer.update()
missing = [b for b in P["aim"] if b not in a.pose.bones]
if missing:
    raise RuntimeError("unknown bones: %s" % missing)
depth = {}
for b in a.data.bones:
    d = 0; c = b
    while c.parent:
        c = c.parent; d += 1
    depth[b.name] = d
errs = {}; refs = {}
for name in sorted(P["aim"], key=lambda n: depth[n]):
    pb = a.pose.bones[name]; mw = a.matrix_world
    head = mw @ pb.head; tail = mw @ pb.tail
    # Limb direction = head -> head of the child that best continues the bone; leaf bones use head -> tail.
    # (Bone tails are NOT reliable limb directions: e.g. a rig's UpLeg bone can point sideways.)
    ref = None
    if pb.children:
        own = (tail - head).normalized(); best = 9.0
        for k in pb.children:
            ang = ((mw @ k.head) - head).normalized().angle(own)
            if ang < best:
                best = ang; ref = k
    refs[name] = ref.name if ref else "(tail)"
    end = (mw @ ref.head) if ref else tail
    cur = (end - head).normalized(); tgt = mathutils.Vector(P["aim"][name]).normalized()
    R = cur.rotation_difference(tgt).to_matrix().to_4x4()
    M = mw @ pb.matrix
    pb.matrix = mw.inverted() @ (mathutils.Matrix.Translation(head) @ R @ mathutils.Matrix.Translation(-head) @ M)
    bpy.context.view_layer.update()
    h2 = a.matrix_world @ pb.head
    e2 = (a.matrix_world @ ref.head) if ref else (a.matrix_world @ pb.tail)
    errs[name] = round(float((e2 - h2).normalized().angle(tgt)) * 57.29578, 2)
print("@@JSON@@" + json.dumps({"aimed": list(P["aim"]), "residual_deg": errs, "limb_ref": refs}))
'''

# Render the scene through its OWN camera and lights (shot rendering), at the given frames.
# P: outdir, prefix, size [w, h], mode (beauty|mask|normal), engine, frames[int], objects[] (mask: only these are white,
# everything else hidden), hide[] (objects hidden for this render, e.g. actors for a clean plate).
RENDER_SCENE = r'''
import bpy, os, json
sc = bpy.context.scene; vl = bpy.context.view_layer; r = sc.render
if sc.camera is None:
    raise RuntimeError("scene has no active camera")
os.makedirs(P["outdir"], exist_ok=True)
mode = P["mode"]
saved = dict(engine=r.engine, rx=r.resolution_x, ry=r.resolution_y, pct=r.resolution_percentage, fp=r.filepath,
             ff=r.image_settings.file_format, cm=r.image_settings.color_mode, ft=r.film_transparent,
             mo=vl.material_override, frame=sc.frame_current)
hid = {}
for n in P.get("hide", []):
    o = bpy.data.objects[n]; hid[n] = o.hide_render; o.hide_render = True
override = None
if mode in ("mask", "normal"):
    if mode == "mask":
        keep = set(P["objects"])
        for o in sc.objects:
            if o.type in ("MESH", "LIGHT") and o.name not in keep and o.name not in hid:
                hid[o.name] = o.hide_render; o.hide_render = True
    override = bpy.data.materials.new("_mcp_override"); override.use_nodes = True
    nt = override.node_tree; nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial"); em = nt.nodes.new("ShaderNodeEmission")
    if mode == "mask":
        em.inputs["Color"].default_value = (1, 1, 1, 1); nt.links.new(em.outputs[0], out.inputs[0])
        r.film_transparent = True; r.image_settings.color_mode = "RGBA"
    else:
        g = nt.nodes.new("ShaderNodeNewGeometry"); m = nt.nodes.new("ShaderNodeVectorMath"); m.operation = "MULTIPLY_ADD"
        m.inputs[1].default_value = (0.5, 0.5, 0.5); m.inputs[2].default_value = (0.5, 0.5, 0.5)
        nt.links.new(g.outputs["Normal"], m.inputs[0]); nt.links.new(m.outputs[0], em.inputs["Color"])
        nt.links.new(em.outputs[0], out.inputs[0])
    vl.material_override = override
r.engine = P["engine"]; r.resolution_x, r.resolution_y = P["size"]; r.resolution_percentage = 100
r.image_settings.file_format = "PNG"
paths = []
try:
    for f in P["frames"]:
        sc.frame_set(int(f))
        p = os.path.join(P["outdir"], "%s%04d.png" % (P["prefix"], int(f)))
        r.filepath = p
        bpy.ops.render.render(write_still=True)
        paths.append(p)
finally:
    for n, v in hid.items():
        bpy.data.objects[n].hide_render = v
    if override: bpy.data.materials.remove(override)
    r.engine = saved["engine"]; r.resolution_x = saved["rx"]; r.resolution_y = saved["ry"]; r.resolution_percentage = saved["pct"]
    r.filepath = saved["fp"]; r.image_settings.file_format = saved["ff"]; r.image_settings.color_mode = saved["cm"]
    r.film_transparent = saved["ft"]; vl.material_override = saved["mo"]; sc.frame_set(saved["frame"])
print("@@JSON@@" + json.dumps(paths))
'''

# Animation helpers. P (KEY_POSE): armature, frame, object(bool: also key the armature object's location/rotation).
KEY_POSE = r'''
import bpy, json
a = bpy.data.objects[P["armature"]]; f = int(P["frame"])
for pb in a.pose.bones:
    pb.keyframe_insert("rotation_euler", frame=f); pb.keyframe_insert("location", frame=f)
if P.get("object", True):
    a.keyframe_insert("location", frame=f); a.keyframe_insert("rotation_euler", frame=f)
print("@@JSON@@" + json.dumps({"keyed": f, "bones": len(a.pose.bones)}))
'''

# P: start, end, fps (omit a key to leave it), frame (go to this frame; evaluates existing animation).
TIMELINE = r'''
import bpy, json
sc = bpy.context.scene
if "start" in P: sc.frame_start = int(P["start"])
if "end" in P: sc.frame_end = int(P["end"])
if "fps" in P: sc.render.fps = int(P["fps"])
if "frame" in P: sc.frame_set(int(P["frame"]))
print("@@JSON@@" + json.dumps({"start": sc.frame_start, "end": sc.frame_end, "fps": sc.render.fps, "frame": sc.frame_current}))
'''
