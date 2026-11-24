"""Checks every generated Block must pass (#13): structure, citations, math and diagram rendering, quiz sanity,
sympy-verified claims. Also computes the numbers the app owns (Iteration Table rows)."""

import ast
import builtins
import collections
import functools
import json
import keyword
import jsonschema
import re
import subprocess
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import sympy as sp
import yaml
from sympy.parsing.sympy_parser import parse_expr, standard_transformations, implicit_multiplication_application, convert_xor

from .catalogue import CATALOGUE, BlockDraft, validate_data
from .kernels import LAB_IMAGE_TAG
from .pi_step import LATEX_WORDS

DIAGRAMS = ("diagram", "step_diagram")  # the Components drawn in Mermaid

WEB_DIR = Path(__file__).resolve().parents[2] / "web"
MATH_RE = re.compile(r"\$\$(.+?)\$\$|\$(.+?)\$", re.S)
NOT_MARKDOWN = {"mermaid", "code", "expr", "f", "latex", "language", "source", "template", "starter", "solution", "command",
                "output", "answers", "highlight", "shell"}
TRANSFORMS = standard_transformations + (implicit_multiplication_application, convert_xor)


NAME = re.compile(r"(?<![\w.'\"])[A-Za-z_]\w+")


def parse(expr: str, names: list[str] | tuple[str, ...] = ()) -> sp.Expr:
    # implicit multiplication splits x1 into x*1 and lam into l*a*m: every longer name that is not sympy's or Python's is one symbol
    own = {n for n in NAME.findall(expr) if not (hasattr(sp, n) or hasattr(builtins, n) or keyword.iskeyword(n))}
    local = {n: sp.Symbol(n, real=True) for n in own | set(names)}
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
        out += [((d or i).strip(), bool(d)) for d, i in MATH_RE.findall(CODE_SPAN.sub("", data))]  # remark-math skips code
    return out


def render_errors(blocks: list[dict]) -> dict[int, list[str]]:
    """KaTeX and Mermaid parse every Block's math and diagrams in one node call."""
    math = [{"id": i, "tex": t, "display": d} for i, b in enumerate(blocks) for t, d in math_in(b["data"])]
    diagrams = [{"id": i, "src": b["data"]["mermaid"]} for i, b in enumerate(blocks) if b["component"] in DIAGRAMS]
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
        if q.get("explanations") and len(q["explanations"]) != len(opts):
            errs.append(f"question {n}: explanations must give one per option, in option order")
        if not q["multiple"] and len(set(q["correct"])) != 1:
            errs.append(f"question {n}: single-choice must have exactly one correct option")
        if not q["explanation"].strip():
            errs.append(f"question {n}: explanation is empty")
        if any(CATCH_ALL.search(o) for o in opts):
            errs.append(f"question {n}: \"all/none of the above\" is a cue, not a mistake: make every wrong option a real misconception")
    return errs + length_cue(data["questions"])


CATCH_ALL = re.compile(r"\b(all|none) of the above\b|toutes les r[ée]ponses|aucune (de ces|des) r[ée]ponses", re.I)
LABEL = re.compile(r'\["?([^\]"]*)"?\]|\("?([^)"]*)"?\)|\{"?([^}"]*)"?\}')


FIGURE_KEPT = 0.6  # share of a cited figure's entities a diagram redrawing it must keep



def length_cue(questions: list[dict]) -> list[str]:
    """The right option given away by its length (#harden quiz-cue): a learner who picks the longest scores. A question counts when its
    right option is clearly longer than every wrong one; options that are all bare names or numbers are left out (their length is the name's)."""
    seen = []  # (question number, right length, longest wrong length)
    for n, q in enumerate(questions, 1):
        if len(q["options"]) > 1 and len(q["correct"]) == 1 and 0 <= (c := q["correct"][0]) < len(q["options"]) \
                and any(" " in o.strip() for o in q["options"]):
            seen.append((n, len(q["options"][c].strip()), max(len(o.strip()) for i, o in enumerate(q["options"]) if i != c)))
    clear = [n for n, r, w in seen if r >= 1.25 * w and r - w >= 8]
    cued = {n for n, r, w in seen if r >= 2 * w and r - w >= 20}  # one question twice as long: that question is given away
    if len(clear) >= 2 and len(clear) > len(seen) / 2:
        cued |= set(clear)
    if len(seen) >= 3 and all(r > w for _, r, w in seen):
        cued |= {n for n, _, _ in seen}
    if not cued:
        return []
    ns = sorted(cued)
    which = f"question {ns[0]}" if len(ns) == 1 else "questions " + ", ".join(map(str, ns))
    return [f"quiz cue: the right option is clearly the longest in {which} (of {len(questions)}), so a learner picks it by length. "
            "Rewrite the wrong options to be as long and as specific as the right one (the same detail, qualifiers and parentheses, "
            "each a real mistake), or shorten the right one"]

def figure_warnings(src: str, pages: list[dict]) -> list[str] | None:
    """For a diagram citing pages read with figures: what of the figures it drops (entities, containment).
    None when no cited page has a figure, so there is nothing to compare."""
    figures = [f for p in pages for f in p.get("figures") or []]
    if not figures:
        return None
    labels = " ".join(t for m in re.findall(r'"([^"]*)"', src) + [next((g for g in m if g), "") for m in LABEL.findall(src)]
                      for t in [m] if t).lower()
    found = lambda e: re.search(r"(?<!\w)" + re.escape(e.lower().strip()) + r"(?!\w)", labels)
    out = []
    entities = list(dict.fromkeys(e for f in figures for e in f.get("entities", []) if e.strip()))
    missing = [e for e in entities if not found(e)]
    if entities and len(missing) > (1 - FIGURE_KEPT) * len(entities):
        out.append(f"the cited figure shows {len(entities)} things, the diagram keeps {len(entities) - len(missing)}; "
                   f"missing {', '.join(missing[:12])}")
    holders = list(dict.fromkeys(c[0] for f in figures for c in f.get("contains", []) if len(c) == 2))
    if holders and not re.search(r"(?m)^\s*subgraph\b", src):
        out.append(f"the figure puts things inside {', '.join(holders[:6])}; draw each as a subgraph holding its parts, not a flat chain")
    return ["figure fidelity: " + "; ".join(out)] if out else []


