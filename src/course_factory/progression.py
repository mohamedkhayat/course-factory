"""Progression (#22): a practice Block tests only what the Course has taught before it, in reading order, and gives the facts
it needs. Plain code, no model: it reads the Blocks' own text, so it also catches a model that under-declares what it tests."""

import json
import re

PRACTICE = {"quiz", "fill_blanks", "code_exercise", "exercise"}
WORD = re.compile(r"\w[\w\-]*")
CODE_SPAN = re.compile(r"```[^\n]*\n(.*?)```|`([^`\n]+)`", re.S)
CALL = re.compile(r"\.?([A-Za-z_]\w*)\s*\(|/(_\w+)")  # function and method calls, `/_update`-style endpoints
GAP = re.compile(r"\[\[\d+\]\]")
NAMED = re.compile(r"\b(?:index|indices?|documents?|champs?|fields?|tables?|fichiers?|files?|dossiers?|topics?|colonnes?|columns?)\s+[«\"]?\s*`([^`]+)`", re.I)
STOP = set("""a an and are as at be by de des du en et for from if in is it la le les of on or ou par pas pour que qui sur the
to un une with dans est sont ce cette il elle on ne se sa son ses au aux y oui non yes no true false none null self print return
def import from int str float len list dict set range open sum min max map filter lambda""".split())


def words(text: str) -> set[str]:
    return {w.lower() for w in WORD.findall(text)}


def strings(data) -> list[str]:
    if isinstance(data, str):
        return [data]
    if isinstance(data, dict):
        return [s for k, v in data.items() if k not in ("claims", "regex") for s in strings(v)]
    if isinstance(data, list):
        return [s for v in data for s in strings(v)]
    return []


def code_terms(text: str) -> set[str]:
    """The terms a piece of code relies on: called functions and methods, and `_endpoint` path segments."""
    return {(a or b).lower() for a, b in CALL.findall(text)}


def spans(text: str) -> str:
    return "\n".join(a or b for a, b in CODE_SPAN.findall(text))


def number(term: str) -> bool:
    return term.replace(".", "").isdigit()


def in_context(template: str, n: int, answer: str) -> set[str]:
    """The blank's answer with the characters glued to its gap, so `_[[5]]` filled with "update" tests `_update`."""
    m = re.search(rf"([\w\-]*)\[\[{n}\]\]([\w\-]*)", template)
    return words(f"{m[1]}{answer}{m[2]}" if m else answer)


def values(template: str, blanks: list[dict]) -> list[tuple[str, str]]:
    """(label, answer) of the blanks whose answer is this exercise's own data, not a taught term: a quoted value, a document
    id after `_doc/` or `_update/`, or a name with digits (`transaction_001`). Only the exercise can give those."""
    out = []
    for i, b in enumerate(blanks, 1):
        a = (b.get("answers") or [""])[0]
        if a and not number(a) and (re.search(rf':\s*"\[\[{i}\]\]"', template) or re.search(rf"/_(?:doc|update|create)/\[\[{i}\]\]", template)
                                    or (re.fullmatch(r"[\w\-.]+", a) and re.search(r"\d", a) and re.search(r"[A-Za-z]", a))):
            out.append((f"blank {i}", a))
    return out


def tested(component: str, data: dict) -> tuple[list[tuple[str, set[str]]], str]:
    """(what the Block expects, as (label, terms) pairs; the text the learner sees before answering)."""
    if component == "fill_blanks" or (component == "code_exercise" and data.get("blanks")):
        shown = " ".join([data.get("title", ""), data.get("task", ""), GAP.sub(" ", data.get("template") or data.get("starter", ""))])
        template = data.get("template") or data.get("starter", "")
        return [(f"blank {i}", in_context(template, i, b["answers"][0])) for i, b in enumerate(data["blanks"], 1) if b.get("answers")], shown
    if component == "code_exercise":
        shown = " ".join([data["task"], data["starter"]])
        return [("solution", code_terms(data["solution"]) - code_terms(shown))], shown + " " + " ".join(data.get("hints", []))
    if component == "exercise":
        return [("correction", code_terms(spans(data["correction"])) - code_terms(spans(data["statement"])))], data["statement"]
    if component == "quiz":
        out = []
        for n, q in enumerate(data["questions"], 1):
            right = " ".join(q["options"][i] for i in q["correct"] if i < len(q["options"]))
            # "l'index `capteurs`", `("L1", 5)`: names and string literals the prompt gives are data, not taught terms
            named = words(" ".join(NAMED.findall(q["prompt"]) + re.findall(r'"([^"\n]*)"', spans(q["prompt"]))))
            out.append((f"question {n}", {w for w in words(spans(q["prompt"]) + " " + spans(right)) if not number(w)} - named))
        return out, ""
    return [], ""


