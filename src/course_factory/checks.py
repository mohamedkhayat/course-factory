"""Checks every generated Block must pass (#13): structure, citations, math and diagram rendering, quiz sanity,
sympy-verified claims. Also computes the numbers the app owns (Iteration Table rows)."""

import json
import re
import subprocess
from pathlib import Path

import numpy as np
import sympy as sp
from sympy.parsing.sympy_parser import parse_expr, standard_transformations, implicit_multiplication_application, convert_xor

from .catalogue import CATALOGUE, BlockDraft, validate_data

WEB_DIR = Path(__file__).resolve().parents[2] / "web"
MATH_RE = re.compile(r"\$\$(.+?)\$\$|\$(.+?)\$", re.S)
NOT_MARKDOWN = {"mermaid", "code", "expr", "f", "latex", "language", "source"}
TRANSFORMS = standard_transformations + (implicit_multiplication_application, convert_xor)


def parse(expr: str, names: list[str] | tuple[str, ...] = ()) -> sp.Expr:
    local = {n: sp.Symbol(n, real=True) for n in names}
    return parse_expr(expr, local_dict=local, transformations=TRANSFORMS)


def math_in(data, path: str = "") -> list[tuple[str, bool]]:
    """(tex, display) for every math span in the Block data."""
    out: list[tuple[str, bool]] = []
    if isinstance(data, dict):
        for k, v in data.items():
            if k == "latex" and isinstance(v, str):
                out.append((v, True))
            elif k not in NOT_MARKDOWN:
                out += math_in(v, k)
    elif isinstance(data, list):
        for v in data:
            out += math_in(v, path)
    elif isinstance(data, str):
        out += [((d or i).strip(), bool(d)) for d, i in MATH_RE.findall(data)]
    return out


def render_errors(blocks: list[dict]) -> dict[int, list[str]]:
    """KaTeX and Mermaid parse every Block's math and diagrams in one node call."""
    math = [{"id": i, "tex": t, "display": d} for i, b in enumerate(blocks) for t, d in math_in(b["data"])]
    diagrams = [{"id": i, "src": b["data"]["mermaid"]} for i, b in enumerate(blocks) if b["component"] == "diagram"]
    if not math and not diagrams:
        return {}
    out = subprocess.run(["node", str(WEB_DIR / "scripts" / "check-render.mjs")], input=json.dumps({"math": math, "mermaid": diagrams}),
                         capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        raise RuntimeError(f"render checker failed: {out.stderr[-500:]}")
    errors: dict[int, list[str]] = {}
    for e in json.loads(out.stdout)["errors"]:
        errors.setdefault(e["id"], []).append(e["message"])
    return errors


def quiz_errors(data: dict) -> list[str]:
    errs = []
    for n, q in enumerate(data["questions"], 1):
        opts = [o.strip().lower() for o in q["options"]]
        if len(set(opts)) != len(opts):
            errs.append(f"question {n}: options are not distinct")
        if any(not 0 <= c < len(opts) for c in q["correct"]):
            errs.append(f"question {n}: a correct index is out of range")
        if not q["multiple"] and len(set(q["correct"])) != 1:
            errs.append(f"question {n}: single-choice must have exactly one correct option")
        if not q["explanation"].strip():
            errs.append(f"question {n}: explanation is empty")
    return errs


def claim_errors(claims: list[dict]) -> list[str]:
    errs = []
    for c in claims:
        try:
            names = c["vars"]
            f = parse(c["expr"], names)
            syms = [sp.Symbol(n, real=True) for n in names]
            if c["op"] == "equal":
                got, want = f, parse(str(c["expected"]), names)
            elif c["op"] == "diff":
                got, want = sp.diff(f, syms[0]), parse(str(c["expected"]), names)
            elif c["op"] == "grad":
                got = sp.Matrix([sp.diff(f, s) for s in syms])
                want = sp.Matrix([parse(e, names) for e in c["expected"]])
            else:
                got = sp.hessian(f, syms)
                want = sp.Matrix([[parse(e, names) for e in row] for row in c["expected"]])
            diff = sp.simplify(got - want)
            if diff != 0 and not (isinstance(diff, sp.MatrixBase) and diff.is_zero_matrix):
                errs.append(f"sympy: {c['op']} of {c['expr']} is {got}, not {c['expected']}")
        except Exception as e:  # unparseable claims are errors the model must fix
            errs.append(f"sympy could not check claim {c}: {e}")
    return errs


def iteration_rows(data: dict) -> list[dict]:
    """Runs the method so every number in the table comes from the app."""
    syms = [sp.Symbol(n, real=True) for n in data["vars"]]
    f = parse(data["f"], data["vars"])
    f_n = sp.lambdify(syms, f, "numpy")
    g_n = sp.lambdify(syms, [sp.diff(f, s) for s in syms], "numpy")
    h_n = sp.lambdify(syms, sp.hessian(f, syms).tolist(), "numpy")
    x = np.array(data["x0"], dtype=float)
    rows = []
    for k in range(data["iterations"] + 1):
        g = np.array(g_n(*x), dtype=float)
        rows.append({"k": k, "x": [round(float(v), 6) for v in x], "f": round(float(f_n(*x)), 6),
                     "grad_norm": round(float(np.linalg.norm(g)), 6)})
        if k == data["iterations"]:
            break
        x = x - data["step"] * g if data["method"] == "gradient" else x - np.linalg.solve(np.array(h_n(*x), dtype=float), g)
    return rows


def expr_errors(component: str, data: dict) -> list[str]:
    try:
        if component == "plot":
            for fn in data["functions"]:
                parse(fn["expr"], ["x"])
        elif component == "explorer":
            names = ["x"] + [p["name"] for p in data["params"]]
            used = {str(s) for s in parse(data["expr"], names).free_symbols}
            if missing := {p["name"] for p in data["params"]} - used:
                return [f"explorer parameters not used in expr: {sorted(missing)}"]
    except Exception as e:
        return [f"expression does not parse: {e}"]
    return []


def check_blocks(raw: list[dict], sources: dict[str, int]) -> tuple[list[dict], list[list[str]]]:
    """Validates and normalises Blocks. Returns (blocks, errors per Block); sources maps name -> page count."""
    blocks, errors = [], []
    for item in raw:
        errs: list[str] = []
        try:
            draft = BlockDraft.model_validate(item)
        except Exception as e:
            blocks.append({"component": str(item.get("component", "?")), "data": item.get("data") or {}, "citations": [],
                           "origin": "model_added"})
            errors.append([f"not a Block: {e}"])
            continue
        data, errs = validate_data(draft.component, draft.data)
        block = {"component": draft.component, "data": data, "citations": [c.model_dump() for c in draft.citations], "origin": draft.origin}
        for c in draft.citations:
            if not 1 <= c.page <= sources.get(c.source, 0):
                errs.append(f"citation to {c.source} page {c.page} does not exist")
        if draft.origin == "from_source" and not draft.citations:
            errs.append("a From source Block needs at least one Citation")
        if not errs and draft.component in CATALOGUE:
            if draft.component == "quiz":
                errs += quiz_errors(data)
            errs += claim_errors(data.get("claims", []))
            errs += expr_errors(draft.component, data)
            if draft.component == "iteration_table":
                try:
                    data["rows"] = iteration_rows(data)
                except Exception as e:
                    errs.append(f"iteration table cannot be computed: {e}")
        blocks.append(block)
        errors.append(errs)
    for i, errs in render_errors([b if not errors[n] else {"component": "", "data": {}} for n, b in enumerate(blocks)]).items():
        errors[i] += errs
    return blocks, errors
