"""Components the local model proposes when the Catalogue can't express something.

A proposal is built into one .tsx file from a constrained template, then gated (strict tsc, import allowlist,
esbuild bundle, sandboxed render + screenshot). Passing Components wait for the owner's preview; approval writes a
shadcn registry item tagged provenance=local-model, reviewed=false, and Claude Code works the Review Queue later."""

import datetime as dt
import json
import subprocess
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .catalogue import CATALOGUE
from .checks import schema_errors
from .context import Ctx
from .pi_step import HARNESS_DIR, StepFailed, record_owner_action, run_pi_step

WEB_DIR = Path(__file__).resolve().parents[2] / "web"
TEMPLATE = (HARNESS_DIR / "component_template.tsx").read_text()
BUILDS = 3  # build attempts, each told the previous gate errors
PENDING = "component pending:"
REJECTED = "component rejected:"

COMPONENTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS components (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, description TEXT NOT NULL, why TEXT NOT NULL DEFAULT '',
  schema TEXT NOT NULL, samples TEXT NOT NULL, code TEXT, status TEXT NOT NULL DEFAULT 'building',
  gates TEXT NOT NULL DEFAULT '[]', course_id INTEGER REFERENCES courses(id), provenance TEXT NOT NULL DEFAULT 'local-model',
  reviewed INTEGER NOT NULL DEFAULT 0, review_notes TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
);
"""
# status: building -> preview (gates passed) -> approved | rejected; failed when no build passed the gates


class ComponentProposal(BaseModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{2,40}$")
    description: str
    why: str = ""
    schema_: dict = Field(alias="schema")  # JSON Schema of the Block data
    samples: list[dict] = Field(min_length=1)


class BuiltComponent(BaseModel):
    code: str


class ComponentEdit(BaseModel):
    """What Claude Code sends back from the Review Queue."""
    code: str | None = None
    schema_: dict | None = Field(default=None, alias="schema")
    reviewed: bool | None = None
    notes: str | None = None


class Note(BaseModel):
    note: str = Field(min_length=1)


def comp_dir(ctx: Ctx, name: str) -> Path:
    return ctx.data_dir / "components" / name


def gate(code: str, samples: list[dict], out_dir: Path) -> dict:
    """Seam 2: one Component file plus sample Blocks in, pass or fail with reasons per gate out."""
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "Component.tsx").write_text(code)
    (out_dir / "samples.json").write_text(json.dumps(samples, ensure_ascii=False))
    try:
        p = subprocess.run(["node", str(WEB_DIR / "scripts" / "gate-component.mjs"), str(out_dir / "Component.tsx"),
                            str(out_dir / "samples.json"), str(out_dir)], capture_output=True, text=True, timeout=180)
        return json.loads(p.stdout.strip().splitlines()[-1])
    except Exception as e:
        return {"ok": False, "gates": [{"gate": "runner", "ok": False, "errors": [str(e)[:500]]}]}


def schemas(db) -> dict[str, dict]:
    """Model-made Components a Block may use: anything not rejected or failed."""
    return {r["name"]: json.loads(r["schema"]) for r in db.execute(
        "SELECT name, schema FROM components WHERE status IN ('building', 'preview', 'approved')")}


def status_flags(db, component: str) -> tuple[list[str], list[str]]:
    """(errors, warnings) a Block gets from its Component's state; not live means it shows as Markdown."""
    if component in CATALOGUE:
        return [], []
    row = db.execute("SELECT status FROM components WHERE name=?", (component,)).fetchone()
    if row is None or row["status"] in ("rejected", "failed"):
        return [f"{REJECTED} '{component}' is not available; the Block is shown as Markdown"], []
    if row["status"] != "approved":
        return [], [f"{PENDING} '{component}' awaits your preview; the Block is shown as Markdown until then"]
    return [], []


def describe_custom(db) -> str:
    rows = db.execute("SELECT name, description, schema FROM components WHERE status='approved' ORDER BY name").fetchall()
    return "\n".join(f"- {r['name']} (made by local model): {r['description']} Data JSON Schema: {r['schema']}" for r in rows)


def propose(ctx: Ctx, cid: int, p: ComponentProposal) -> None:
    """Registers and builds a proposal, unless that name already exists."""
    db = ctx.db
    if p.name in CATALOGUE or db.execute("SELECT 1 FROM components WHERE name=?", (p.name,)).fetchone():
        return
    samples = [s for s in p.samples if not schema_errors(p.schema_, s)]  # only samples that fit the schema are rendered
    if not samples:
        return
    db.execute("INSERT INTO components (name, description, why, schema, samples, course_id, created_at) VALUES (?,?,?,?,?,?,?)",
               (p.name, p.description, p.why, json.dumps(p.schema_, ensure_ascii=False), json.dumps(samples, ensure_ascii=False),
                cid, dt.datetime.now(dt.UTC).isoformat()))
    build(ctx, cid, p.name)