def block_warnings(block: dict, pages: Sequence[dict] = ()) -> list[str]:
    """Item-writing and readability heuristics: shown on the Block, never block it. `pages`: the Block's cited pages."""
    data, out = block["data"], []
    if block["component"] in DIAGRAMS and re.match(r"\s*(flowchart|graph)\b", src := data.get("mermaid", "")):
        body = src.split("\n", 1)[-1]
        ids = flow_nodes(src)
        fidelity = figure_warnings(src, list(pages))
        out += fidelity or []
        # a step_diagram already shows it a stage at a time; a faithful redraw of a figure is as big as the figure
        if len(ids) > 9 and block["component"] == "diagram" and fidelity is None:
            out.append(f"diagram size: {len(ids)} nodes; keep to 9 at most, split it or walk it as a step_diagram")
        long = [t for t in (next(g for g in m if g) for m in LABEL.findall(body) if any(m))
                if len(re.findall(r"[^\W\d_]{2,}", re.sub(r"\$[^$]*\$|<[^>]+>", " ", t))) > 6]  # words, not symbols
        if long:
            out.append(f"diagram size: labels of 2-4 words read at a glance; shorten {long[0]!r} and put the detail in the text")
    if block["component"] == "theorem_box" and data.get("kind") == "definition":
        terms = list(dict.fromkeys(t.strip() for t in re.findall(r"\*\*([^*\n]{1,40}?)(?::\*\*|\*\*\s*:)", data.get("statement", ""))))
        if len(terms) >= 3:
            out.append(f"definition cram: one definition defines {', '.join(terms)}; give each term its own theorem_box, "
                       "with its own why-it-matters line")
    return out


FLOAT_TOLERANCE = 1e-4  # relative: decimals in a worked example are already rounded


def natural(name: str) -> list:
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", name)]


def value(v, names):
    """Parses an expected value: an expression, or a list written as a JSON list, a string "[a, b]" or "a, b"."""
    if isinstance(v, list):
        return [value(x, names) for x in v]
    s, depth, top_comma = str(v).strip(), 0, False
    for ch in s:
        depth += ch in "([{"
        depth -= ch in ")]}"
        top_comma |= ch == "," and depth == 0
    return parse(f"[{s}]" if top_comma else s, names)


def canon(v):
    """One shape for sympy's many: solve's dicts and lists of tuples, eigenvals' dicts, matrices, 1-element lists."""
    if isinstance(v, dict):
        if all(isinstance(k, sp.Symbol) for k in v):
            return canon([v[k] for k in sorted(v, key=lambda k: natural(str(k)))])
        return canon(sorted(([k, x] for k, x in v.items()), key=lambda kv: sp.default_sort_key(sp.sympify(kv[0]))))
    if isinstance(v, sp.MatrixBase):
        v = v.tolist()
    if isinstance(v, (list, tuple, sp.Tuple)):
        items = [canon(x) for x in v]
        return items[0] if len(items) == 1 else items
    return sp.sympify(v)


def same(got, want) -> bool:
    if isinstance(got, list) or isinstance(want, list):
        return isinstance(got, list) and isinstance(want, list) and len(got) == len(want) and all(map(same, got, want))
    d = sp.simplify(got - want)
    if d == 0 or d.has(sp.log) and sp.simplify(sp.expand_log(d, force=True)) == 0:  # log(1/u) = -log(u): simplify won't split logs
        return True
    if d.is_number and (got.has(sp.Float) or want.has(sp.Float)):
        return abs(float(d)) <= FLOAT_TOLERANCE * max(1.0, abs(float(want)))
    return False


def free(v) -> set:
    return set().union(*map(free, v)) if isinstance(v, list) else getattr(v, "free_symbols", set())


def flat(v) -> list:
    return [y for x in v for y in flat(x)] if isinstance(v, list) else [v]


def at_point(v, at: dict):
    """Substitutes the point by symbol name, so x and a real x both take it."""
    if isinstance(v, list):
        return [at_point(x, at) for x in v]
    return v.subs({s: parse(str(at[str(s)])) for s in v.free_symbols if str(s) in at})


def fits(got, want) -> bool:
    """Some real point makes got equal want: a value at a point the claim never names, which sympy cannot decide.
    No such point at all, and the claim is wrong wherever it was taken."""
    g, w = flat(got), flat(want)
    if len(g) != len(w) or sum(sp.count_ops(x) for x in g) > 200:
        return True  # shortcut: a shape mismatch or a large system is not solved (it could stall the check); skipped
    try:
        sols = sp.solve([x - y for x, y in zip(g, w)], sorted(free(got), key=str), dict=True)
    except Exception:
        return True
    return any(all(v.is_real is not False for v in sol.values()) for sol in sols)


