"""
KNOBLAB generative family: metaball shell carved by the exact pocket.

Signed-distance field sampled on a uniform grid, surfaced with marching
cubes. Dependencies: numpy, scikit-image. The pocket primitives come from
model.pocket_spec, so the captive geometry is identical to the B-rep
families - only the outer shell is implicit.

Output is a mesh (STL / 3MF). There is no STEP for this family: an
implicit surface has no B-rep.
"""

import io
import math
import struct
import zipfile

import numpy as np

try:
    from skimage.measure import marching_cubes as _mc
except ImportError:                       # pragma: no cover
    _mc = None


# ---------------------------------------------------------------------
# mesh container
# ---------------------------------------------------------------------

class Mesh:
    def __init__(self, verts, faces):
        self.verts = np.asarray(verts, dtype=np.float64)
        self.faces = np.asarray(faces, dtype=np.int64)
        self._fix_winding()

    def _fix_winding(self):
        if self.signed_volume() < 0:
            self.faces = self.faces[:, ::-1]

    def signed_volume(self):
        v = self.verts
        f = self.faces
        a, b, c = v[f[:, 0]], v[f[:, 1]], v[f[:, 2]]
        return float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6.0)

    def volume(self):
        return abs(self.signed_volume())

    def bbox(self):
        lo, hi = self.verts.min(0), self.verts.max(0)
        return hi - lo

    def is_watertight(self):
        f = self.faces
        e = np.concatenate([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]])
        e.sort(axis=1)
        _, counts = np.unique(e, axis=0, return_counts=True)
        return bool((counts == 2).all())

    # -- binary STL --------------------------------------------------
    def to_stl_bytes(self):
        v = self.verts.astype(np.float32)
        f = self.faces
        tri = v[f]                                           # (n,3,3)
        n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        n /= (np.linalg.norm(n, axis=1, keepdims=True) + 1e-12)
        rec = np.zeros(len(f), dtype=[("n", "<f4", 3), ("v", "<f4", (3, 3)),
                                      ("a", "<u2")])
        rec["n"] = n
        rec["v"] = tri
        header = b"KNOBLAB metaball" + b" " * 64
        return header + struct.pack("<I", len(f)) + rec.tobytes()

    # -- 3MF (core spec, millimetres) --------------------------------
    def to_3mf_bytes(self, name="knob"):
        v = self.verts
        f = self.faces
        parts = ['<?xml version="1.0" encoding="UTF-8"?>',
                 '<model unit="millimeter" xml:lang="en-US" '
                 'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">',
                 '<resources>',
                 f'<object id="1" name="{name}" type="model"><mesh><vertices>']
        parts.extend(f'<vertex x="{x:.4f}" y="{y:.4f}" z="{z:.4f}"/>'
                     for x, y, z in v)
        parts.append('</vertices><triangles>')
        parts.extend(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in f)
        parts.append('</triangles></mesh></object></resources>'
                     '<build><item objectid="1"/></build></model>')
        model_xml = "\n".join(parts)
        ctypes = ('<?xml version="1.0" encoding="UTF-8"?>'
                  '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                  '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                  '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>'
                  '</Types>')
        rels = ('<?xml version="1.0" encoding="UTF-8"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Target="/3D/3dmodel.model" Id="rel0" '
                'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>'
                '</Relationships>')
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("[Content_Types].xml", ctypes)
            z.writestr("_rels/.rels", rels)
            z.writestr("3D/3dmodel.model", model_xml)
        return buf.getvalue()


# ---------------------------------------------------------------------
# SDF primitives (numpy, broadcast over grids)
# ---------------------------------------------------------------------

def sd_sphere(X, Y, Z, cx, cy, cz, r):
    return np.sqrt((X - cx) ** 2 + (Y - cy) ** 2 + (Z - cz) ** 2) - r


def sd_cylinder(X, Y, Z, r, z0, z1):
    """Capped cylinder on the z axis between z0 and z1."""
    dr = np.sqrt(X * X + Y * Y) - r
    dz = np.maximum(z0 - Z, Z - z1)
    outside = np.sqrt(np.maximum(dr, 0) ** 2 + np.maximum(dz, 0) ** 2)
    inside = np.minimum(np.maximum(dr, dz), 0)
    return outside + inside


def sd_hex_prism(X, Y, Z, r_in, z0, z1, r_corner=0.0):
    """Hexagonal prism, vertex on +X (matches CadQuery polygon()).
    r_in = inscribed radius. Corners rounded by r_corner."""
    # 2D hexagon (Inigo Quilez): flats at +-y, so a vertex sits on +x,
    # which is where CadQuery's polygon(6, d) puts its first vertex.
    kx, ky, kz = -0.8660254, 0.5, 0.5773503
    px = np.abs(X)
    py = np.abs(Y)
    r = r_in - r_corner
    dot = kx * px + ky * py
    m = np.minimum(dot, 0.0)
    px = px - 2.0 * m * kx
    py = py - 2.0 * m * ky
    cl = np.clip(px, -kz * r, kz * r)
    d2 = np.sqrt((px - cl) ** 2 + (py - r) ** 2) * np.sign(py - r) - r_corner
    dz = np.maximum(z0 - Z, Z - z1)
    outside = np.sqrt(np.maximum(d2, 0) ** 2 + np.maximum(dz, 0) ** 2)
    inside = np.minimum(np.maximum(d2, dz), 0)
    return outside + inside


