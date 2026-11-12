#!/usr/bin/env python3
"""
KNOBLAB - local parametric knob front end.

    python3 app.py

Serves http://localhost:8766. Sliders and a stack editor in the browser,
CadQuery (B-rep families) or an SDF mesher (metaball) on the server. The
browser never computes geometry; it displays the mesh the server made,
so what you see is what exports.
"""

import argparse
import io
import json
import os
import tempfile
import threading
import webbrowser
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import cadquery as cq

import fasteners as F
import model as M

HERE = os.path.dirname(os.path.abspath(__file__))
KERNEL_LOCK = threading.Lock()   # OpenCascade is not reentrant


def export_bytes(obj, ext, **kw):
    """Export a CadQuery object to bytes via a temp file."""
    with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False) as fh:
        path = fh.name
    try:
        cq.exporters.export(obj, path, **kw)
        with open(path, "rb") as fh:
            return fh.read()
    finally:
        os.unlink(path)


def stats_for(result):
    if hasattr(result, "val"):                 # CadQuery
        shape = result.val()
        bb = shape.BoundingBox()
        return {"bbox": [round(bb.xlen, 2), round(bb.ylen, 2), round(bb.zlen, 2)],
                "volume": round(shape.Volume() / 1000.0, 2),
                "watertight": bool(shape.isValid()), "brep": True}
    bb = result.bbox()                         # generative.Mesh
    return {"bbox": [round(float(bb[0]), 2), round(float(bb[1]), 2), round(float(bb[2]), 2)],
            "volume": round(result.volume() / 1000.0, 2),
            "watertight": result.is_watertight(), "brep": False}


def preview_stl(result):
    if hasattr(result, "val"):
        return export_bytes(result, "stl", tolerance=0.02, angularTolerance=0.15)
    return result.to_stl_bytes()


def catalog():
    return {
        "sizes": F.SIZES,
        "items": {k: v["label"] for k, v in F.ITEMS.items()},
        "item_kind": {k: v["kind"] for k, v in F.ITEMS.items()},
        "materials": {k: v for k, v in F.MATERIALS.items()},
        "knob_dia": {str(k): v for k, v in F.KNOB_DIA.items()},
        "families": list(M.FAMILIES),
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype, extra=None):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _params(self, qs):
        return M.merge_params({k: v[0] for k, v in qs.items()})

    def do_GET(self):
        u = urlparse(self.path)
        qs = parse_qs(u.query)

        if u.path in ("/", "/index.html"):
            with open(os.path.join(HERE, "index.html"), "rb") as fh:
                return self._send(200, fh.read(), "text/html; charset=utf-8")

        if u.path == "/defaults":
            return self._send(200, json.dumps({"defaults": M.DEFAULTS,
                                               "catalog": catalog()}),
                              "application/json")

        if u.path == "/preview.stl":
            p = self._params(qs)
            errs = M.validate(p)
            if errs:
                return self._send(400, json.dumps({"errors": errs}), "application/json")
            try:
                with KERNEL_LOCK:
                    result, spec, warnings = M.build(p)
                    data = preview_stl(result)
                    stats = {"part": stats_for(result),
                             "derived": M.derived(p, spec),
                             "warnings": warnings}
            except Exception as e:                      # kernel failure
                return self._send(400, json.dumps({"errors": [f"Build failed: {e}"]}),
                                  "application/json")
            return self._send(200, data, "model/stl", {"X-Stats": json.dumps(stats)})

        if u.path == "/export":
            p = self._params(qs)
            errs = M.validate(p)
            if errs:
                return self._send(400, json.dumps({"errors": errs}), "application/json")
            name = qs.get("name", ["knob"])[0].strip() or "knob"
            name = "".join(c for c in name if c.isalnum() or c in "-_")
            with KERNEL_LOCK:
                result, spec, warnings = M.build(p, export=True)
                buf = io.BytesIO()
                with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                    if hasattr(result, "val"):
                        z.writestr(f"{name}.stl", export_bytes(
                            result, "stl", tolerance=0.005, angularTolerance=0.05))
                        z.writestr(f"{name}.step", export_bytes(result, "step"))
                        z.writestr(f"{name}.3mf", export_bytes(result, "3mf"))
                    else:
                        z.writestr(f"{name}.stl", result.to_stl_bytes())
                        z.writestr(f"{name}.3mf", result.to_3mf_bytes(name))
                    z.writestr(f"{name}_parameters.json", json.dumps(p, indent=2))
                    z.writestr(f"{name}_spec.json", json.dumps(
                        {"derived": M.derived(p, spec), "warnings": warnings,
                         "print": "Print as exported: grip face on the bed, "
                                  "pocket opening up. No supports."}, indent=2))
                    z.writestr(f"{name}_model.py", script_for(p))
            return self._send(
                200, buf.getvalue(), "application/zip",
                {"Content-Disposition": f'attachment; filename="{name}.zip"'})

        return self._send(404, "not found", "text/plain")


def script_for(p):
    """A standalone script reproducing exactly this knob, for the archive."""
    lines = [
        "# Generated by KNOBLAB. Standalone - edit and re-run with:",
        "#   python3 this_file.py     (needs model.py, fasteners.py,",
        "#                             generative.py beside it)",
        "import sys, os",
        "sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))",
        "import cadquery as cq",
        "import model as M",
        "",
        "PARAMS = {",
    ]
    for k, v in p.items():
        lines.append(f"    {k!r}: {v!r},")
    lines += [
        "}",
        "",
        "errs = M.validate(PARAMS)",
        "if errs:",
        "    raise SystemExit('\\n'.join(errs))",
        "result, spec, warnings = M.build(PARAMS, export=True)",
        "if hasattr(result, 'val'):",
        "    cq.exporters.export(result, 'knob.stl', tolerance=0.005, angularTolerance=0.05)",
        "    cq.exporters.export(result, 'knob.step')",
        "    cq.exporters.export(result, 'knob.3mf')",
        "else:",
        "    open('knob.stl', 'wb').write(result.to_stl_bytes())",
        "    open('knob.3mf', 'wb').write(result.to_3mf_bytes())",
        "print('exported', M.derived(PARAMS, spec), warnings)",
    ]
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8766)
    ap.add_argument("--no-open", action="store_true")
    a = ap.parse_args()

    try:
        srv = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    except OSError as e:
        print(f"Cannot bind port {a.port}: {e}")
        print(f"Something is already using it. Try:  python3 app.py --port {a.port + 1}")
        raise SystemExit(1)
    url = f"http://localhost:{a.port}"
    print(f"KNOBLAB running at {url}   (ctrl-C to stop)")
    if not a.no_open:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
