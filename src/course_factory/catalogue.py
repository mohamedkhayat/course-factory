"""The v1 Catalogue: the Components content may use, each with the shape of Block data it accepts.

Text fields are Markdown with $inline$ / $$display$$ math. Fields named `latex` are bare LaTeX.
"""

import re
from typing import Annotated, Literal

from pydantic import AliasChoices, BaseModel, BeforeValidator, Field, ValidationError, model_validator

Md = str


class SympyClaim(BaseModel):
    """A computable claim the app verifies with sympy. Expressions use sympy syntax (x**2, exp(x), x1, x2)."""

    op: Literal["equal", "diff", "grad", "hessian"]
    expr: str
    vars: list[str] = []
    expected: str | list[str] | list[list[str]]


OPS = {"equal": "equal", "eq": "equal", "equals": "equal", "=": "equal", "==": "equal", "value": "equal", "evaluate": "equal",
       "simplify": "equal", "diff": "diff", "derivative": "diff", "d": "diff", "grad": "grad", "gradient": "grad",
       "hessian": "hessian", "hess": "hessian"}
ANSWER_KEYS = {"expected": None, "derivative": "diff", "gradient": "grad", "hessian": "hessian", "value": "equal",
               "result": "equal", "equals": "equal"}


def _strings(v):
    return [_strings(x) for x in v] if isinstance(v, list) else str(v)


def heal_claim(raw) -> dict | None:
    """Coerces the claim shapes the model writes into a SympyClaim; None for one sympy cannot check."""
    if not isinstance(raw, dict) or not isinstance(raw.get("expr"), str):
        return None
    c = dict(raw)
    key = next((k for k in ANSWER_KEYS if k in c), None)
    if key is None and "==" in c["expr"]:  # "lhs == rhs" written in expr
        c["expr"], c["expected"], c["op"] = *c["expr"].split("==", 1), "equal"
    elif key not in (None, "expected"):
        c["expected"] = c.pop(key)
        c.setdefault("op", ANSWER_KEYS[key])
    if "expected" not in c:
        return None
    op = OPS.get(str(c.get("op", "equal")).strip().lower())
    if op is None:
        return None  # lt, ge...: sympy cannot decide these without a domain
    if op == "diff" and "diff(" in c["expr"]:
        op = "equal"  # the derivative is already taken in expr
    names = c.get("vars", c.get("var", []))
    names = [n.strip() for n in names.split(",")] if isinstance(names, str) else names
    return {"op": op, "expr": c["expr"].strip(), "vars": [str(n) for n in names if str(n).strip()], "expected": _strings(c["expected"])}


Claims = Annotated[list[SympyClaim], BeforeValidator(lambda v: [c for c in map(heal_claim, v) if c] if isinstance(v, list) else v)]


class TheoremBox(BaseModel):
    """Use when stating a definition, theorem or property formally, with an optional proof."""

    kind: Literal["definition", "theorem", "proposition", "lemma", "corollary", "property"]
    title: str = ""
    statement: Md
    proof: Annotated[Md, BeforeValidator(lambda v: v or "")] = ""  # the model writes null for no proof


class WorkedExample(BaseModel):
    """Use when showing how to solve a typical problem, step by step."""

    title: str
    problem: Md
    steps: list[Md] = Field(min_length=1)
    answer: Md
    claims: Claims = []


class Exercise(BaseModel):
    """Use when the learner should solve a problem; mode "hand" for paper calculations, with `steps` revealed one by one and a self-mark; `minutes` sets a time limit."""

    title: str
    statement: Md
    hints: list[Md] = []
    correction: Md
    mode: Literal["written", "hand"] = "written"
    steps: list[Md] = []
    minutes: int = Field(0, ge=0, le=240)  # a time limit, as in the exam for its points; 0 = untimed
    claims: Claims = []