def build(ctx: Ctx, cid: int, name: str, note: str | None = None) -> dict:
    """Builds the file and runs the gates, up to BUILDS times. Ends in preview (passed) or failed."""
    db = ctx.db
    c = db.execute("SELECT * FROM components WHERE name=?", (name,)).fetchone()
    db.execute("UPDATE components SET status='building' WHERE id=?", (c["id"],))
    errors: list[str] = []
    result: dict = {"ok": False, "gates": []}
    for _ in range(BUILDS):
        try:
            built = run_pi_step(db, ctx.backend, "build_component", {
                "name": name, "description": c["description"], "schema": json.loads(c["schema"]), "samples": json.loads(c["samples"]),
                "template": TEMPLATE, "previous": c["code"] or "", "errors": errors, "note": note or ""},
                BuiltComponent, ctx.course_dir(cid), course_id=cid)
        except StepFailed as e:
            result = {"ok": False, "gates": [{"gate": "build", "ok": False, "errors": [str(e)[:500]]}]}
            break
        result = gate(built.code, json.loads(c["samples"]), comp_dir(ctx, name))
        db.execute("UPDATE components SET code=?, gates=? WHERE id=?", (built.code, json.dumps(result["gates"]), c["id"]))
        if result["ok"]:
            break
        errors = [f"{g['gate']}: {e}" for g in result["gates"] if not g["ok"] for e in g["errors"]]
        c = db.execute("SELECT * FROM components WHERE id=?", (c["id"],)).fetchone()
    db.execute("UPDATE components SET status=? WHERE id=?", ("preview" if result["ok"] else "failed", c["id"]))
    revalidate(ctx, name)
    return result


def revalidate(ctx: Ctx, name: str) -> None:
    """Re-checks every Block that uses this Component against its current schema and state."""
    db = ctx.db
    row = db.execute("SELECT schema FROM components WHERE name=?", (name,)).fetchone()
    schema = json.loads(row["schema"]) if row else None
    for b in db.execute("SELECT id, data, flags FROM blocks WHERE component=?", (name,)).fetchall():
        kept = [f for f in json.loads(b["flags"]) if not f.startswith((PENDING, REJECTED, "schema:"))]
        errors, warnings = status_flags(db, name)
        if schema is not None:
            errors += [f"schema: {e}" for e in schema_errors(schema, json.loads(b["data"]))]
        flags = kept + errors + warnings
        hard = [f for f in flags if not f.startswith(("grounding", PENDING))]
        db.execute("UPDATE blocks SET flags=?, status=? WHERE id=?",
                   (json.dumps(flags, ensure_ascii=False), "flagged" if hard else "ok", b["id"]))


def registry_item(c) -> dict:
    return {"$schema": "https://ui.shadcn.com/schema/registry-item.json", "name": c["name"], "type": "registry:component",
            "title": c["name"].replace("_", " ").title(), "description": c["description"], "dependencies": [],
            "files": [{"path": f"components/cf/{c['name']}.tsx", "type": "registry:component", "content": c["code"]}],
            "meta": {"provenance": c["provenance"], "reviewed": bool(c["reviewed"]), "data_schema": json.loads(c["schema"])}}


def write_registry(ctx: Ctx, name: str) -> None:
    c = ctx.db.execute("SELECT * FROM components WHERE name=?", (name,)).fetchone()
    folder = ctx.data_dir / "registry"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.json").write_text(json.dumps(registry_item(c), ensure_ascii=False, indent=2))


def component_json(ctx: Ctx, c, full: bool = False) -> dict:
    out = {"id": c["id"], "name": c["name"], "description": c["description"], "why": c["why"], "status": c["status"],
           "provenance": c["provenance"], "reviewed": bool(c["reviewed"]), "made_by_local_model": c["provenance"] == "local-model",
           "gates": json.loads(c["gates"]), "has_screenshot": (comp_dir(ctx, c["name"]) / "screenshot.png").exists()}
    if full:
        blocks = [{"id": b["id"], "data": json.loads(b["data"]), "status": b["status"], "flags": json.loads(b["flags"])}
                  for b in ctx.db.execute("SELECT * FROM blocks WHERE component=? ORDER BY id", (c["name"],))]
        out |= {"schema": json.loads(c["schema"]), "samples": json.loads(c["samples"]), "code": c["code"],
                "review_notes": c["review_notes"], "blocks": blocks}
    return out