def claim_errors(claims: list[dict]) -> list[str]:
    """Only a claim sympy proves wrong is an error; one it cannot read or decide checks nothing and is skipped."""
    errs = []
    for c in claims:
        try:
            op, names, at = c["op"], c["vars"], c.get("at") or {}
            free_names = sorted((str(s) for s in free(canon(parse(c["expr"])))), key=natural)
            if op != "equal" and not names or op == "grad" and isinstance(c["expected"], list) and len(c["expected"]) != len(names):
                names = free_names
            f, want = parse(c["expr"], names), value(c["expected"], names)
            if op == "equal" and isinstance(canon(want), list) and not isinstance(canon(f), list):
                op, names = ("hessian" if isinstance(canon(want)[0], list) else "grad"), names or free_names  # written under equal
                f, want = parse(c["expr"], names), value(c["expected"], names)
            if isinstance(at, list):  # a point given as coordinates, in the order of vars (else of the names, x before y)
                at = dict(zip(names or free_names, at)) if len(at) == len(names or free_names) else None
                if at is None:
                    continue
            syms = [sp.Symbol(n, real=True) for n in names]

            def matches(g):
                return same(at_point(canon(g), at), at_point(canon(want), at))

            if op == "grad" and not isinstance(want, list):
                op = "diff"  # one partial derivative written as a gradient
            if op == "equal":
                got = f
            elif op == "diff":
                # no vars: the derivative may be with respect to any of its symbols, not just the first by name
                got = next((g for g in (sp.diff(f, s) for s in (syms if not c["vars"] else syms[:1])) if matches(g)),
                           sp.diff(f, syms[0]))
            elif op == "grad":
                got = [sp.diff(f, s) for s in syms]
            else:
                got = sp.hessian(f, syms)
                if isinstance(want, list) and len(want) == len(syms) ** 2 and not isinstance(want[0], list):
                    want = [want[i:i + len(syms)] for i in range(0, len(want), len(syms))]  # flat "a, b, c, d"
            got, want = at_point(canon(got), at), at_point(canon(want), at)
            ok = same(got, want)
            if not ok and not at and free(got) and not free(want) and fits(got, want):
                continue
        except Exception:
            continue
        if not ok:
            errs.append(f"sympy: {c['op']} of {c['expr']}{f' at {at}' if at else ''} is {got}, not {c['expected']}")
    return errs


TEXT_FIXES = [
    (re.compile(r"\\n(?![A-Za-z])"), "\n"),  # a newline the model escaped twice
    (re.compile(r"\$\$\$\$"), "$$\n$$"),  # two display formulas run together
    (re.compile(r"(\\text\{[^{}]*?)(\\[A-Za-z]+)([^{}]*\})"), r"\1}\2\\text{\3"),  # math command inside \text{}
]
DOUBLED_COMMAND = re.compile(r"\\{2,}(?=[A-Za-z])")
SINGLE_COMMAND = re.compile(r"(?<!\\)(?:\\\\)*\\[A-Za-z]")  # an odd run of backslashes before a letter: a command escaped right
MATH_SPAN = re.compile(r"(\$\$.+?\$\$|\$[^$]+?\$)", re.S)
OUTSIDE_MATH = [
    (re.compile(r"\\n([A-Za-z]*)"), lambda m: m[0] if "n" + m[1] in LATEX_WORDS else "\n" + m[1]),  # "\nLa" is a newline, "\neq" is not
    (re.compile(r"\\q?quad\s*"), " "),
]
MERMAID_LIST = re.compile(r'(["|]\s*)(\d+\.|[-+*])(?=\s)')  # a label starting like a Markdown list fails to render
MERMAID_MATH = re.compile(r"\$[^$\n]+\$")
MERMAID_PARENS = re.compile(r'(\b\w+)\[(?!["(\[/\\])([^\]"\n]*[()][^\]"\n]*)\]')  # A[Uvicorn (ASGI)] fails; A[(db)] is a cylinder
LIST_FIELDS = {"steps", "hints"}


def heal_markdown(s: str) -> str:
    for pattern, repl in TEXT_FIXES:
        s = pattern.sub(repl, s)
    if s.count("$$") % 2:
        s += "$$"  # the last display formula was never closed
    parts = MATH_SPAN.split(s)
    for i in range(1, len(parts), 2):  # "\\rho" escaped twice: a line break, then "rho"
        if not SINGLE_COMMAND.search(parts[i]):  # a formula escaped right elsewhere ("\begin{pmatrix}s&s\\s&t") keeps its row breaks
            parts[i] = DOUBLED_COMMAND.sub(r"\\", parts[i])
    for i in range(0, len(parts), 2):
        for pattern, fix in OUTSIDE_MATH:
            parts[i] = pattern.sub(fix, parts[i])
    return "".join(parts)


def heal_text(data, key: str = ""):
    """Deterministic fixes for text the model reliably mangles, so they need no repair call."""
    if isinstance(data, dict):
        return {k: heal_text(v, k) for k, v in data.items()}
    if isinstance(data, list):
        return [heal_text(v, key) for v in data if not (key in LIST_FIELDS and isinstance(v, str) and not v.strip())]
    if not isinstance(data, str):
        return data
    if key == "mermaid":
        data = MERMAID_MATH.sub(lambda m: re.sub(r"\\\\(?=[A-Za-z])", r"\\", m[0]), data)  # "\\geq" escaped twice: a line break, then "geq"
        data = MERMAID_PARENS.sub(r'\1["\2"]', data)
        return MERMAID_LIST.sub(lambda m: m[1] + (m[2][:-1] + "#46;" if m[2].endswith(".") else f"#{ord(m[2])};"), data)
    if key == "latex":
        return TEXT_FIXES[2][0].sub(TEXT_FIXES[2][1], data)
    return data if key in NOT_MARKDOWN else heal_markdown(data)


