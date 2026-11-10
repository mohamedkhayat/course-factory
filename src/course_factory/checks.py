"""Checks every generated Block must pass (#13): structure, citations, math and diagram rendering, quiz sanity,
sympy-verified claims. Also computes the numbers the app owns (Iteration Table rows)."""

import ast
import collections
import json
import jsonschema
import re
import subprocess
from pathlib import Path

import numpy as np
import sympy as sp
import yaml
from sympy.parsing.sympy_parser import parse_expr, standard_transformations, implicit_multiplication_application, convert_xor

from .catalogue import CATALOGUE, BlockDraft, validate_data
from .pi_step import LATEX_WORDS

WEB_DIR = Path(__file__).resolve().parents[2] / "web"
MATH_RE = re.compile(r"\$\$(.+?)\$\$|\$(.+?)\$", re.S)
NOT_MARKDOWN = {"mermaid", "code", "expr", "f", "latex", "language", "source", "template", "starter", "solution", "command",
                "output", "answers", "highlight", "shell"}
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
    diagrams = [{"id": i, "src": b["data"]["mermaid"]} for i, b in enumerate(blocks) if b["component"] in ("diagram", "step_diagram")]
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
    return errs


CATCH_ALL = re.compile(r"\b(all|none) of the above\b|toutes les r[ée]ponses|aucune (de ces|des) r[ée]ponses", re.I)
LABEL = re.compile(r'\["?([^\]"]*)"?\]|\("?([^)"]*)"?\)|\{"?([^}"]*)"?\}')


def block_warnings(block: dict) -> list[str]:
    """Item-writing and readability heuristics: shown on the Block, never block it."""
    data, out = block["data"], []
    if block["component"] == "quiz":
        qs = [q for q in data.get("questions", []) if len(q["options"]) > 1 and len(q["correct"]) == 1]
        longest = [len(q["options"][q["correct"][0]]) > max(len(o) for i, o in enumerate(q["options"]) if i != q["correct"][0])
                   for q in qs]
        if len(longest) >= 3 and all(longest):
            out.append("quiz cue: the right option is the longest in every question; make wrong options as long and as specific")
    if block["component"] in ("diagram", "step_diagram") and re.match(r"\s*(flowchart|graph)\b", src := data.get("mermaid", "")):
        body = src.split("\n", 1)[-1]
        ids = set(re.findall(r"(?m)(?:^|[;&>-])\s*([A-Za-z_][\w-]*)\s*(?=[\[({>]|-|$|;|&|:::)", mermaid_ids(body)))
        ids -= {"subgraph", "end", "classDef", "class", "style", "linkStyle", "direction", "click"}
        if len(ids) > 9 and block["component"] == "diagram":  # a step_diagram already shows it a stage at a time
            out.append(f"diagram size: {len(ids)} nodes; keep to 9 at most, split it or walk it as a step_diagram")
        long = [t for t in (next(g for g in m if g) for m in LABEL.findall(body) if any(m))
                if len(re.findall(r"[^\W\d_]{2,}", re.sub(r"\$[^$]*\$|<[^>]+>", " ", t))) > 6]  # words, not symbols
        if long:
            out.append(f"diagram size: labels of 2-4 words read at a glance; shorten {long[0]!r} and put the detail in the text")
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
    if d == 0:
        return True
    if d.is_number and (got.has(sp.Float) or want.has(sp.Float)):
        return abs(float(d)) <= FLOAT_TOLERANCE * max(1.0, abs(float(want)))
    return False


def claim_errors(claims: list[dict]) -> list[str]:
    """Only a claim sympy proves wrong is an error; one it cannot read checks nothing and is skipped."""
    errs = []
    for c in claims:
        try:
            op, names = c["op"], c["vars"]
            if op != "equal" and not names or op == "grad" and isinstance(c["expected"], list) and len(c["expected"]) != len(names):
                names = sorted((str(s) for s in parse(c["expr"]).free_symbols), key=natural)
            f, want = parse(c["expr"], names), value(c["expected"], names)
            syms = [sp.Symbol(n, real=True) for n in names]
            if op == "grad" and not isinstance(want, list):
                op = "diff"  # one partial derivative written as a gradient
            if op == "equal":
                got = f
            elif op == "diff":
                got = sp.diff(f, syms[0])
            elif op == "grad":
                got = [sp.diff(f, s) for s in syms]
            else:
                got = sp.hessian(f, syms)
                if isinstance(want, list) and len(want) == len(syms) ** 2 and not isinstance(want[0], list):
                    want = [want[i:i + len(syms)] for i in range(0, len(want), len(syms))]  # flat "a, b, c, d"
            ok = same(canon(got), canon(want))
        except Exception:
            continue
        if not ok:
            errs.append(f"sympy: {c['op']} of {c['expr']} is {canon(got)}, not {c['expected']}")
    return errs


