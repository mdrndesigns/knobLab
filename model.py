"""
KNOBLAB - parametric knobs for captive nuts and bolt heads, M4-M12.

Coordinate convention (print orientation, no supports):
    z = 0      bed. This is the grip face of the knob.
    z = H      pocket opening. In use this face sits against the work.
The stack list is ordered opening-first: stack[0] is the item nearest
the work, the last item is deepest in the knob.

All dimensions in millimetres. Defaults assume a 0.4 mm nozzle at
0.2 mm layer height.
"""

import math

import cadquery as cq

import fasteners as F

DEFAULTS = {
    # --- fastener ---------------------------------------------------
    "size": 8,                      # thread, M4 M5 M6 M8 M10 M12
    "stack": "flange_din,hex_iso",  # opening-first, comma separated
    "material": "petg",
    "clear_af": 0.30,               # total extra across flats
    "clear_depth": 0.30,            # extra depth per item
    "corner_r": 0.4,                # hex pocket corner radius, 0 = sharp
    "lead_in": 0.8,                 # 45 deg chamfer at the opening
    "extra_depth": 0.0,             # spare depth under the stack
    "through": True,                # bolt passes out through the grip face
    "stud_extra": 0.0,              # blind only: bore past the stack
    # --- body ---------------------------------------------------------
    "family": "lobed",              # cylinder | lobed | wing | metaball
    "diameter": 40.0,               # outer envelope
    "cap": 4.0,                     # solid plastic between pocket and grip face
    "edge_chamfer": 1.0,            # top and bottom outer edges
    # --- cylinder -----------------------------------------------------
    "flutes": 12,                   # 0 = plain
    "flute_r": 2.0,
    "flute_depth": 1.0,
    # --- lobed --------------------------------------------------------
    "lobes": 5,
    "lobe_depth": 5.0,              # valley below the lobe crest
    "lobe_sharp": 1.0,              # 0.5 soft .. 3 pointed
    # --- wing ---------------------------------------------------------
    "arms": 2,
    "arm_w": 12.0,
    "hub": 0.0,                     # 0 = auto from pocket + wall
    # --- metaball -----------------------------------------------------
    "blobs": 7,
    "blob_r": 9.0,
    "blob_k": 6.0,                  # smooth-union radius
    "blob_jitter": 0.3,             # 0 = perfect ring
    "seed": 1,
    "voxel": 0.35,                  # preview; export uses voxel_export
    "voxel_export": 0.2,
}

STR_KEYS = ("stack", "material", "family")
INT_KEYS = ("size", "flutes", "lobes", "arms", "blobs", "seed")
FAMILIES = ("cylinder", "lobed", "wing", "metaball")


# ---------------------------------------------------------------------
# parameters
# ---------------------------------------------------------------------

def merge_params(raw):
    """Coerce incoming strings into typed params, filling gaps from DEFAULTS."""
    p = dict(DEFAULTS)
    for k, v in raw.items():
        if k not in p:
            continue
        if k in STR_KEYS:
            p[k] = str(v)
        elif isinstance(p[k], bool):
            p[k] = str(v).lower() in ("1", "true", "yes", "on")
        elif k in INT_KEYS:
            p[k] = int(float(v))
        else:
            p[k] = float(v)
    return p


def parse_stack(p):
    ids = [s.strip() for s in str(p["stack"]).split(",") if s.strip()]
    return [i for i in ids if i in F.ITEMS]


# ---------------------------------------------------------------------
# pocket spec - shared by the B-rep and the SDF builders
# ---------------------------------------------------------------------

def pocket_spec(p):
    """
    Returns dict:
        items     list of per-item dicts with z ranges (print frame)
        prims     list of cutting primitives: hex / cyl / cone
        depth     total pocket depth below the opening
        r_max     widest radius the pocket reaches
        s_max     widest across-flats in the stack
        H         total knob height
        bore      bore diameter
    """
    size = p["size"]
    ids = parse_stack(p)
    caf, cd = p["clear_af"], p["clear_depth"]

    items, prims = [], []
    depth = 0.0
    r_max = 0.0
    s_max = 0.0
    for idx, iid in enumerate(ids):
        d = F.item_dims(iid, size)
        s_p = d["s"] + caf                      # pocket across flats
        r_in = s_p / 2.0                        # inscribed radius
        r_c = F.across_corners(s_p) / 2.0       # circumscribed radius
        h_p = d["h"] + cd
        z_top = -depth                          # relative to opening (z=H)
        z_bot = z_top - h_p
        item = {**d, "s_pocket": s_p, "h_pocket": h_p,
                "rel_top": z_top, "rel_bot": z_bot}
        prims.append({"type": "hex", "r_in": r_in, "r_corner": p["corner_r"],
                      "rel_top": z_top, "rel_bot": z_bot})
        r_item = r_c
        if d["kind"] == "flange":
            r_fl = (d["dc"] + caf) / 2.0
            c_p = d["c"] + cd
            prims.append({"type": "cyl", "r": r_fl,
                          "rel_top": z_top, "rel_bot": z_top - c_p})
            item["r_flange"] = r_fl
            r_item = max(r_item, r_fl)
        items.append(item)
        depth += h_p
        r_max = max(r_max, r_item)
        s_max = max(s_max, d["s"])

    depth += p["extra_depth"]
    H = p["cap"] + depth

    # lead-in at the opening: 45 deg cone on the first item's entry radius
    if items and p["lead_in"] > 0:
        first = items[0]
        r_entry = first.get("r_flange", first["s_pocket"] / 2.0)
        prims.append({"type": "cone", "r_bot": r_entry,
                      "r_top": r_entry + p["lead_in"],
                      "rel_top": 0.0, "rel_bot": -p["lead_in"]})

    bore = F.BORE[size]
    if p["through"]:
        prims.append({"type": "cyl", "r": bore / 2.0,
                      "rel_top": 0.0, "rel_bot": -H})
    elif p["stud_extra"] > 0:
        prims.append({"type": "cyl", "r": bore / 2.0,
                      "rel_top": 0.0, "rel_bot": -(depth + p["stud_extra"])})

    return {"items": items, "prims": prims, "depth": depth, "r_max": r_max,
            "s_max": s_max, "H": H, "bore": bore, "ids": ids}


