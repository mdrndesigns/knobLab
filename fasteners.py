"""
Fastener dimension tables for KNOBLAB. All values in millimetres.

Sources (checked 2026-10-21):
    ISO 4032   hex nut style 1          s = across flats, m = max height
    DIN 934    hex nut (legacy German)  M10 s=17, M12 s=19; lower m than ISO
    ISO 4035   thin (jam) nut           ISO across-flats
    DIN 439    thin (jam) nut           DIN across-flats, same m as ISO 4035
    DIN 6923   hex flange nut           dc = flange dia, c = flange thickness
    ISO 4161   hex flange nut           = DIN 6923 except M10 s=16
    DIN 985    nyloc nut                DIN across-flats
    ISO 4017   hex head screw           k = head height
    DIN 933    hex head screw           DIN across-flats, same k

The pocket uses s MAX (nominal) and m/k MAX, then adds the material
clearance. A nut at its minimum tolerance will sit a little looser; it
never binds.

Every entry is a dict keyed by nominal thread size (4, 5, 6, 8, 10, 12).
Fields:
    s     across flats
    h     height of the item (m for nuts, k for bolt heads)
    dc    flange outer diameter       (flange items only)
    c     flange thickness, min       (flange items only)
"""

import math

SIZES = [4, 5, 6, 8, 10, 12]
PITCH = {4: 0.7, 5: 0.8, 6: 1.0, 8: 1.25, 10: 1.5, 12: 1.75}

# across flats, ISO pattern vs legacy DIN pattern
_S_ISO = {4: 7, 5: 8, 6: 10, 8: 13, 10: 16, 12: 18}
_S_DIN = {4: 7, 5: 8, 6: 10, 8: 13, 10: 17, 12: 19}

ITEMS = {
    "hex_iso": {
        "label": "Hex nut ISO 4032",
        "kind": "hex",
        "s": _S_ISO,
        "h": {4: 3.2, 5: 4.7, 6: 5.2, 8: 6.8, 10: 8.4, 12: 10.8},
    },
    "hex_din": {
        "label": "Hex nut DIN 934",
        "kind": "hex",
        "s": _S_DIN,
        "h": {4: 3.2, 5: 4.0, 6: 5.0, 8: 6.5, 10: 8.0, 12: 10.0},
    },
    "thin_iso": {
        "label": "Thin nut ISO 4035",
        "kind": "hex",
        "s": _S_ISO,
        "h": {4: 2.2, 5: 2.7, 6: 3.2, 8: 4.0, 10: 5.0, 12: 6.0},
    },
    "thin_din": {
        "label": "Thin nut DIN 439",
        "kind": "hex",
        "s": _S_DIN,
        "h": {4: 2.2, 5: 2.7, 6: 3.2, 8: 4.0, 10: 5.0, 12: 6.0},
    },
    "nyloc_din": {
        "label": "Nyloc DIN 985",
        "kind": "hex",
        "s": _S_DIN,
        "h": {4: 5.0, 5: 5.0, 6: 6.0, 8: 8.0, 10: 10.0, 12: 12.0},
    },
    "flange_din": {
        "label": "Flange nut DIN 6923",
        "kind": "flange",
        "s": {4: 7, 5: 8, 6: 10, 8: 13, 10: 15, 12: 18},
        "h": {4: 4.65, 5: 5.0, 6: 6.0, 8: 8.0, 10: 10.0, 12: 12.0},
        "dc": {4: 10.0, 5: 11.8, 6: 14.2, 8: 17.9, 10: 21.8, 12: 26.0},
        "c": {4: 1.0, 5: 1.0, 6: 1.1, 8: 1.2, 10: 1.5, 12: 1.8},
    },
    "flange_iso": {
        "label": "Flange nut ISO 4161",
        "kind": "flange",
        "s": {4: 7, 5: 8, 6: 10, 8: 13, 10: 16, 12: 18},
        "h": {4: 4.65, 5: 5.0, 6: 6.0, 8: 8.0, 10: 10.0, 12: 12.0},
        "dc": {4: 10.0, 5: 11.8, 6: 14.2, 8: 17.9, 10: 21.8, 12: 26.0},
        "c": {4: 1.0, 5: 1.0, 6: 1.1, 8: 1.2, 10: 1.5, 12: 1.8},
    },
    "bolt_iso": {
        "label": "Hex head ISO 4017",
        "kind": "bolt",
        "s": _S_ISO,
        "h": {4: 2.8, 5: 3.5, 6: 4.0, 8: 5.3, 10: 6.4, 12: 7.5},
    },
    "bolt_din": {
        "label": "Hex head DIN 933",
        "kind": "bolt",
        "s": _S_DIN,
        "h": {4: 2.8, 5: 3.5, 6: 4.0, 8: 5.3, 10: 6.4, 12: 7.5},
    },
}

# Bore for the bolt shank to pass through: ISO 273 medium clearance hole
# plus 0.2 mm, because FDM bores print undersized.
BORE = {4: 4.7, 5: 5.7, 6: 6.8, 8: 9.2, 10: 11.2, 12: 13.7}

# Pocket clearances by material. af = total extra across flats (both
# sides), depth = extra pocket depth per item. PETG swells at the nozzle
# and needs more; glass-filled ABS and PA-CF are dimensionally tight.
MATERIALS = {
    "petg":   {"label": "PETG",     "af": 0.30, "depth": 0.30},
    "abs_gf": {"label": "ABS-GF",   "af": 0.25, "depth": 0.20},
    "asa":    {"label": "ASA",      "af": 0.25, "depth": 0.20},
    "pa_cf":  {"label": "PA-CF",    "af": 0.25, "depth": 0.20},
    "pla":    {"label": "PLA",      "af": 0.20, "depth": 0.20},
}

# Knob outer diameter defaults, from the RS/Elesa star-knob range
# (M6 Ø32, M8 Ø38-50, M10 Ø44-57) extended down to M4 and up to M12.
KNOB_DIA = {4: 22.0, 5: 26.0, 6: 32.0, 8: 40.0, 10: 50.0, 12: 57.0}


def across_corners(s):
    """Circumscribed diameter of a hexagon with across-flats s."""
    return s / math.cos(math.radians(30))


def item_dims(item_id, size):
    """Nominal dims of one stack item at a thread size."""
    it = ITEMS[item_id]
    d = {"id": item_id, "kind": it["kind"], "label": it["label"],
         "s": float(it["s"][size]), "h": float(it["h"][size])}
    if it["kind"] == "flange":
        d["dc"] = float(it["dc"][size])
        d["c"] = float(it["c"][size])
    return d


def wall_min(s_max):
    """Minimum plastic around the widest pocket radius, from the PLA failure.
    0.25 x across-flats, never under 2.4 mm (6 perimeters at 0.4 mm).
    M8 -> 3.25, M10 -> 4.0/4.25, M12 -> 4.5/4.75."""
    return max(2.4, round(0.25 * s_max, 2))