ASCII_MATH = re.compile(r"\bsqrt\(|\bexp\(|(?<!\*\*)[\w)]\*\*(?:[\d(]|[A-Za-z](?!\w|\*\*))|\w\^\(")  # x**2, e**x; not **D**éveloppeurs or Gi**t**H (bold)
CODE_SPAN = re.compile(r"```.*?```|`[^`]*`", re.S)
# shortcut: assumes French/English courses; a course taught in Chinese, Japanese or Korean would need this off
# a correction that argues with itself ("Attendez — relisons") was written before its answer was worked out, and is often wrong
SECOND_THOUGHTS = re.compile(r"\battendez(?!-vous)|\brecalculons\b|\brelisons\b|\boups\b|\bwait\s*[,—:-]|\bhold on\b|\blet me re-?(?:check|compute|calculate)", re.I)
CJK = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]+")


def ascii_math_errors(data, key: str = "") -> list[str]:
    """Formulas written as code (sqrt(n), e^(iu.X)) outside $…$: they show as plain text, not as math."""
    if isinstance(data, dict):
        return [e for k, v in data.items() if k != "claims" for e in ascii_math_errors(v, k)]  # claims are sympy syntax
    if isinstance(data, list):
        return [e for v in data for e in ascii_math_errors(v, key)]
    if not isinstance(data, str) or (key in NOT_MARKDOWN and key != "mermaid"):
        return []
    m = ASCII_MATH.search(CODE_SPAN.sub("", MATH_SPAN.sub("", data)))
    return [f"{key or 'text'} writes a formula as code near {m.group()!r}: write it as LaTeX inside $…$ (e.g. $\\sqrt{{n}}$, $e^{{iuX}}$)"] if m else []


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
    exprs = [fn["expr"] for fn in data["functions"]] if component == "plot" else [data["expr"]] if component == "explorer" else []
    if unknown := {name for e in exprs for name in re.findall(r"([A-Za-z_]\w*)\s*\(", e)} - DRAWABLE:
        return [f"the plotter cannot draw {sorted(unknown)}; use only {', '.join(sorted(DRAWABLE))}"]
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


DOCKER_INSTRUCTIONS = {"FROM", "RUN", "CMD", "LABEL", "MAINTAINER", "EXPOSE", "ENV", "ADD", "COPY", "ENTRYPOINT", "VOLUME", "USER",
                       "WORKDIR", "ARG", "ONBUILD", "STOPSIGNAL", "HEALTHCHECK", "SHELL"}
GAP = re.compile(r"\[\[(\d+)\]\]")
PY_ONLY_REGEX = re.compile(r"\(\?[aiLmsux]+[):]|\(\?P[<=>]")  # inline flags and Python's named groups break new RegExp()
CONSOLE_REQUEST = re.compile(r"^(?:GET|PUT|POST|DELETE|HEAD|PATCH) /\S*[ \t]*$", re.M)


def syntax_errors(language: str, src: str) -> list[str]:
    """Parses code in the languages with a cheap parser; others pass."""
    lang = language.strip().lower()
    try:
        if lang in ("python", "py"):
            ast.parse(src)
        elif lang in ("yaml", "yml"):
            list(yaml.safe_load_all(src))
        elif lang == "json":
            for body in CONSOLE_REQUEST.split(src):  # Elasticsearch/Kibana console: "PUT /index" lines, each followed by JSON
                if body.strip():
                    json.loads(body)
        elif lang == "dockerfile":
            for line in re.sub(r"\\\n", " ", src).splitlines():  # continuation lines join their instruction
                word = line.split(maxsplit=1)[0] if line.strip() and not line.lstrip().startswith("#") else None
                if word and word.upper() not in DOCKER_INSTRUCTIONS:
                    raise ValueError(f"unknown instruction {word!r}")
    except Exception as e:
        return [f"{lang} does not parse: {str(e)[:300]}"]
    return dockerfile_errors(src) if lang == "dockerfile" else []


RUN_TARGET = re.compile(r"([\w./-]+\.py)\b|\b([A-Za-z_][\w.]*):[A-Za-z_]\w*")  # python app.py | uvicorn pkg.main:app


def dockerfile_errors(src: str) -> list[str]:
    """Two mistakes that parse but fail at docker build or container start: a COPY of several files into a path that
    is not a directory, and a CMD/ENTRYPOINT that runs a file no COPY/ADD brings into the image."""
    errors, sources, targets = [], [], []
    for line in re.sub(r"\\\n", " ", src).splitlines():
        word, _, rest = line.strip().partition(" ")
        if word.upper() in ("COPY", "ADD"):
            try:
                args = json.loads(rest) if rest.lstrip().startswith("[") else rest.split()
            except ValueError:
                args = rest.split()
            args = [a for a in args if not a.startswith("--")]
            if len(args) > 2 and not (args[-1].endswith("/") or args[-1] == "."):
                errors.append(f"dockerfile: {line.strip()!r} copies several files, so the destination must be a directory "
                              f"ending in / ({args[-1]}/), or docker build fails")
            sources += [a.removeprefix("./").rstrip("/") for a in args[:-1]]
        elif word.upper() in ("CMD", "ENTRYPOINT"):
            server = re.search(r"\b(uvicorn|gunicorn|hypercorn)\b", rest)
            targets += [py or mod for py, mod in RUN_TARGET.findall(rest) if py or (mod and server)]

    def brought_in(target: str) -> bool:
        path = target if target.endswith(".py") else target.replace(".", "/") + ".py"
        name, top = path.rsplit("/", 1)[-1], path.lstrip("/").split("/")[0]
        # shortcut: a source without an extension is taken to be a directory that holds the file
        return any(s in ("", ".") or "*" in s or "." not in s.rsplit("/", 1)[-1] or s.rsplit("/", 1)[-1] in (name, top) for s in sources)

    if sources:  # no COPY at all is a bind-mounted dev image; a COPY that forgets the program is the mistake
        errors += [f"dockerfile: the container runs {t!r} but no COPY/ADD brings it into the image (only {', '.join(sources)}): "
                   "copy it too (or COPY . .), or the container fails at start" for t in dict.fromkeys(targets) if not brought_in(t)]
    return errors