def body_min_radius(p, spec):
    """Smallest radial extent of plastic around the axis, per family."""
    R = p["diameter"] / 2.0
    fam = p["family"]
    if fam == "cylinder":
        return R - (p["flute_depth"] if p["flutes"] > 0 else 0.0)
    if fam == "lobed":
        return R - p["lobe_depth"]
    if fam == "wing":
        return hub_radius(p, spec)
    if fam == "metaball":
        return R - p["blob_r"]        # core radius, blobs sit on the rim
    return R


def hub_radius(p, spec):
    if p["hub"] > 0:
        return p["hub"] / 2.0
    return spec["r_max"] + F.wall_min(spec["s_max"])


def validate(p):
    errs = []
    if p["size"] not in F.SIZES:
        errs.append("Size must be M4, M5, M6, M8, M10 or M12.")
        return errs
    if p["family"] not in FAMILIES:
        errs.append("Unknown family.")
        return errs
    spec = pocket_spec(p)
    if not spec["items"]:
        errs.append("Stack is empty - add at least one nut or head.")
        return errs
    kinds = [i["kind"] for i in spec["items"]]
    if "bolt" in kinds and kinds.index("bolt") != len(kinds) - 1:
        errs.append("A bolt head must be the last (deepest) item in the stack.")
    if kinds.count("bolt") > 1:
        errs.append("Only one bolt head per knob.")

    wmin = F.wall_min(spec["s_max"])
    r_body = body_min_radius(p, spec)
    if r_body - spec["r_max"] < wmin - 1e-6:
        errs.append(f"Wall under {wmin:.1f} mm at the pocket "
                    f"({r_body - spec['r_max']:.1f} mm). Raise diameter or "
                    f"lower lobe / flute depth.")
    if not p["through"] and p["cap"] - p["stud_extra"] < 1.2:
        errs.append("Blind cap: cap minus stud extra must leave 1.2 mm of plastic.")
    if p["cap"] < 1.2:
        errs.append("Cap under 1.2 mm (6 layers).")
    if p["family"] == "lobed" and p["lobes"] < 3:
        errs.append("Lobed knob needs at least 3 lobes.")
    if p["family"] == "wing" and p["arms"] < 2:
        errs.append("Wing knob needs at least 2 arms.")
    if p["family"] == "wing" and p["arm_w"] / 2.0 > hub_radius(p, spec):
        errs.append("Arm width exceeds the hub.")
    if p["family"] == "metaball" and p["blobs"] < 1:
        errs.append("Metaball knob needs at least 1 blob.")
    if p["corner_r"] > 0 and p["clear_af"] / 2.0 < 0.1547 * p["corner_r"]:
        errs.append("Corner radius eats the across-flats clearance. "
                    "Lower corner radius or raise clearance.")
    if p["lead_in"] > p["cap"] + spec["depth"] - 1:
        errs.append("Lead-in deeper than the knob.")
    return errs


# ---------------------------------------------------------------------
# B-rep bodies (cylinder, lobed, wing)
# ---------------------------------------------------------------------

def _chamfer_ends(solid, c, warnings):
    if c <= 0:
        return solid
    try:
        return solid.edges(">Z or <Z").chamfer(c)
    except Exception:
        warnings.append("Edge chamfer skipped - kernel could not chamfer this outline.")
        return solid


def body_cylinder(p, H, warnings):
    R = p["diameter"] / 2.0
    solid = cq.Workplane("XY").circle(R).extrude(H)
    solid = _chamfer_ends(solid, p["edge_chamfer"], warnings)
    n = int(p["flutes"])
    if n > 0 and p["flute_depth"] > 0:
        fr = p["flute_r"]
        rc = R + fr - p["flute_depth"]
        for i in range(n):
            a = 2 * math.pi * i / n
            cutter = (cq.Workplane("XY")
                      .center(rc * math.cos(a), rc * math.sin(a))
                      .circle(fr).extrude(H + 2).translate((0, 0, -1)))
            solid = solid.cut(cutter)
    return solid