class QuizQuestion(BaseModel):
    prompt: Md = Field(validation_alias=AliasChoices("prompt", "question"))
    options: list[Md] = Field(min_length=2)
    correct: Annotated[list[int], BeforeValidator(lambda v: [int(v)] if isinstance(v, int) or isinstance(v, str) and v.strip().isdigit() else v)] = Field(
        min_length=1, validation_alias=AliasChoices("correct", "correct_index", "answer"))  # the model writes one answer as a bare index
    explanation: Md
    explanations: list[Md] = []  # optional: why each option is right or wrong, in option order
    multiple: bool = False

    @model_validator(mode="before")
    @classmethod
    def explanation_from_options(cls, data):
        """The model often explains each option but not the question: the right option's explanation is the answer's."""
        if not isinstance(data, dict):
            return data
        opts = data.get("options")
        if isinstance(opts, list) and opts and all(isinstance(o, dict) for o in opts):  # [{text, correct, explanation}]
            data = data | {"options": [o.get("text") or o.get("option") or "" for o in opts],
                           "explanations": [o.get("explanation") or o.get("feedback") or "" for o in opts]}
            if "correct" not in data or isinstance(data["correct"], bool):
                data["correct"] = [i for i, o in enumerate(opts) if o.get("correct")]
        if isinstance(data.get("explanation"), list):  # one per option, under the singular name
            data = data | {"explanations": data["explanation"], "explanation": ""}
        if not data.get("explanation") and isinstance(data.get("explanations"), list):
            right = next((data[k] for k in ("correct", "correct_index", "answer") if k in data), None)
            right = right[0] if isinstance(right, list) and right else right
            if isinstance(right, int) and 0 <= right < len(data["explanations"]):
                data = data | {"explanation": data["explanations"][right]}
        return data


class Quiz(BaseModel):
    """Use when checking a definition, a distinction or a common mistake with multiple choice; explain each option."""

    questions: list[QuizQuestion] = Field(min_length=1)


class KeyFormula(BaseModel):
    """Use when one formula must be remembered: name it and say what each part means."""

    name: str
    latex: str
    meaning: Md
    claims: Claims = []


class Callout(BaseModel):
    """Use when a tip, pitfall, exam note or remark deserves to stand out."""

    tone: Literal["tip", "warning", "exam", "note"]
    text: Md


class Algorithm(BaseModel):
    """Use when presenting an algorithm, procedure or exam Method as numbered steps with inputs and output; `when` says what in a question triggers it."""

    name: str
    when: Md = ""  # the trigger: what in a question says to use this method
    inputs: Md
    steps: list[Md] = Field(min_length=1)
    output: Md


class IterationTable(BaseModel):
    """Use when running an iterative method by hand on f; state the problem, the app computes the rows."""

    method: Literal["gradient", "newton"]
    f: str
    vars: list[str] = Field(min_length=1)
    x0: list[float]
    step: float = 0.1
    iterations: int = Field(5, ge=1, le=50)
    caption: Md = ""
    rows: list[dict] = []

    @model_validator(mode="after")
    def x0_matches_vars(self):
        if len(self.x0) != len(self.vars):
            raise ValueError("x0 must have one value per variable")
        return self


class PlotFunction(BaseModel):
    expr: str
    label: str = ""


class Plot(BaseModel):
    """Use when a function of one variable should be seen: shape, minima, comparisons."""

    title: str = ""
    functions: list[PlotFunction] = Field(min_length=1)
    x_range: tuple[float, float] = (-5.0, 5.0)


class ExplorerParam(BaseModel):
    name: str
    min: float
    max: float
    value: float


class Explorer(BaseModel):
    """Use when a parameter's effect on a function of x should be explored with sliders."""

    title: str
    expr: str
    params: list[ExplorerParam] = Field(min_length=1)
    x_range: tuple[float, float] = (-5.0, 5.0)
    explanation: Md = ""