DRAWABLE ={"exp", "log", "sqrt", "sin", "cos", "tan", "asin", "acos", "atan", "sinh", "cosh", "tanh", "abs", "pi", "E"}
KINKS = (sp.Abs, sp.sign, sp.Heaviside, sp.Piecewise, sp.floor, sp.ceiling, sp.Max, sp.Min, sp.DiracDelta)


def drawable(expr: str, names: list[str]) -> sp.Expr:
    """Parses expr with sympy and refuses names the browser's plotter (mathjs) does not know the same way."""
    if unknown := set(re.findall(r"[A-Za-z_]\w*", expr)) - DRAWABLE - set(names):
        raise ValueError(f"expr must be a function of {' and '.join(names)} only, using {', '.join(sorted(DRAWABLE))}; "
                         f"it uses {sorted(unknown)}")
    return parse(expr, names)


def curve(expr: str, x_range, n: int = 160) -> list[list[float]]:
    """Points [x, y] of a function of x over a range (those where it is defined): what a function_plot Video draws."""
    f = sp.lambdify(sp.Symbol("x", real=True), drawable(expr, ["x"]), "numpy")
    xs = np.linspace(x_range[0], x_range[1], n)
    with np.errstate(all="ignore"):
        ys = np.broadcast_to(np.asarray(f(xs), dtype=float), xs.shape)
    return [[float(x), float(y)] for x, y in zip(xs, ys) if np.isfinite(y)]


def video_errors(data: dict) -> list[str]:
    """What the template's own parameters need beyond their types: a function_plot's curve can be drawn, and its marks are on it."""
    p = data["params"]
    if data["template"] != "function_plot":
        return []
    lo, hi = p["x_range"]
    try:
        points = curve(p["expr"], p["x_range"]) if lo < hi else []
    except Exception as e:
        return [f"expression does not parse: {e}"]
    if len(points) < 20:
        return ["function_plot: expr must be defined on most of x_range (x_range [low, high] with low < high)"]
    return [f"function_plot: the mark at x={m['x']} is outside x_range or where expr is not defined" for m in p["marks"]
            if not lo <= m["x"] <= hi or not curve(p["expr"], (m["x"], m["x"]), 1)][:1]


def two_variable(expr: str) -> sp.Expr:
    return drawable(expr, ["x", "y"])


def blank_errors(blanks: list[dict], template: str, language: str) -> list[str]:
    """Gaps numbered [[1]]..[[n]] one per blank, each blank answerable, and the template with first answers still parses."""
    gaps = {int(n) for n in GAP.findall(template)}
    if gaps != set(range(1, len(blanks) + 1)):
        return [f"the template has gaps {sorted(gaps)} but there are {len(blanks)} blanks; number gaps [[1]]..[[n]], one per blank"]
    errors = [f"blank {i}: an accepted answer is empty" for i, b in enumerate(blanks, 1) if not all(a.strip() for a in b["answers"])]
    for i, b in enumerate(blanks, 1):
        rx = b.get("regex") or ""
        try:
            if m := PY_ONLY_REGEX.search(rx):
                raise re.error(f"{m.group()!r} is Python-only and the app checks with JavaScript; matching is already case-insensitive")
            pattern = re.compile(rx, re.I)
        except re.error as e:
            errors.append(f"blank {i}: regex does not compile: {e}")
            continue
        if rx and not any(pattern.fullmatch(a.strip()) for a in b["answers"]):  # the app tests ^(?:regex)$, case-insensitive
            errors.append(f"blank {i}: the regex {rx!r} matches none of the accepted answers, so it is broken (often an escape "
                          "written twice, \\\\{ for \\{): write one backslash per escape and check it on the answers")
    return errors or syntax_errors(language, GAP.sub(lambda m: blanks[int(m[1]) - 1]["answers"][0], template))


def mermaid_ids(src: str) -> str:
    """The Mermaid source with labels removed, so only node ids and edges are left."""
    unquoted = re.sub(r'"[^"]*"', '""', src)  # first: a quoted label may hold brackets ("collect() [ACTION]")
    return re.sub(r'\[[^\]]*\]|\([^)]*\)|\{[^}]*\}|\|[^|]*\|', " ", unquoted).replace('""', " ")


EDGE = re.compile(r"([\w-]+)\s*(?:-\.+->|--+>|==+>|---)\s*(?=([\w-]+))")
FAN_OUT = re.compile(r"r[ée]pli[cq]|broadcast|diffus|workers?\b|esclaves?\b|slaves?\b|fan.?out", re.I)  # not "each"/"partition": pipelines say those too


def chain_errors(data: dict) -> list[str]:
    """A diagram drawn as one chain (every node one edge in, one out) whose own words say something fans out: the
    primary shard replicated to its replicas was drawn Node 1 -> Node 2 -> Node 3."""
    src = data["mermaid"]
    if not re.match(r"\s*(flowchart|graph)\b", src) or re.search(r"^\s*subgraph\b", src, re.M):  # nodes drawn as boxes holding shards: the path is a route
        return []
    edges = set(EDGE.findall(mermaid_ids(src).split("\n", 1)[-1]))
    nodes = {n for e in edges for n in e}
    outs, ins = collections.Counter(a for a, _ in edges), collections.Counter(b for _, b in edges)
    if len(nodes) < 4 or max(outs.values(), default=0) > 1 or max(ins.values(), default=0) > 1:
        return []
    cue = FAN_OUT.search(data.get("caption", "") + " " + src)
    return [f"the diagram is one chain but its words say \"{cue.group()}\": what fans out should branch (several edges from one "
            "node), not pass through each node in turn"] if cue else []


