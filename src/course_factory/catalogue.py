"""The v1 Catalogue: the Components content may use, each with the shape of Block data it accepts.

Text fields are Markdown with $inline$ / $$display$$ math. Fields named `latex` are bare LaTeX.
"""

from typing import Literal

from pydantic import BaseModel, Field, ValidationError, model_validator

Md = str


class SympyClaim(BaseModel):
    """A computable claim the app verifies with sympy. Expressions use sympy syntax (x**2, exp(x), x1, x2)."""

    op: Literal["equal", "diff", "grad", "hessian"]
    expr: str
    vars: list[str] = []
    expected: str | list[str] | list[list[str]]


class TheoremBox(BaseModel):
    kind: Literal["definition", "theorem", "proposition", "lemma", "corollary", "property"]
    title: str = ""
    statement: Md
    proof: Md = ""


class WorkedExample(BaseModel):
    title: str
    problem: Md
    steps: list[Md] = Field(min_length=1)
    answer: Md
    claims: list[SympyClaim] = []


class Exercise(BaseModel):
    title: str
    statement: Md
    hints: list[Md] = []
    correction: Md
    claims: list[SympyClaim] = []


class QuizQuestion(BaseModel):
    prompt: Md
    options: list[Md] = Field(min_length=2)
    correct: list[int] = Field(min_length=1)
    explanation: Md
    multiple: bool = False


class Quiz(BaseModel):
    questions: list[QuizQuestion] = Field(min_length=1)


class KeyFormula(BaseModel):
    name: str
    latex: str
    meaning: Md
    claims: list[SympyClaim] = []


class Callout(BaseModel):
    tone: Literal["tip", "warning", "exam", "note"]
    text: Md


class Algorithm(BaseModel):
    name: str
    inputs: Md
    steps: list[Md] = Field(min_length=1)
    output: Md


class IterationTable(BaseModel):
    """The model states the problem; the app computes the rows."""

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
    title: str = ""
    functions: list[PlotFunction] = Field(min_length=1)
    x_range: tuple[float, float] = (-5.0, 5.0)


class ExplorerParam(BaseModel):
    name: str
    min: float
    max: float
    value: float


class Explorer(BaseModel):
    title: str
    expr: str
    params: list[ExplorerParam] = Field(min_length=1)
    x_range: tuple[float, float] = (-5.0, 5.0)
    explanation: Md = ""


class Diagram(BaseModel):
    mermaid: str
    caption: Md = ""


class Figure(BaseModel):
    source: str
    page: int
    caption: Md = ""


class Table(BaseModel):
    headers: list[str] = Field(min_length=1)
    rows: list[list[Md]]
    caption: Md = ""


class Code(BaseModel):
    language: str = "python"
    code: str
    caption: Md = ""


class Prose(BaseModel):
    markdown: Md


CATALOGUE: dict[str, type[BaseModel]] = {
    "theorem_box": TheoremBox, "worked_example": WorkedExample, "exercise": Exercise, "quiz": Quiz,
    "key_formula": KeyFormula, "callout": Callout, "algorithm": Algorithm, "iteration_table": IterationTable,
    "plot": Plot, "explorer": Explorer, "diagram": Diagram, "figure": Figure, "table": Table, "code": Code,
    "prose": Prose,
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
    return "\n".join(lines)


def _type_name(t) -> str:
    s = str(t).replace("typing.", "").replace("course_factory.catalogue.", "")
    return s.replace("<class '", "").replace("'>", "")