MERMAID_WORDS = {"end", "graph", "flowchart", "subgraph", "style", "class", "classdef", "click", "linkstyle", "direction", "default"}


def node_id(raw: str) -> str:
    """A node id Mermaid accepts: word characters only, never a keyword such as "end"."""
    s = re.sub(r"\W", "_", raw.strip()) or "n"
    return "n_" + s if s.lower() in MERMAID_WORDS or s[0].isdigit() else s


def mermaid_label(text: str) -> str:
    s = text.replace('"', "#quot;").replace("\n", "<br/>")
    return re.sub(r"^(\s*)(\d+)\.(?=\s)|^(\s*)([-+*])(?=\s)",  # a label starting like a Markdown list fails to render
                  lambda m: f"{m[1]}{m[2]}#46;" if m[2] else f"{m[3]}#{ord(m[4])};", s)


def compile_mermaid(direction: str, nodes: dict[str, str], edges: list[list[str]]) -> str:
    """Mermaid from nodes and edges, so the model never writes Mermaid syntax (quoting, escapes, keywords) itself."""
    lines = [f"flowchart {direction}"] + [f'  {node_id(k)}["{mermaid_label(v)}"]' for k, v in nodes.items()]
    for e in edges:
        a, b = node_id(e[0]), node_id(e[1])
        lines.append(f'  {a} -->|"{mermaid_label(e[2])}"| {b}' if len(e) > 2 and e[2] else f"  {a} --> {b}")
    return "\n".join(lines)


class Structured(BaseModel):
    """nodes/edges compile to `mermaid`; afterwards only `mermaid` is kept, so an owner edit of it is never overwritten."""

    nodes: dict[str, Md] = {}
    edges: list[list[str]] = []
    direction: Literal["TD", "LR"] = "TD"
    mermaid: str = ""

    @model_validator(mode="after")
    def compiled(self):
        if self.nodes:
            if any(not 2 <= len(e) <= 3 for e in self.edges):
                raise ValueError("each edge is [from, to] or [from, to, label]")
            missing = sorted({x for e in self.edges for x in e[:2]} - set(self.nodes))
            if missing:
                raise ValueError(f"edges use node ids that are not in nodes: {', '.join(missing)}")
            self.mermaid, self.nodes, self.edges = compile_mermaid(self.direction, self.nodes, self.edges), {}, []
        elif not self.mermaid.strip():
            raise ValueError("give nodes {id: label} and edges [[from, to], [from, to, label]]")
        return self


class Diagram(Structured):
    """Use when showing a flow, pipeline or relations: give nodes {id: label} and edges [[from, to], [from, to, label]]; code draws it. Write raw `mermaid` only for kinds nodes and edges cannot express (sequence, class, state)."""

    caption: Md = ""


class Figure(BaseModel):
    """Use when a figure on a page of the material says it best."""

    source: str
    page: int
    caption: Md = ""


class Table(BaseModel):
    """Use when comparing options or summarising facts side by side."""

    headers: list[str] = Field(min_length=1)
    rows: list[list[Md]]
    caption: Md = ""


class Code(BaseModel):
    """Use when showing a code or config listing to read, not to complete."""

    language: str = "python"
    code: str
    caption: Md = ""


class Prose(BaseModel):
    """Use to explain in connected paragraphs: what an idea is, why it is needed, how it links to the last one."""

    markdown: Md


class Intuition(BaseModel):
    """Use before a formal statement: the idea in plain words, an optional analogy, and where the analogy stops being true."""

    idea: Md
    analogy: Md = ""
    limits: Md = ""  # where the analogy breaks: a wrong analogy taught as true is worse than none


class Misconception(BaseModel):
    """Use for a Section's main mistake (from the plan's misconceptions): what students wrongly believe, why it is wrong, the correct idea."""

    belief: Md
    why_wrong: Md
    correct: Md


class Recap(BaseModel):
    """Use as the Section's last Block: its 3-5 takeaways and what the learner can now do."""

    takeaways: list[Md] = Field(min_length=2)
    can_do: list[Md] = []