def step_errors(data: dict) -> list[str]:
    ids, errors = mermaid_ids(data["mermaid"]), []
    for n, st in enumerate(data["steps"], 1):
        errors += [f"step {n}: node {node} is not in the diagram" for node in st["highlight"]
                   if not re.search(rf"(?<![\w-]){re.escape(node)}(?![\w-])", ids)]
        errors += [f"step {n}: there is no edge {a} --> {b} in the diagram" for a, b in st.get("edges", [])
                   if not re.search(rf"(?<![\w-]){re.escape(a)}\s*[-=.ox<]+>?\s*(?:\|[^|]*\|\s*)?{re.escape(b)}(?![\w-])",
                                    re.sub(r"\[[^\]]*\]|\([^)]*\)|\{[^}]*\}", "", data["mermaid"]))]
    return errors


@functools.lru_cache(maxsize=1)
def _lab_image_built() -> bool:
    try:
        return subprocess.run(["docker", "image", "inspect", LAB_IMAGE_TAG], capture_output=True, timeout=30).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def run_errors(src: str) -> list[str]:
    """Runs a Python solution in the Lab image (no network, 20 s): 1 of 1 solutions that executed anything crashed on a shape
    error and nothing noticed. Passes when Docker or the image is missing."""
    if not _lab_image_built():
        return []
    try:
        out = subprocess.run(["docker", "run", "--rm", "-i", "--network", "none", "--memory", "1g", "--pids-limit", "128",
                              LAB_IMAGE_TAG, "timeout", "20", "python", "-I", "-"], input=src, capture_output=True, text=True, timeout=90)
    except (OSError, subprocess.TimeoutExpired):
        return []
    last = (out.stderr.strip().splitlines() or [""])[-1]
    # shortcut: a fragment that leans on its setting passes (spark, X_train: 9 of 24 stored solutions), and so does a server that
    # never returns; upgrade when code exercises carry their own setup code
    if out.returncode in (0, 124) or last.startswith(("NameError", "ModuleNotFoundError", "ImportError", "EOFError", "FileNotFoundError")):
        return []
    return [f"the solution crashes when run: {last[:300]}; fix it (array shapes, names) so it runs from top to bottom"]


KIND_ITEMS = {"tree": (3, 12), "layers": (3, 7), "nesting": (3, 10), "pipeline": (3, 9), "cycle": (3, 8), "state_machine": (2, 8), "fan_out": (3, 10)}
LABEL_MAX, EXPLANATION_MAX = 40, 320


def kind_diagram_errors(data: dict) -> list[str]:
    """A kind_diagram's structure is valid for its kind, within the size limits; the model never gives positions."""
    kind, items = data["kind"], data["items"]
    ids = [i["id"] for i in items]
    known = set(ids)
    low, high = KIND_ITEMS[kind]
    errors = [f"{kind}: {len(ids)} items; use {low} to {high}"] if not low <= len(ids) <= high else []
    if len(known) != len(ids):
        errors.append("item ids must be unique")
    for i in items:
        if not i["id"].strip() or not i["label"].strip():
            errors.append(f"item {i['id']!r} needs an id and a label")
        elif len(i["label"]) > LABEL_MAX or re.search(r"[$\\*`]", i["label"]):
            errors.append(f"label {i['label'][:30]!r}: at most {LABEL_MAX} characters of plain text, no math or Markdown; put the detail in the explanation")
        if not i["explanation"].strip() or len(i["explanation"]) > EXPLANATION_MAX:
            errors.append(f"explanation of {i['id']!r}: one or two sentences, at most {EXPLANATION_MAX} characters")
    unknown = lambda names: sorted({n for n in names if n not in known})  # noqa: E731
    if kind == "tree":
        roots = [i["id"] for i in items if not i["parent"]]
        errors += [f"a tree has exactly one root (an item with no parent); found {len(roots)}"] if len(roots) != 1 else []
        errors += [f"parent {p!r} is not an item" for p in unknown(i["parent"] for i in items if i["parent"])]
        up = {i["id"]: i["parent"] for i in items}
        errors += [f"the parents loop from {i!r}: a tree has no cycle" for i in ids if _loops(up, i)][:1]
    elif kind == "layers":
        layers = {i["layer"] for i in items}
        if None in layers or layers != set(range(len(layers))) or len(layers) < 2:
            errors.append("every item needs a layer: 0 at the top, with no empty layer, over at least 2 layers")
    elif kind == "nesting":
        errors += [f"container {c!r} is not an item" for c in unknown(i["container"] for i in items if i["container"])]
        up = {i["id"]: i["container"] for i in items}
        if not any(up.values()):
            errors.append("nesting shows containment: put `container` on the items inside another")
        else:
            errors += [f"the containers loop from {i!r}: nothing contains itself" for i in ids if _loops(up, i)][:1]
    elif kind in ("pipeline", "cycle"):
        if sorted(data["order"]) != sorted(ids):
            errors.append(f"{kind}: `order` lists every item id exactly once, in order (a single path)")
    elif kind == "fan_out":
        spokes = data["spokes"]
        if data["hub"] not in known or unknown(spokes) or data["hub"] in spokes or len(set(spokes)) != len(spokes):
            errors.append("fan_out: `hub` is an item and `spokes` are other items, each once")
        elif {data["hub"], *spokes} != known:
            errors.append("fan_out: every item is the hub or one of its spokes")
    links = data["links"]
    if kind == "state_machine" and not links:
        errors.append("state_machine: give `links` [[from, to, label]], one per transition")
    if any(not 2 <= len(link) <= 3 for link in links) or unknown(x for link in links for x in link[:2]):
        errors.append("every link is [from, to] or [from, to, label] with ids of items")
    elif kind == "state_machine" and known - {x for link in links for x in link[:2]}:
        errors.append("state_machine: every state has a transition in or out")
    return errors


