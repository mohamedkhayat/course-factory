"""The Chapter plan (#23): before its Sections are written, one Model step plans the whole Chapter (each Section's
Objectives, the misconceptions to target, a practice ramp, and its visual), and plain code holds the plan to the rules in
docs/research/learning-design.md."""

import collections
import json
import re
from typing import Literal

from pydantic import BaseModel, Field

from .pi_step import attach_checks, last_trace_id, run_pi_step
from .progression import PRACTICE, name_stems, stems, strings

Level = Literal["remember", "understand", "apply", "analyse"]
LEVELS = ["remember", "understand", "apply", "analyse"]
Kind = Literal["retrieval", "worked", "faded", "independent", "exam"]
Relation = Literal["process", "hierarchy", "fan_out", "comparison", "cycle", "state", "quantity", "none"]
RAMP = ["worked", "faded", "independent", "exam"]
FITS: dict[str, set[str]] = {  # practice kind -> the Components that can carry it
    "retrieval": {"quiz", "fill_blanks", "explain_back"}, "worked": {"worked_example"}, "faded": {"exercise", "fill_blanks", "code_exercise"},
    "independent": {"exercise", "code_exercise"}, "exam": {"exercise", "code_exercise"}}
DRAWS: dict[str, set[str]] = {  # relation -> the Components that draw it
    "process": {"diagram", "step_diagram"}, "hierarchy": {"diagram"}, "fan_out": {"diagram"}, "comparison": {"table"},
    "cycle": {"diagram", "step_diagram"}, "state": {"diagram", "step_diagram"},
    "quantity": {"plot", "surface_plot", "iteration_table", "optimizer_animation"}}


class Objective(BaseModel):
    id: str
    level: Level
    text: str
    concepts: list[str] = []
    exam_types: list[str] = []


class Misconception(BaseModel):
    id: str
    text: str


class Practice(BaseModel):
    objective: str
    kind: Kind
    component: str


class Visual(BaseModel):
    relation: Relation = "none"
    shows: str = ""
    component: str = ""


class SectionLesson(BaseModel):
    title: str
    objectives: list[Objective] = Field(min_length=1)
    misconceptions: list[Misconception] = []
    practice: list[Practice] = Field(min_length=1)
    visual: Visual = Visual()


class LessonPlan(BaseModel):
    overview: str = ""  # the Chapter's big picture, then what each Section adds in order: shown at the top of the Chapter
    sections: list[SectionLesson] = Field(min_length=1)