def lobed_outline(p):
    """Polar outline r(theta) sampled as points for a closed spline."""
    R = p["diameter"] / 2.0
    Rv = R - p["lobe_depth"]
    n = int(p["lobes"])
    k = max(0.3, p["lobe_sharp"])
    steps = max(96, 32 * n)
    pts = []
    for i in range(steps):
        t = 2 * math.pi * i / steps
        w = ((1 + math.cos(n * t)) / 2.0) ** k
        r = Rv + (R - Rv) * w
        pts.append((r * math.cos(t), r * math.sin(t)))
    return pts


def body_lobed(p, H, warnings):
    pts = lobed_outline(p)
    solid = (cq.Workplane("XY")
             .spline(pts, periodic=True).close()
             .extrude(H))
    solid = _chamfer_ends(solid, p["edge_chamfer"], warnings)
    return solid


def body_wing(p, H, warnings, spec):
    R = p["diameter"] / 2.0
    rh = hub_radius(p, spec)
    w = p["arm_w"]
    n = int(p["arms"])
    solid = cq.Workplane("XY").circle(rh).extrude(H)
    L = R - w / 2.0                       # arm length to the tip-circle centre
    for i in range(n):
        a = 360.0 * i / n
        arm = (cq.Workplane("XY").transformed(rotate=(0, 0, a))
               .center(L / 2.0, 0).rect(L, w).extrude(H))
        tip = (cq.Workplane("XY").transformed(rotate=(0, 0, a))
               .center(L, 0).circle(w / 2.0).extrude(H))
        solid = solid.union(arm).union(tip)
    solid = _chamfer_ends(solid, p["edge_chamfer"], warnings)
    return solid


def cutters(spec):
    """One CadQuery solid per pocket primitive, in the print frame."""
    H = spec["H"]
    out = []
    for pr in spec["prims"]:
        z0 = H + pr["rel_bot"]
        z1 = H + pr["rel_top"]
        h = z1 - z0
        if pr["type"] == "hex":
            e = 2 * pr["r_in"] / math.cos(math.radians(30))
            c = (cq.Workplane("XY").workplane(offset=z0)
                 .polygon(6, e).extrude(h + 1.0))      # +1 overshoots the opening
            if pr["r_corner"] > 0:
                c = c.edges("|Z").fillet(pr["r_corner"])
            out.append(c)
        elif pr["type"] == "cyl":
            over_top = 1.0 if abs(pr["rel_top"]) < 1e-9 else 0.0
            over_bot = 1.0 if (z0 <= 1e-9) else 0.0
            c = (cq.Workplane("XY").workplane(offset=z0 - over_bot)
                 .circle(pr["r"]).extrude(h + over_top + over_bot))
            out.append(c)
        elif pr["type"] == "cone":
            cone = cq.Solid.makeCone(pr["r_bot"], pr["r_top"] + 0.5, h + 0.5,
                                     cq.Vector(0, 0, z0), cq.Vector(0, 0, 1))
            out.append(cq.Workplane("XY").add(cone))
    return out


def build_brep(p):
    """Returns (solid, spec, warnings) for the three B-rep families."""
    warnings = []
    spec = pocket_spec(p)
    H = spec["H"]
    fam = p["family"]
    if fam == "cylinder":
        solid = body_cylinder(p, H, warnings)
    elif fam == "lobed":
        solid = body_lobed(p, H, warnings)
    elif fam == "wing":
        solid = body_wing(p, H, warnings, spec)
    else:
        raise ValueError("not a B-rep family")
    for c in cutters(spec):
        solid = solid.cut(c)
    return solid, spec, warnings


# ---------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------

def build(p, export=False):
    """
    Returns (result, spec, warnings).
    result is a cq.Workplane for B-rep families, or a generative.Mesh
    for the metaball family.
    """
    if p["family"] == "metaball":
        import generative as G
        spec = pocket_spec(p)
        voxel = p["voxel_export"] if export else p["voxel"]
        mesh, warnings = G.build_metaball(p, spec, voxel)
        return mesh, spec, warnings
    return build_brep(p)


def derived(p, spec):
    """Numbers worth showing that fall out of the parameters."""
    wmin = F.wall_min(spec["s_max"])
    r_body = body_min_radius(p, spec)
    return {
        "H": round(spec["H"], 2),
        "pocket_depth": round(spec["depth"], 2),
        "wall": round(r_body - spec["r_max"], 2),
        "wall_min": wmin,
        "bore": spec["bore"] if (p["through"] or p["stud_extra"] > 0) else 0,
        "stack": [f'{i["label"]} {i["s"]:g}AF x {i["h"]:g}' for i in spec["items"]],
        "r_pocket": round(spec["r_max"], 2),
    }