STEPS = (3, 12)
CAPTION_MAX = 240


def animation_errors(data: dict) -> list[str]:
    """A stepped_animation's steps name items and links that exist (and are present at that step), each with a cited one-sentence caption."""
    items, kind, steps = data["items"], data["kind"], data["steps"]
    ids = [i["id"] for i in items]
    pairs = {tuple(link[:2]) for link in data["links"]}
    if kind in ("pipeline", "cycle"):
        order = data["order"]
        pairs |= {(a, order[(n + 1) % len(order)]) for n, a in enumerate(order) if kind == "cycle" or n + 1 < len(order)}
    elif kind == "tree":
        pairs |= {(i["parent"], i["id"]) for i in items if i["parent"]}
    elif kind == "fan_out":
        pairs |= {(data["hub"], s) for s in data["spokes"]}
    pairs |= {(b, a) for a, b in pairs}
    errors = [f"{len(steps)} steps; use {STEPS[0]} to {STEPS[1]}"] if not STEPS[0] <= len(steps) <= STEPS[1] else []
    first = {}  # the first thing a step does to an item: an item whose first event is `add` is absent at the start
    for st in steps:
        for kindof in ("add", "remove"):
            for i in st[kindof]:
                first.setdefault(i, kindof)
    here = {i for i in ids if first.get(i) != "add"}
    for n, st in enumerate(steps, 1):
        at = f"step {n}"
        if not st["caption"].strip() or len(st["caption"]) > CAPTION_MAX:
            errors.append(f"{at}: a caption of one sentence, at most {CAPTION_MAX} characters")
        named = [*st["highlight"], *st["add"], *st["remove"], *st["labels"]]
        if not (named or st["links"] or st["move"]):
            errors.append(f"{at} changes nothing: highlight, light a link, move the token, add, remove or relabel")
        if unknown := sorted({i for i in named if i not in ids}):
            errors.append(f"{at} names {unknown}, which are not items")
        here |= set(st["add"])
        for pair in [*st["links"], *([st["move"]] if st["move"] else [])]:
            if len(pair) != 2 or tuple(pair) not in pairs:
                errors.append(f"{at}: {pair} is not a link of the diagram; `links` and `move` are [from, to] of a link of its structure")
            elif not set(pair) <= here:
                errors.append(f"{at}: the link {pair} touches an item that is not there yet")
        if gone := sorted(i for i in st["highlight"] if i in ids and i not in here):
            errors.append(f"{at} highlights {gone}, which are not there yet")
        here -= set(st["remove"])
    return errors


def _loops(up: dict, start: str) -> bool:
    """Whether following parents from `start` comes back to it."""
    at = up.get(start)
    for _ in range(len(up)):
        if at is None or at == "":
            return False
        if at == start:
            return True
        at = up.get(at)
    return True


def sentences(text: str) -> int:
    """Sentences in a note, its maths left out (a decimal point or $a.b$ is no full stop)."""
    prose = re.sub(r"\$\$.*?\$\$|\$[^$]*\$|\d+\.\d+", " ", text or "", flags=re.S)
    return len(re.findall(r"[.!?](?=\s|$)", prose.strip())) or (1 if prose.strip() else 0)


def component_errors(component: str, data: dict) -> list[str]:
    """Checks for the Components whose content must work as code, a function of x and y, or a solvable drill."""
    if component == "code":
        return syntax_errors(data["language"], data["code"])
    if component == "code_exercise":
        return syntax_errors(data["language"], data["solution"]) or (
            blank_errors(data["blanks"], data["starter"], data["language"]) if data.get("blanks") else []) or (
            run_errors(data["solution"]) if data["language"].strip().lower() in ("python", "py") else [])
    if component == "fill_blanks":
        # code with gaps and no task is a guessing game; shortcut: a long title is taken to state the task, as older Blocks do
        no_task = data["language"] and len(data.get("task", "")) < 20 and len(data["title"]) < 60
        return blank_errors(data["blanks"], data["template"], data["language"]) + ([
            'a fill_blanks on code needs a "task": what the completed code must do, with every condition a gap depends on '
            "(a date bound, a sort order, scored or not), so each gap can be deduced and not guessed"] if no_task else [])
    if component in ("surface_plot", "optimizer_animation"):
        try:
            f = two_variable(data["expr"])
        except ValueError as e:
            return [str(e)]
        except Exception as e:
            return [f"expression does not parse: {e}"]
        if component == "optimizer_animation":
            derived = [f] + [sp.diff(f, v) for v in sp.symbols("x y", real=True)]
            if any(d.has(*KINKS) for d in derived):
                return ["expr is not differentiable everywhere (abs, sign, max...); the optimizer needs a smooth function"]
    if component == "plot" and len(data["functions"]) > 1 and not all(fn.get("label", "").strip() for fn in data["functions"]):
        return ["the plot draws several curves and some have no label: give every function a label saying which is which"]
    if component == "derivation":
        long = [i + 1 for i, ln in enumerate(data["lines"]) if sentences(ln.get("note", "")) > 2]
        return [f"derivation line {', '.join(map(str, long))}: a gap note is at most two sentences (how this line follows from the one before)"] if long else []
    if component == "step_diagram":
        return step_errors(data) + chain_errors(data)
    if component == "diagram":
        return chain_errors(data) + size_errors(data)
    if component == "kind_diagram":
        return kind_diagram_errors(data)
    if component == "stepped_animation":
        return kind_diagram_errors(data) or animation_errors(data)
    if component == "video":
        return video_errors(data)
    return []