class ExplainBack(BaseModel):
    """Use to check an understand objective: the learner explains a Concept in their own words, graded against a rubric of the 2-5 points a good explanation makes."""

    concept: str
    prompt: Md
    rubric: list[Md] = Field(min_length=1)
    model_answer: Md


Range = tuple[float, float]


class Blank(BaseModel):
    answers: Annotated[list[str], BeforeValidator(lambda v: [v] if isinstance(v, str) else v)] = Field(
        min_length=1, validation_alias=AliasChoices("answers", "accepted", "answer"))
    regex: str = ""  # also accepted when the whole answer matches, case ignored
    hint: str = ""


class FillBlanks(BaseModel):
    """Use when the learner should recall key terms or syntax: text (language "") or code with gaps [[1]], [[2]]... each with accepted answers. Gaps never inside $math$."""

    title: str
    task: Md = ""  # what the completed code must do, shown above it: the learner picks `gte` over `gt` from this, not by guessing
    language: str = ""
    template: str
    blanks: list[Blank] = Field(min_length=1)
    explanation: Md = ""


class CodeExercise(BaseModel):
    """Use when the learner should write or complete code or config: starter with TODOs (or [[n]] gaps with blanks), hints, graded answer."""

    title: str
    task: Md
    language: str
    starter: str  # with blanks: gaps [[1]], [[2]]... checked by match, no model
    solution: str
    hints: list[Md] = []
    blanks: list[Blank] = []
    rubric: str = ""  # what the model grader must look for


class SurfacePoint(BaseModel):
    x: float
    y: float
    label: str = ""


class SurfacePlot(BaseModel):
    """Use when a function of x and y should be seen: rotatable 3D surface and/or contour map."""

    title: str
    expr: str
    x_range: Range = (-3.0, 3.0)
    y_range: Range = (-3.0, 3.0)
    view: Literal["surface", "contour", "both"] = "both"
    points: list[SurfacePoint] = []
    caption: Md = ""


class OptimizerAnimation(BaseModel):
    """Use when showing how an optimiser (gradient, momentum, newton) moves on f(x, y), animated, with a step-size slider."""

    title: str
    expr: str
    method: Literal["gradient", "momentum", "newton"] = "gradient"
    start: tuple[float, float]
    step: float = Field(0.1, gt=0)
    momentum: float = Field(0.9, ge=0, lt=1)
    iterations: int = Field(30, ge=1, le=200)
    x_range: Range = (-3.0, 3.0)
    y_range: Range = (-3.0, 3.0)
    caption: Md = ""


class DiagramStep(BaseModel):
    @model_validator(mode="before")
    @classmethod
    def flag_highlight(cls, data):  # {"target": "T1", "highlight": true}: the id is in target
        return {k: v for k, v in data.items() if not (k == "highlight" and isinstance(v, bool))} if isinstance(data, dict) else data

    highlight: Annotated[list[str], BeforeValidator(lambda v: [v] if isinstance(v, str) else v)] = Field(
        min_length=1, validation_alias=AliasChoices("highlight", "node", "nodes", "id", "target"))
    edges: list[tuple[str, str]] = []  # [from, to] node ids of edges to light up
    caption: Md


class StepDiagram(Structured):
    """Use when walking through a process one stage at a time: nodes {id: label} and edges [[from, to]] as for diagram, then steps whose highlight lists node ids to light up in order, with captions."""

    steps: list[DiagramStep] = Field(min_length=1)
    caption: Md = ""

    @model_validator(mode="before")
    @classmethod
    def same_ids(cls, data):
        if isinstance(data, dict) and data.get("nodes") and isinstance(data.get("steps"), list):  # highlights name nodes as written
            data = data | {"steps": [st | {"highlight": [node_id(h) for h in st.get("highlight", [])],
                                           "edges": [[node_id(a), node_id(b)] for a, b, *_ in st.get("edges", [])]}
                                     if isinstance(st, dict) else st for st in data["steps"]]}
        return data


