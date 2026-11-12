# KNOBLAB

Parametric knobs for captive nuts and hex-head bolts, M4–M12. Sliders and a
stack editor in the browser, CadQuery on the server. Sister of BOXLAB.

## Run

    cd ~/cad/knoblab
    python3 app.py

Opens http://localhost:8766. Ctrl-C to stop.
Port clash: `python3 app.py --port 8767`

## Dependencies

    pip install cadquery numpy scikit-image

CadQuery drives the cylinder, lobed and wing families. numpy + scikit-image
drive the metaball family (signed-distance field + marching cubes). The
app starts without scikit-image; only the metaball family then errors.

## Files

    fasteners.py   dimension tables (ISO 4032, DIN 934, ISO 4035, DIN 439,
                   DIN 6923, ISO 4161, DIN 985, ISO 4017, DIN 933), bores,
                   material clearances, default knob diameters
    model.py       parameters, validation, pocket spec, B-rep families
    generative.py  metaball family: SDF, marching cubes, STL/3MF writers
    app.py         local server, stdlib only
    index.html     UI + three.js viewport

## The stack

The pocket is built from an ordered list of items, opening first:
item 1 sits against the work, the last item is deepest in the knob.
Each item is cut at its own across-flats and height plus the material
clearance. Flange nuts get a second, round cut for the flange disc.
A bolt head must be the last item.

Your strut-channel reference is the default: `flange_din, hex_iso`.

ISO and DIN differ at M10 (16 vs 17 AF) and M12 (18 vs 19 AF). Measure
the nut with a spanner and pick the matching entry; the wrong one is
either loose by a millimetre or will not go in.

## Why the old knobs failed, and what the tool enforces

- Wall around the pocket ≥ 0.25 × across-flats, never under 2.4 mm.
  The readout shows wall / minimum; the build refuses below it.
- Hex pocket corners rounded (0.4 mm default). Sharp internal corners
  are where PLA cracks started.
- Lead-in chamfer at the opening, so the nut presses in square.
- Print orientation: grip face on the bed, pocket opening up. Layers run
  around the hex, which is the direction the torque loads them.
  No supports.
- Material presets set the pocket clearance: PETG 0.30 across flats,
  ABS-GF / ASA / PA-CF 0.25, PLA 0.20. Depth clearance is per item.

## Bore

Through: the clearance bore (ISO 273 medium + 0.2 mm) runs out of the
grip face, for a rod that passes through.
Blind: the bore stops `stud past stack` mm beyond the pocket; at least
1.2 mm of cap remains.

## Families

    cylinder   plain or fluted
    lobed      3–10 lobes, depth and sharpness; polar outline, one spline
    wing       2–4 arms on a hub; hub Ø auto = pocket + minimum wall
    metaball   core + blobs smooth-unioned, carved by the exact pocket.
               Mesh only (STL + 3MF); an implicit surface has no STEP.
               Preview voxel 0.35 mm, export 0.2 mm. Export of a Ø57
               knob at 0.2 mm takes ~10 s and writes a ~20 MB STL.

Changing the size resets the diameter and the family proportions.
Slide anything afterwards.

## Export

The Export button downloads a zip:

    <name>.step / .stl / .3mf   (metaball: .stl / .3mf)
    <name>_parameters.json      the exact slider state
    <name>_spec.json            pocket depth, wall, bore, stack, print note
    <name>_model.py             standalone script that rebuilds it

Run the script next to model.py, fasteners.py and generative.py.

## Changing the tool

Add a fastener: a new entry in `fasteners.ITEMS`, it appears in the
stack dropdown automatically.
Add a slider: add it to `DEFAULTS` in model.py, then a row to `CONTROLS`
in index.html.
Add a family: a `body_*` function in model.py, the name in `FAMILIES`,
a `grp-<name>` group in index.html.
# knobLab
