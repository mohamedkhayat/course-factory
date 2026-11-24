"""The Video templates: the parameters the model fills in (typed, checked like other Block data) and how many scenes each makes.
The Manim scene code is in video_workers/scenes.py and runs only in the Manim environment. The model never writes Manim code.
Change a template's scene code and its VERSION here, so Videos made with the old one render again."""
import re
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, Field

# Text on screen is plain: maths goes in a `latex` field, or as $..$ in the narration
PLAIN = re.compile(r"[$\\*`{}^_]")


def plain(v: str) -> str:
    if PLAIN.search(v):
        raise ValueError(f"{v[:30]!r}: plain text only (no $, backslash, *, backquote, braces, ^ or _); maths goes in a latex field")
    return v.strip()


Text = Annotated[str, AfterValidator(plain)]


class SectionLine(BaseModel):
    title: Text = Field(max_length=60)
    line: Text = Field("", max_length=110)  # what this Section adds, one short line


class ChapterOverview(BaseModel):
    title: Text = Field(max_length=70)
    points: list[Text] = Field(min_length=1, max_length=4)  # the big picture, each at most 90 characters
    sections: list[SectionLine] = Field(min_length=1, max_length=8)  # the Chapter's Sections, in order


class Record(BaseModel):
    key: Text = Field(min_length=1, max_length=10)  # records with the same key meet after a shuffle
    value: Text = Field("", max_length=10)


class PartitionFlow(BaseModel):
    title: Text = Field(max_length=70)
    partitions: list[list[Record]] = Field(min_length=2, max_length=4)  # each partition's records, 1 to 5 of them
    narrow: Text = Field(max_length=50)  # a narrow transformation by name: map, filter
    wide: Text = Field(max_length=50)  # a wide one: groupByKey, reduceByKey, join
    cache: bool = False  # one more scene: the result is cached and the next action reuses it


class EquationStep(BaseModel):
    latex: str = Field(min_length=1, max_length=160)
    note: Text = Field("", max_length=70)  # what was done to reach this line: "subtract 3 from both sides"


class EquationTransform(BaseModel):
    title: Text = Field("", max_length=70)
    steps: list[EquationStep] = Field(min_length=2, max_length=7)  # the first is the equation as given


class Mark(BaseModel):
    x: float
    label: Text = Field(max_length=40)


class FunctionPlot(BaseModel):
    title: Text = Field("", max_length=70)
    expr: str = Field(max_length=80)  # sympy syntax in x, as in a plot Block
    latex: str = Field("", max_length=80)  # the function as written ("f(x)=x^2"), shown on the curve
    x_range: tuple[float, float] = (-3.0, 3.0)
    marks: list[Mark] = Field([], max_length=4)  # points to point out, one scene each


class Template:
    def __init__(self, model: type[BaseModel], scenes, version: int, doc: str):
        self.model, self.scenes, self.version, self.doc = model, scenes, version, doc


TEMPLATES: dict[str, Template] = {
    "chapter_overview": Template(ChapterOverview, lambda p: 1 + len(p["sections"]), 2,
                                 "the Chapter's big picture, then its Sections one scene each (the app makes this one: one per Chapter)"),
    "partition_flow": Template(PartitionFlow, lambda p: 4 if p["cache"] else 3, 1,
                               "records in partitions (title, partitions [[{key, value}]] of 2-4, narrow, wide, cache); scenes: the data, the narrow step, the wide step with its shuffle, and with cache true the cached result"),
    "equation_transform": Template(EquationTransform, lambda p: len(p["steps"]), 1,
                                   "an equation transformed line by line (title, steps [{latex, note}], the first is the equation); one scene per step"),
    "function_plot": Template(FunctionPlot, lambda p: 2 + len(p["marks"]), 1,
                              "a function and its curve (title, expr in x, latex, x_range, marks [{x, label}]); scenes: the axes, the curve, then one per mark"),
}
NAMES = tuple(TEMPLATES)
Name = Literal[NAMES]  # type: ignore[valid-type]


def check_params(template: str, params: dict) -> tuple[dict, int]:
    """The normalised parameters and the number of scenes (so the narration has one script each); ValueError with every problem."""
    from pydantic import ValidationError
    try:
        data = TEMPLATES[template].model.model_validate(params).model_dump()
    except ValidationError as e:
        raise ValueError("; ".join(f"{template} {'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()))
    if template == "partition_flow" and any(not 1 <= len(p) <= 5 for p in data["partitions"]):
        raise ValueError("partition_flow: each partition holds 1 to 5 records")
    return data, TEMPLATES[template].scenes(data)


def describe() -> str:
    return " ".join(f"{n}: {t.doc}." for n, t in TEMPLATES.items())