class TerminalEntry(BaseModel):
    command: str = Field(validation_alias=AliasChoices("command", "input", "cmd", "text"))
    output: str = ""
    note: Md = Field("", validation_alias=AliasChoices("note", "comment", "description"))


class Terminal(BaseModel):
    """Use when teaching commands: a shell session, one command at a time, with its output and what it does."""

    title: str = ""
    shell: str = "bash"
    entries: list[TerminalEntry] = Field(min_length=1)


CATALOGUE: dict[str, type[BaseModel]] = {
    "theorem_box": TheoremBox, "worked_example": WorkedExample, "exercise": Exercise, "quiz": Quiz,
    "key_formula": KeyFormula, "callout": Callout, "algorithm": Algorithm, "iteration_table": IterationTable,
    "plot": Plot, "explorer": Explorer, "diagram": Diagram, "figure": Figure, "table": Table, "code": Code,
    "prose": Prose, "fill_blanks": FillBlanks, "code_exercise": CodeExercise, "surface_plot": SurfacePlot,
    "optimizer_animation": OptimizerAnimation, "step_diagram": StepDiagram, "terminal": Terminal,
    "intuition": Intuition, "misconception": Misconception, "recap": Recap, "explain_back": ExplainBack,
}


class Citation(BaseModel):
    source: str
    page: int
    quote: str = ""


class BlockDraft(BaseModel):
    component: str
    data: dict
    citations: list[Citation] = []
    origin: Literal["from_source", "model_added"]
    exam_types: list[str] = []  # Cram: the Question Types this Block prepares for
    tests: list[str] = []  # practice: the Concepts it tests, which must be taught by then (#22)

    @model_validator(mode="before")
    @classmethod
    def origin_from_citations(cls, data):
        if isinstance(data, dict) and "origin" not in data:  # the model forgets it: a cited Block is from its source
            data = data | {"origin": "from_source" if data.get("citations") else "model_added"}
        return data


def validate_data(component: str, data: dict, catalogue: dict[str, type[BaseModel]] = CATALOGUE) -> tuple[dict, list[str]]:
    """Returns the normalised data and any schema errors."""
    schema = catalogue.get(component)
    if schema is None:
        return data, [f"unknown Component '{component}'; use one of: {', '.join(catalogue)}"]
    try:
        return schema.model_validate(data).model_dump(), []
    except ValidationError as e:
        return data, [f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors()]


def describe(catalogue: dict[str, type[BaseModel]] = CATALOGUE) -> str:
    """A compact description of every Component's data shape, for prompts."""
    lines = []
    for name, schema in catalogue.items():
        fields = ", ".join(f"{f}: {_type_name(info.annotation)}{'' if info.is_required() else '?'}"
                           for f, info in schema.model_fields.items() if f != "rows" or name != "iteration_table")
        doc = (schema.__doc__ or "").strip().split("\n")[0]
        lines.append(f"- {name} {{{fields}}}" + (f"  ({doc})" if doc else ""))
    text = "\n".join(lines)
    # the shapes inside the lists (QuizQuestion, Blank...): unnamed, the model guesses their fields and the Block goes to repair
    nested = [f"- {n} {{{', '.join(f'{f}: {_type_name(i.annotation)}' + ('' if i.is_required() else '?') for f, i in m.model_fields.items())}}}"
              for n, m in globals().items() if isinstance(m, type) and issubclass(m, BaseModel) and re.search(rf"\b{n}\b", text)]
    return text + ("\nShapes used above:\n" + "\n".join(nested) if nested else "")


def _type_name(t) -> str:
    s = str(t).replace("typing.", "").replace("course_factory.catalogue.", "")
    return s.replace("<class '", "").replace("'>", "")