TEXT_FIXES = [
    (re.compile(r"\\n(?![A-Za-z])"), "\n"),  # a newline the model escaped twice
    (re.compile(r"\$\$\$\$"), "$$\n$$"),  # two display formulas run together
    (re.compile(r"(\\text\{[^{}]*?)(\\[A-Za-z]+)([^{}]*\})"), r"\1}\2\\text{\3"),  # math command inside \text{}
]
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


ASCII_MATH = re.compile(r"\bsqrt\(|\bexp\(|(?<!\*\*)[\w)]\*\*(?:[\d(]|[A-Za-z](?!\w))|\w\^\(")  # x**2, e**x; not **D**éveloppeurs (bold)
CODE_SPAN = re.compile(r"```.*?```|`[^`]*`", re.S)
# shortcut: assumes French/English courses; a course taught in Chinese, Japanese or Korean would need this off
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
    return []


DRAWABLE = {"exp", "log", "sqrt", "sin", "cos", "tan", "asin", "acos", "atan", "sinh", "cosh", "tanh", "abs", "pi", "E"}
KINKS = (sp.Abs, sp.sign, sp.Heaviside, sp.Piecewise, sp.floor, sp.ceiling, sp.Max, sp.Min, sp.DiracDelta)


def drawable(expr: str, names: list[str]) -> sp.Expr:
    """Parses expr with sympy and refuses names the browser's plotter (mathjs) does not know the same way."""
    if unknown := set(re.findall(r"[A-Za-z_]\w*", expr)) - DRAWABLE - set(names):
        raise ValueError(f"expr must be a function of {' and '.join(names)} only, using {', '.join(sorted(DRAWABLE))}; "
                         f"it uses {sorted(unknown)}")
    return parse(expr, names)


def two_variable(expr: str) -> sp.Expr:
    return drawable(expr, ["x", "y"])


def blank_errors(blanks: list[dict], template: str, language: str) -> list[str]:
    """Gaps numbered [[1]]..[[n]] one per blank, each blank answerable, and the template with first answers still parses."""
    gaps = {int(n) for n in GAP.findall(template)}
    if gaps != set(range(1, len(blanks) + 1)):
        return [f"the template has gaps {sorted(gaps)} but there are {len(blanks)} blanks; number gaps [[1]]..[[n]], one per blank"]
    errors = [f"blank {i}: an accepted answer is empty" for i, b in enumerate(blanks, 1) if not all(a.strip() for a in b["answers"])]
    for i, b in enumerate(blanks, 1):
        try:
            re.compile(b.get("regex") or "")
        except re.error as e:
            errors.append(f"blank {i}: regex does not compile: {e}")
    return errors or syntax_errors(language, GAP.sub(lambda m: blanks[int(m[1]) - 1]["answers"][0], template))


def mermaid_ids(src: str) -> str:
    """The Mermaid source with labels removed, so only node ids and edges are left."""
    return re.sub(r'"[^"]*"|\[[^\]]*\]|\([^)]*\)|\{[^}]*\}|\|[^|]*\|', " ", src)


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


def component_errors(component: str, data: dict) -> list[str]:
    """Checks for the Components whose content must work as code, a function of x and y, or a solvable drill."""
    if component == "code":
        return syntax_errors(data["language"], data["code"])
    if component == "code_exercise":
        return syntax_errors(data["language"], data["solution"]) or (
            blank_errors(data["blanks"], data["starter"], data["language"]) if data.get("blanks") else [])
    if component == "fill_blanks":
        return blank_errors(data["blanks"], data["template"], data["language"])
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
    if component == "step_diagram":
        return step_errors(data) + chain_errors(data)
    if component == "diagram":
        return chain_errors(data)
    return []


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
        block = {"component": draft.component, "data": data, "citations": [c.model_dump() for c in draft.citations], "origin": draft.origin,
                 **({"exam_types": draft.exam_types} if draft.exam_types else {}), **({"tests": draft.tests} if draft.tests else {})}
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
            errs += component_errors(draft.component, data)
            errs += ascii_math_errors(data)
            if m := CJK.search(json.dumps(data, ensure_ascii=False)):  # Qwen slips into Chinese mid-sentence
                errs.append(f"Chinese/Japanese/Korean text {m.group()!r}: write it in the course's language")
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