def progression_errors(blocks: list[dict]) -> dict[int, list[str]]:
    """`blocks` in reading order, each {"id", "component", "data", "chapter", "section"}. Returns id -> errors for each
    practice Block that expects a term no earlier Block has taught (or one a later Section of its Chapter is named after)
    and that its own text does not give."""
    sections = list(dict.fromkeys((b["chapter"], b["section"]) for b in blocks))
    first_seen: dict[str, str] = {}
    for b in blocks:
        for w in words(" ".join(strings(b["data"]))):
            first_seen.setdefault(w, b["section"])

    def home(at: int, term: str) -> str | None:
        """A later Section of the same Chapter named after the term (\"CRUD Operations: PUT, GET\"): where it is really taught."""
        chapter, title = sections[at]
        if term in words(title):
            return None
        return next((t for c, t in sections[at + 1:] if c == chapter and term in words(t)), None)

    taught: set[str] = set()
    explained: dict[tuple, set[str]] = {}  # per Section: words its tables, definitions and prose explain (not just show)
    errors: dict[int, list[str]] = {}
    for b in blocks:
        here = explained.setdefault((b["chapter"], b["section"]), set())
        if b["component"] in PRACTICE:
            parts, shown = tested(b["component"], b["data"])
            given = words(shown)
            if b["component"] == "fill_blanks" or (b["component"] == "code_exercise" and b["data"].get("blanks")):
                for label, value in values(b["data"].get("template") or b["data"].get("starter", ""), b["data"]["blanks"]):
                    if not words(value) <= given:
                        errors.setdefault(b["id"], []).append(
                            f"{label}: expects \"{value}\", a value only this exercise can give (an id, a name, a new field value): "
                            "state it in the title or task")
            code = b["component"] != "fill_blanks" or bool(b["data"].get("language"))  # prose words recur everywhere: code terms only
            for label, terms in parts:
                for t in sorted(terms - given - STOP):
                    main = home(sections.index((b["chapter"], b["section"])), t)
                    if number(t):
                        if t not in taught and not any(map(number, given)):  # with numbers in the task, it may be computed from them
                            errors.setdefault(b["id"], []).append(
                                f"{label}: expects the number {t}, which neither the task nor an earlier Block gives: state it in the task")
                    elif len(t) < 2:
                        continue
                    elif t not in taught:
                        later = first_seen.get(t)
                        where = f"it is first taught in Section \"{later}\"" if later and later != b["section"] else "nothing teaches it"
                        errors.setdefault(b["id"], []).append(
                            f"{label}: tests \"{t}\" before the Course teaches it ({where}): teach it first, give it in the task, "
                            "or test only what earlier Blocks taught")
                    elif code and main and first_seen[t] == b["section"] and t not in here:  # shown first here, as a preview of its own Section
                        errors.setdefault(b["id"], []).append(
                            f"{label}: tests \"{t}\", which the later Section \"{main}\" teaches: move this practice "
                            "after it, or test only what this Section and earlier ones teach")
        taught |= words(" ".join(strings(b["data"])))
        if b["component"] not in PRACTICE | {"terminal", "code"}:
            here |= words(" ".join(strings(b["data"])))
    return errors


MARK = "progression: "
REPEAT = 0.9  # share of the smaller answer's terms found in the earlier one: same API names with another folder or value is a new case


def answer_terms(component: str, data: dict) -> list[tuple[str, set[str]]]:
    """What a practice Block makes the learner produce, as (label, terms): its filled-in code, or each quiz question's prompt."""
    if component == "quiz":
        return [(f"question {n}", words(q["prompt"]) - STOP) for n, q in enumerate(data["questions"], 1)]
    if component == "exercise":
        text = spans(data["correction"])
    elif data.get("blanks"):
        text = data.get("template") or data.get("starter", "")
        for i, b in enumerate(data["blanks"], 1):
            text = text.replace(f"[[{i}]]", (b.get("answers") or [""])[0])
    else:
        text = data.get("solution", "")
    return [("", words(text) - STOP)]