def plan_errors(plan: LessonPlan, sections: list[dict], taught: list[str], exam_types: list[str]) -> list[str]:
    """`sections`: the Chapter's Sections in order, {"title", "teaches"}; `taught`: the Concepts taught before the Chapter;
    `exam_types`: the Chapter's Question Type names (Cram)."""
    errors = []
    if [s.title for s in plan.sections] != [s["title"] for s in sections]:
        return [f"plan one entry per Section, in this order, with these exact titles: {json.dumps([s['title'] for s in sections], ensure_ascii=False)}"]
    if len(plan.overview.split()) < 15:
        errors.append("write the overview: the Chapter's big picture in 2-3 sentences, then what each Section adds, in order")
    known = set(taught)
    covered = set()
    for n, (sec, lesson) in enumerate(zip(sections, plan.sections)):
        known |= set(sec["teaches"])
        at = f'Section "{lesson.title}"'
        ids = {o.id for o in lesson.objectives}
        levels = [LEVELS.index(o.level) for o in lesson.objectives]
        if levels != sorted(levels):
            errors.append(f"{at}: order the objectives from the lowest level to the highest (remember, understand, apply, analyse)")
        if n == 0 and levels[0] >= LEVELS.index("apply"):
            errors.append(f"{at} opens the Chapter: start with a remember or understand objective before any {lesson.objectives[0].level}")
        order = [[o.id for o in lesson.objectives].index(p.objective) for p in lesson.practice if p.objective in ids]
        if order != sorted(order):
            errors.append(f"{at}: practise the objectives in their order, so practice goes from easy to hard")
        if lesson.practice[0].kind in ("independent", "exam"):
            errors.append(f"{at}: the first practice is {lesson.practice[0].kind}; start with a retrieval item or a worked example")
        for p in lesson.practice:
            if p.objective not in ids:
                errors.append(f"{at}: practice for unknown objective \"{p.objective}\"; use one of {sorted(ids)}")
            if p.component not in FITS[p.kind]:
                errors.append(f"{at}: {p.kind} practice must be one of {sorted(FITS[p.kind])}, not {p.component}")
        recall = [o.id for o in lesson.objectives if o.level in ("remember", "understand")]
        need = bool(recall) + len(lesson.objectives) - len(recall)
        drills = sum(p.kind not in ("worked", "faded") for p in lesson.practice)
        if drills > need:  # practice beyond what the objectives need crowds the explanation out of a 12-Block Section
            errors.append(f"{at}: {drills} practice items besides worked and faded examples, its objectives need {need}: one retrieval item "
                          "covers all the remember/understand objectives, one independent or exam problem each apply/analyse one")
        if recall and not any(p.kind == "retrieval" and p.objective in recall for p in lesson.practice):
            errors.append(f"{at}: objectives {recall} are remember/understand: practise them with one retrieval item "
                          "(quiz, fill_blanks or explain_back)")
        if any(p.component == "quiz" for p in lesson.practice) and not lesson.misconceptions:
            errors.append(f"{at}: a quiz needs the misconceptions its wrong options come from: list them")
        for o in lesson.objectives:
            covered |= set(o.exam_types)
            ahead = [c for c in o.concepts if c not in known]
            if ahead:
                errors.append(f"{at}: objective \"{o.id}\" uses {ahead}, which no Section up to this one teaches")
            kinds = [p.kind for p in lesson.practice if p.objective == o.id]
            if o.level in ("apply", "analyse"):
                if not {"independent", "exam"} & set(kinds) or "worked" not in kinds:
                    errors.append(f"{at}: objective \"{o.id}\" is {o.level}: a worked example, then an independent or exam problem")
            ramp = [RAMP.index(k) for k in kinds if k in RAMP]
            if ramp != sorted(ramp):
                errors.append(f"{at}: objective \"{o.id}\" practice goes worked, faded, independent, exam, in that order")
        v = lesson.visual
        if v.relation != "none" and v.component not in DRAWS[v.relation]:
            errors.append(f"{at}: a {v.relation} is drawn with one of {sorted(DRAWS[v.relation])}, not {v.component or 'nothing'}")
    missing = [t for t in exam_types if t not in covered]
    if missing:
        errors.append(f"no objective prepares for the Question Types {missing}: tag the objectives that do with their exact names")
    return errors


def plan_gaps(lesson: dict, blocks: list[dict]) -> list[str]:
    """What the Section's plan asked for that its Blocks don't have: a planned practice Component used fewer times than
    planned, or the planned visual."""
    have = collections.Counter(b.get("component") for b in blocks)
    want = collections.Counter(p["component"] for p in lesson["practice"])
    gaps = [f"the plan has {n} {c} Block(s) for objectives {[p['objective'] for p in lesson['practice'] if p['component'] == c]}, "
            f"the Section has {have[c]}" for c, n in want.items() if have[c] < n]
    v = lesson.get("visual") or {}
    if v.get("relation", "none") != "none" and not have[v.get("component")]:
        gaps.append(f"the plan has a {v['component']} showing {v.get('shows', 'the ' + v['relation'])}; the Section has none")
    return gaps


def explained(concept: str, seen: set[str]) -> bool:
    """Half the stems of the Concept's name (before any parenthesis, its notation) appear in what came before."""
    terms = name_stems(concept)
    return not terms or len(terms & seen) * 2 >= len(terms)


FORMAL = {"theorem_box", "key_formula"}
EXAMPLE = re.compile(r"exemple|example|e\.g\.|imagin|consid[ée]r|suppos|prenons|take a|par ex", re.I)  # an opening that works a case
CONCRETE = {"prose", "intuition", "misconception", "worked_example", "plot", "surface_plot", "explorer", "figure", "table", "diagram", "step_diagram",
            "iteration_table", "optimizer_animation", "terminal", "code"}  # after the opening: an example or a case to look at