def flow_nodes(src: str) -> set[str]:
    """The node ids of a Mermaid flowchart."""
    ids = set(re.findall(r"(?m)(?:^|[;&>-])\s*([A-Za-z_][\w-]*)\s*(?=[\[({>]|-|$|;|&|:::)", mermaid_ids(src.split("\n", 1)[-1])))
    return ids - {"subgraph", "end", "classDef", "class", "style", "linkStyle", "direction", "click"}


def size_errors(data: dict) -> list[str]:
    """learning-design.md: a diagram relates 4 to 9 elements. Fewer says what a sentence says; more is read in pieces.
    A diagram with containers (subgraphs) redraws a slide's figure and keeps its size."""
    src = data["mermaid"]
    if not re.match(r"\s*(flowchart|graph)\b", src) or re.search(r"^\s*subgraph\b", src, re.M):
        return []
    edges = set(EDGE.findall(mermaid_ids(src).split("\n", 1)[-1]))
    n = len(flow_nodes(src) | {x for e in edges for x in e})
    if n < 4 and len(edges) < n:  # a chain of 2-3 boxes; a dense small graph (a 3-state Markov chain) earns its place
        return [f"the diagram has only {n} elements: say it in a sentence (a prose Block) instead, or draw at least 4 related ones"]
    return [f"the diagram has {n} nodes: keep to 9 at most; split it in two diagrams or walk it as a step_diagram"] if n > 9 else []


def schema_errors(schema: dict, data: dict) -> list[str]:
    try:
        jsonschema.validate(data, schema)
        return []
    except jsonschema.ValidationError as e:
        return [f"{'.'.join(map(str, e.absolute_path)) or 'data'}: {e.message}"]
    except jsonschema.SchemaError as e:
        return [f"the Component's schema is invalid: {e.message}"]


def check_blocks(raw: list[dict], sources: dict[str, int], extra: dict[str, dict] | None = None) -> tuple[list[dict], list[list[str]]]:
    """Validates and normalises Blocks. Returns (blocks, errors per Block); sources maps name -> page count,
    extra maps a model-made Component's name to its JSON Schema."""
    blocks, errors = [], []
    for item in raw:
        errs: list[str] = []
        while isinstance(item, dict) and "component" not in item and isinstance(item.get("block"), dict):
            item = item["block"]  # the model sometimes wraps the Block in {"block": ...}
        try:
            draft = BlockDraft.model_validate(item | {"data": heal_text(item.get("data") or {})} if isinstance(item, dict) else item)
        except Exception as e:
            blocks.append({"component": str(item.get("component", "?")), "data": item.get("data") or {}, "citations": [],
                           "origin": "model_added"})
            errors.append([f"not a Block: {e}"])
            continue
        if extra and draft.component in extra:
            data, errs = draft.data, schema_errors(extra[draft.component], draft.data)
        else:
            data, errs = validate_data(draft.component, draft.data)
        for c in draft.citations:  # a model types the plain apostrophe where the file name has the curly one
            c.source = next((k for k in sources if k.replace("’", "'") == c.source.replace("’", "'")), c.source)
        block = {"component": draft.component, "data": data, "citations": [c.model_dump() for c in draft.citations], "origin": draft.origin,
                 **({"exam_types": draft.exam_types} if draft.exam_types else {}), **({"tests": draft.tests} if draft.tests else {})}
        for c in draft.citations:
            if not 1 <= c.page <= sources.get(c.source, 0):
                errs.append(f"citation to {c.source} page {c.page} does not exist")
        if draft.origin == "from_source" and not draft.citations:
            errs.append("a From source Block needs at least one Citation")
        if not errs and draft.component in ("kind_diagram", "stepped_animation"):
            for item in [*data["items"], *data.get("steps", [])]:  # an item's or step's page is a Citation of the Block too: the page link, the grounding judge
                cite = item["cite"]
                cite["source"] = next((k for k in sources if k.replace("’", "'") == cite["source"].replace("’", "'")), cite["source"])
                if not 1 <= cite["page"] <= sources.get(cite["source"], 0):
                    errs.append(f"{'item ' + repr(item['id']) if 'id' in item else 'a step'} cites {cite['source']} page {cite['page']}, which does not exist")
                elif not any((c["source"], c["page"]) == (cite["source"], cite["page"]) for c in block["citations"]):
                    block["citations"].append(cite | {"quote": ""})
        if not errs and draft.component in CATALOGUE:
            if draft.component == "quiz":
                errs += quiz_errors(data)
            errs += claim_errors(data.get("claims", []))
            errs += expr_errors(draft.component, data)
            errs += component_errors(draft.component, data)
            errs += ascii_math_errors(data)
            if m := CJK.search(json.dumps(data, ensure_ascii=False)):  # Qwen slips into Chinese mid-sentence
                errs.append(f"Chinese/Japanese/Korean text {m.group()!r}: write it in the course's language")
            if m := SECOND_THOUGHTS.search(json.dumps(data, ensure_ascii=False)):
                errs.append(f"the text argues with itself ({m.group()!r}): work the answer out first, then write only the final "
                            "reasoning, with the marked answer and every number agreeing with it")
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