def repeat_errors(blocks: list[dict]) -> dict[int, list[str]]:
    """A practice Block (or quiz question) asking what an earlier one in its Chapter already asked, with the same names and
    values: the learner only recalls the earlier answer. `blocks` in reading order, as in progression_errors."""
    seen: list[tuple[dict, str, set[str]]] = []
    errors: dict[int, list[str]] = {}
    for b in blocks:
        if b["component"] not in PRACTICE:
            continue
        mine = answer_terms(b["component"], b["data"])
        for label, terms in mine:
            for other, other_label, prior in seen:
                small = min(len(terms), len(prior))
                if other["chapter"] == b["chapter"] and small >= 4 and len(terms & prior) >= REPEAT * small:
                    title = other["data"].get("title") or other_label
                    errors.setdefault(b["id"], []).append(
                        f"repeat: {(label + ' ') if label else ''}asks what \"{title}\" (Section \"{other['section']}\") already asked, "
                        "with the same names and values, so the learner only recalls that answer: give it another case (another "
                        "index, id, field, value or dataset, every fact stated in the task) or practise another skill")
                    break
        seen += [(b, label, terms) for label, terms in mine]
    return errors


def ledger_errors(blocks: list[dict], concepts: dict[str, tuple[int, str]]) -> dict[int, list[str]]:
    """The Concept ledger: each Block's declared `tests` must be Concepts (concept -> (reading-order index, title) of the
    Section that teaches it) taught by its own Section (the Block's "at") or an earlier one."""
    errors: dict[int, list[str]] = {}
    for b in blocks:
        for c in b.get("tests", []):
            if c not in concepts:
                errors.setdefault(b["id"], []).append(f"tests \"{c}\", which is not a Concept of this Course; use one of: "
                                                      + ", ".join(list(concepts)[:60]))
            elif concepts[c][0] > b["at"]:
                errors.setdefault(b["id"], []).append(f"tests \"{c}\", which is taught later, in Section \"{concepts[c][1]}\": "
                                                      "move this practice after it or test only what is taught by now")
    return errors


def course_blocks(db, cid: int) -> tuple[list[dict], dict[str, tuple[int, str]]]:
    """The Blocks of the Chapters whose earlier Chapters are all written, in reading order (Chapter, Section, Block position),
    and the Course's Concepts (concept -> (reading-order index, title) of the Section that teaches it)."""
    chapters, concepts, at = [], {}, {}
    for c in db.execute("SELECT id, status FROM chapters WHERE course_id=? AND priority!='skip' ORDER BY position", (cid,)):
        if c["status"] not in ("in_review", "published"):
            break  # what it will teach is not written yet: later Chapters can't be checked
        chapters.append(c["id"])
    for i, s in enumerate(db.execute("SELECT s.id, s.title, s.teaches FROM sections s JOIN chapters c ON c.id=s.chapter_id "
                                     "WHERE c.course_id=? ORDER BY c.position, s.position", (cid,))):
        at[s["id"]] = i  # by id: two Chapters can both have a Section titled "Exercices"
        for concept in json.loads(s["teaches"]):
            concepts.setdefault(concept, (i, s["title"]))
    if not chapters:
        return [], concepts
    rows = db.execute(f"SELECT b.id, b.component, b.data, b.tests, s.id sid, s.title section, c.id chapter FROM blocks b "
                      f"JOIN sections s ON s.id=b.section_id JOIN chapters c ON c.id=s.chapter_id "
                      f"WHERE c.id IN ({','.join('?' * len(chapters))}) ORDER BY c.position, s.position, b.position", chapters).fetchall()
    return [{"id": r["id"], "component": r["component"], "data": json.loads(r["data"]), "tests": json.loads(r["tests"]),
             "chapter": r["chapter"], "section": r["section"], "at": at[r["sid"]]} for r in rows], concepts


def flag_progression(db, cid: int) -> dict[int, list[str]]:
    """Re-checks the Course's progression and updates the Blocks' flags: a Block that tests ahead of the Course is flagged
    with why; one whose only flags were progression flags is ok again. Returns the errors per Block id."""
    blocks, concepts = course_blocks(db, cid)
    errors = progression_errors(blocks)
    for bid, errs in [*ledger_errors(blocks, concepts).items(), *repeat_errors(blocks).items()]:
        errors.setdefault(bid, []).extend(errs)
    for b in blocks:
        row = db.execute("SELECT status, flags FROM blocks WHERE id=?", (b["id"],)).fetchone()
        old = json.loads(row["flags"])
        kept = [f for f in old if not f.startswith(MARK)]
        new = kept + [MARK + e for e in errors.get(b["id"], [])]
        if new == old:
            continue
        # shortcut: flags mix errors and warnings, so a warning-only Block that progression flagged stays flagged once
        # its progression error clears outside an edit (publish, auto-resolve); the owner approves it. Store status-before if it bites.
        status = "flagged" if errors.get(b["id"]) else ("ok" if row["status"] == "flagged" and not kept else row["status"])
        db.execute("UPDATE blocks SET flags=?, status=? WHERE id=?", (json.dumps(new, ensure_ascii=False), status, b["id"]))
    return errors