def sd_cone_frustum(X, Y, Z, r_bot, r_top, z0, z1):
    """Frustum, radius r_bot at z0 growing to r_top at z1 (a countersink)."""
    t = np.clip((Z - z0) / max(z1 - z0, 1e-9), 0, 1)
    r_at = r_bot + (r_top - r_bot) * t
    dr = np.sqrt(X * X + Y * Y) - r_at
    dz = np.maximum(z0 - Z, Z - z1)
    # approximate (not exact Euclidean on the slant) - fine for a cutter
    return np.maximum(dr * math.cos(math.atan2(r_top - r_bot, z1 - z0)), dz)


def smooth_union(a, b, k):
    """Polynomial smooth minimum (Quilez)."""
    if k <= 0:
        return np.minimum(a, b)
    h = np.clip(0.5 + 0.5 * (b - a) / k, 0.0, 1.0)
    return b + (a - b) * h - k * h * (1.0 - h)


# ---------------------------------------------------------------------
# metaball knob
# ---------------------------------------------------------------------

def blob_centres(p, R_core, H):
    """Blobs on a ring at the core rim, jittered deterministically."""
    n = int(p["blobs"])
    rng = np.random.default_rng(int(p["seed"]))
    rb = p["blob_r"]
    ring = R_core                         # centre on the core surface
    out = []
    for i in range(n):
        a = 2 * math.pi * i / n
        j = p["blob_jitter"]
        a += rng.uniform(-0.5, 0.5) * j * (2 * math.pi / n)
        rr = ring + rng.uniform(-0.3, 0.3) * j * rb
        zz = H / 2.0 + rng.uniform(-0.5, 0.5) * j * (H - rb)
        zz = min(max(zz, rb * 0.6), H - rb * 0.6)
        out.append((rr * math.cos(a), rr * math.sin(a), zz))
    return out


def shell_sdf(X, Y, Z, p, spec):
    R = p["diameter"] / 2.0
    rb = p["blob_r"]
    R_core = R - rb
    H = spec["H"]
    d = sd_cylinder(X, Y, Z, R_core, 0.0, H)
    for cx, cy, cz in blob_centres(p, R_core, H):
        d = smooth_union(d, sd_sphere(X, Y, Z, cx, cy, cz, rb), p["blob_k"])
    # flat bed face and flat opening face: hard intersect with the slab
    slab = np.maximum(-Z, Z - H)
    d = np.maximum(d, slab)
    # optional 45 deg chamfer on the bed edge is not needed: the slab clip
    # already gives a printable flat base.
    return d


def pocket_sdf(X, Y, Z, spec):
    H = spec["H"]
    d = None
    for pr in spec["prims"]:
        z0 = H + pr["rel_bot"]
        z1 = H + pr["rel_top"]
        if abs(pr["rel_top"]) < 1e-9:
            z1 = H + 1.0                   # overshoot the opening
        if pr["type"] == "hex":
            s = sd_hex_prism(X, Y, Z, pr["r_in"], z0, z1, pr["r_corner"])
        elif pr["type"] == "cyl":
            if z0 <= 1e-9:
                z0 = -1.0                  # through bore overshoots the bed
            s = sd_cylinder(X, Y, Z, pr["r"], z0, z1)
        elif pr["type"] == "cone":
            s = sd_cone_frustum(X, Y, Z, pr["r_bot"], pr["r_top"] + 0.5,
                                z0, z1 + 0.5)
        else:
            continue
        d = s if d is None else np.minimum(d, s)
    return d


def build_metaball(p, spec, voxel):
    """Returns (Mesh, warnings)."""
    warnings = []
    if _mc is None:
        raise RuntimeError("scikit-image is required for the metaball family: "
                           "pip install scikit-image")
    R = p["diameter"] / 2.0
    H = spec["H"]
    pad = 2.0 * voxel + 1.0
    ext = R + p["blob_r"] * 0.5 + pad   # blobs centred on the rim reach R
    # Grid nodes are offset by an odd fraction of a voxel so the flat
    # faces (z = 0, z = H, pocket floors) never pass exactly through a
    # node. An exact zero at a node makes marching cubes emit zero-area
    # triangles, which slicers read as open edges.
    off = 0.3713 * voxel
    xs = np.arange(-ext + off, ext + voxel, voxel, dtype=np.float32)
    zs = np.arange(-pad + off, H + pad + voxel, voxel, dtype=np.float32)
    X, Y, Z = np.meshgrid(xs, xs, zs, indexing="ij")

    d = shell_sdf(X, Y, Z, p, spec)
    pk = pocket_sdf(X, Y, Z, spec)
    if pk is not None:
        d = np.maximum(d, -pk)            # hard subtraction

    # Keep every node a clear 1 um off the surface: a node sitting on the
    # isosurface makes marching cubes emit zero-area triangles.
    eps = np.float32(1e-3)
    d = np.where(np.abs(d) < eps, np.where(d < 0, -eps, eps), d)

    verts, faces, _, _ = _mc(d, level=0.0, spacing=(voxel, voxel, voxel))
    verts = verts + np.array([xs[0], xs[0], zs[0]], dtype=np.float32)
    mesh = Mesh(verts, faces)
    if not mesh.is_watertight():
        warnings.append("Metaball mesh not watertight - raise voxel resolution.")
    nvox = X.size
    if nvox > 40_000_000:
        warnings.append(f"Large grid ({nvox/1e6:.0f}M voxels) - export is slow.")
    return mesh, warnings
