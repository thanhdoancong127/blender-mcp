"""Python source executed inside Blender (via the addon's execute_code)."""

# Renders `n` evenly spaced turntable views of all visible mesh objects to `outdir`.
# Result variable `result` is the list of written PNG paths (addon returns it).
TURNTABLE = r'''
import bpy, math, os, mathutils
outdir = {outdir!r}; n = {n}; size = {size}; engine = {engine!r}
os.makedirs(outdir, exist_ok=True)
sc = bpy.context.scene
meshes = [o for o in sc.objects if o.type == "MESH" and o.visible_get()]
if not meshes:
    raise RuntimeError("no visible mesh objects to render")
pts = [o.matrix_world @ mathutils.Vector(c) for o in meshes for c in o.bound_box]
lo = mathutils.Vector(map(min, zip(*pts))); hi = mathutils.Vector(map(max, zip(*pts)))
center = (lo + hi) / 2; radius = max((hi - lo).length / 2, 1e-3)
old = (sc.camera, sc.render.engine, sc.render.resolution_x, sc.render.resolution_y,
       sc.render.filepath, sc.render.image_settings.file_format)
cam_data = bpy.data.cameras.new("_tt_cam"); cam = bpy.data.objects.new("_tt_cam", cam_data)
sc.collection.objects.link(cam); sc.camera = cam
cam_data.lens = 50
dist = radius / math.sin(cam_data.angle / 2) * 1.15
sc.render.engine = engine
sc.render.resolution_x = sc.render.resolution_y = size
sc.render.image_settings.file_format = "PNG"
paths = []
try:
    for i in range(n):
        a = 2 * math.pi * i / n
        # asset faces -Y (Blender front): i=0 is the front view
        cam.location = center + mathutils.Vector((math.sin(a) * dist, -math.cos(a) * dist, radius * 0.15))
        direction = center - cam.location
        cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
        p = os.path.join(outdir, "view_%02d.png" % i)
        sc.render.filepath = p
        bpy.ops.render.render(write_still=True)
        paths.append(p)
finally:
    sc.collection.objects.unlink(cam); bpy.data.objects.remove(cam)
    bpy.data.cameras.remove(cam_data)
    (sc.camera, sc.render.engine, sc.render.resolution_x, sc.render.resolution_y,
     sc.render.filepath, sc.render.image_settings.file_format) = old
result = paths
'''