def order_gaps(blocks: list[dict], teaches: list[str]) -> list[str]:
    """The Section's order against the learning design: it opens by orienting the learner, and each Concept it teaches is
    explained before a practice Block tests it."""
    gaps = []
    if blocks and blocks[0].get("component") not in ("prose", "callout"):
        gaps.append(f"the Section opens with a {blocks[0].get('component')}: open with a short prose Block that orients the "
                    "learner (what this is, why it matters, how it builds on what came before) before any formal Block")
    formal = next((n for n, b in enumerate(blocks) if b.get("component") in FORMAL), None)
    if formal is not None and not any(b.get("component") in CONCRETE for b in blocks[1:formal]) and \
            not EXAMPLE.search(" ".join(strings(blocks[0].get("data"))) if formal else ""):
        gaps.append(f"Block {formal + 1} ({blocks[formal]['component']}) states the formal version before any concrete case: "
                    "put a motivating example first (a worked_example, a plot, a small table or a prose example)")
    seen: set[str] = set()
    for n, b in enumerate(blocks, 1):
        if b.get("component") in PRACTICE:
            gaps += [f"Block {n} ({b['component']}) tests \"{c}\" before any Block explains it" for c in b.get("tests", [])
                     if c in teaches and not explained(c, seen)]
        elif b.get("component") != "recap":  # a recap restates; it does not explain
            seen |= {w for x in strings(b.get("data")) for w in stems(x)}
    gaps += [f"no Block explains \"{c}\", which this Section teaches" for c in teaches
             if not explained(c, seen) and not any(f'"{c}"' in g for g in gaps)]
    teach, drill = balance(blocks)
    counted = [b for b in blocks if b.get("component") != "recap"]
    drills = sum(b.get("component") in PRACTICE for b in counted)
    if drills * 3 > len(counted) or teach < drill:
        gaps.append(f"practice outweighs explanation ({drills} of {len(counted)} Blocks, {drill} practice words for {teach} teaching "
                    "words): explain each Concept in connected text first, and keep practice to about a third of the Blocks")
    return gaps


def balance(blocks: list[dict]) -> tuple[int, int]:
    """Words in teaching Blocks and in practice Blocks (a recap counts as neither)."""
    words = lambda b: sum(len(x.split()) for x in strings(b.get("data")))  # noqa: E731
    return (sum(words(b) for b in blocks if b.get("component") not in PRACTICE | {"recap"}),
            sum(words(b) for b in blocks if b.get("component") in PRACTICE))


def plan_chapter(db, backend, workdir, cid: int, chapter, sections: list[dict], inputs: dict, exam_types: list[str]) -> dict[str, dict]:
    """The Chapter's plan, made once and kept on the Chapter (a regenerated Section reuses it); Section title -> its lesson.
    A plan still breaking the rules after one retry is kept anyway, its errors in the trace: a weak plan never stalls a Run."""
    stored = json.loads(chapter["plan"] or "null")
    if stored and [s["title"] for s in stored["sections"]] == [s["title"] for s in sections]:
        return {s["title"]: s for s in stored["sections"]}
    inputs = inputs | {"sections": json.dumps([{"title": s["title"], "teaches": s["teaches"], "excerpt": s["excerpt"]} for s in sections],
                                              ensure_ascii=False), "errors": "none"}
    plan, errors = None, []
    for _ in range(2):
        plan = run_pi_step(db, backend, "plan_chapter", inputs, LessonPlan, workdir, course_id=cid)
        errors = plan_errors(plan, sections, json.loads(inputs["taught"]), exam_types)
        if not errors:
            break
        attach_checks(db, last_trace_id(), [{"errors": [f"plan: {e}" for e in errors]}])
        inputs = inputs | {"errors": "\n".join(f"- {e}" for e in errors)}
    assert plan is not None
    data = plan.model_dump()
    db.execute("UPDATE chapters SET plan=? WHERE id=?", (json.dumps(data, ensure_ascii=False), chapter["id"]))
    return {s["title"]: s for s in data["sections"]}