def router(ctx: Ctx) -> APIRouter:
    db = ctx.db
    db.executescript(COMPONENTS_SCHEMA)
    r = APIRouter()

    def comp_or_404(comp_id: int):
        c = db.execute("SELECT * FROM components WHERE id=?", (comp_id,)).fetchone()
        if c is None:
            raise HTTPException(404, "no such Component")
        return c

    def owner_action(c, decision: dict, action: str):
        if c["course_id"] is not None:
            record_owner_action(db, c["course_id"], "component_preview", {"component": c["name"], **decision}, action)

    @r.get("/api/components")
    def list_components():
        return [component_json(ctx, c) for c in db.execute("SELECT * FROM components ORDER BY id")]

    @r.get("/api/components/{comp_id}")
    def get_component(comp_id: int):
        """The preview: spec, code, gate results and the real Blocks that use it."""
        return component_json(ctx, comp_or_404(comp_id), full=True)

    @r.get("/api/components/{comp_id}/screenshot")
    def screenshot(comp_id: int):
        path = comp_dir(ctx, comp_or_404(comp_id)["name"]) / "screenshot.png"
        if not path.exists():
            raise HTTPException(404, "no screenshot")
        return FileResponse(path)

    @r.get("/api/components/{comp_id}/bundle.js")
    def bundle(comp_id: int):
        """The gated bundle; the reader runs it in a sandboxed iframe (window.CF.render(el, data, onError))."""
        c = comp_or_404(comp_id)
        path = comp_dir(ctx, c["name"]) / "component.js"
        if c["status"] not in ("preview", "approved") or not path.exists():
            raise HTTPException(404, "not built")
        return FileResponse(path, media_type="text/javascript")

    @r.post("/api/components/{comp_id}/approve")
    def approve(comp_id: int):
        c = comp_or_404(comp_id)
        if c["status"] != "preview":
            raise HTTPException(409, "only a Component waiting for preview can be approved")
        owner_action(c, {}, "approved")
        db.execute("UPDATE components SET status='approved' WHERE id=?", (comp_id,))
        write_registry(ctx, c["name"])
        revalidate(ctx, c["name"])
        return component_json(ctx, comp_or_404(comp_id), full=True)

    @r.post("/api/components/{comp_id}/reject")
    def reject(comp_id: int):
        c = comp_or_404(comp_id)
        if c["status"] not in ("preview", "failed", "approved"):
            raise HTTPException(409, "this Component can't be rejected now")
        owner_action(c, {}, "rejected")
        db.execute("UPDATE components SET status='rejected' WHERE id=?", (comp_id,))
        (ctx.data_dir / "registry" / f"{c['name']}.json").unlink(missing_ok=True)
        revalidate(ctx, c["name"])
        return component_json(ctx, comp_or_404(comp_id), full=True)

    @r.post("/api/components/{comp_id}/regenerate")
    def regenerate(comp_id: int, body: Note):
        c = comp_or_404(comp_id)
        if c["status"] not in ("preview", "failed", "rejected"):
            raise HTTPException(409, "this Component can't be regenerated now")
        owner_action(c, {"note": body.note}, "regenerated")
        build(ctx, c["course_id"], c["name"], note=body.note)
        return component_json(ctx, comp_or_404(comp_id), full=True)

    @r.get("/api/review-components")
    def review_queue():
        """The Review Queue: live model-made Components nobody has reviewed. Worked by Claude Code from outside."""
        return [component_json(ctx, c, full=True) for c in db.execute(
            "SELECT * FROM components WHERE status='approved' AND reviewed=0 ORDER BY id")]

    @r.put("/api/components/{comp_id}")
    def edit_component(comp_id: int, body: ComponentEdit):
        """A reviewer's fix: new code is re-gated (kept only if it passes), a new schema re-validates the Blocks."""
        c = comp_or_404(comp_id)
        if c["status"] != "approved":
            raise HTTPException(409, "only live Components are reviewed")
        if body.schema_ is not None:
            bad = [e for s in json.loads(c["samples"]) for e in schema_errors(body.schema_, s)]
            if bad:
                raise HTTPException(422, {"gates": [], "errors": bad})
        result = None
        if body.code is not None:
            result = gate(body.code, json.loads(c["samples"]), comp_dir(ctx, c["name"]) / "candidate")
            if not result["ok"]:
                raise HTTPException(422, {"gates": result["gates"]})
        if body.schema_ is not None:  # written only once the code (if any) has passed
            db.execute("UPDATE components SET schema=? WHERE id=?", (json.dumps(body.schema_, ensure_ascii=False), comp_id))
        if body.code is not None and result is not None:
            for f in ("component.js", "screenshot.png"):
                (comp_dir(ctx, c["name"]) / "candidate" / f).replace(comp_dir(ctx, c["name"]) / f)
            db.execute("UPDATE components SET code=?, gates=? WHERE id=?", (body.code, json.dumps(result["gates"]), comp_id))
        if body.reviewed is not None:
            db.execute("UPDATE components SET reviewed=? WHERE id=?", (int(body.reviewed), comp_id))
        if body.notes is not None:
            db.execute("UPDATE components SET review_notes=? WHERE id=?", (body.notes, comp_id))
        write_registry(ctx, c["name"])
        revalidate(ctx, c["name"])
        return component_json(ctx, comp_or_404(comp_id), full=True)

    return r
