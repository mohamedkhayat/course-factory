"""Progression (#22): a practice Block tests only what the Course has taught before it, in reading order, and gives the facts
it needs. Plain code, no model: it reads the Blocks' own text, so it also catches a model that under-declares what it tests."""

import itertools
import json
import re

PRACTICE = {"quiz", "fill_blanks", "code_exercise", "exercise", "explain_back"}
WORD = re.compile(r"\w[\w\-]*")
CODE_SPAN = re.compile(r"```[^\n]*\n(.*?)```|`([^`\n]+)`", re.S)
CALL = re.compile(r"\.?([A-Za-z_]\w*)\s*\(|/(_\w+)")  # function and method calls, `/_update`-style endpoints
GAP = re.compile(r"\[\[\d+\]\]")
JSON_KEY = re.compile(r'"([A-Za-z_]\w*)"\s*:')  # a query DSL's clauses (`"bool":`, `"range":`) are its keys
NAMED = re.compile(r"\b(?:index|indices?|documents?|champs?|fields?|tables?|fichiers?|files?|dossiers?|topics?|colonnes?|columns?)\s+[«\"]?\s*`([^`]+)`", re.I)
STOP = set("""a an and are as at be by de des du en et for from if in is it la le les of on or ou par pas pour que qui sur the
to un une with dans est sont ce cette il elle on ne se sa son ses au aux y oui non yes no true false none null self print return
def import from int str float len list dict set range open sum min max map filter lambda""".split())


def words(text: str) -> set[str]:
    return {w.lower() for w in WORD.findall(text)}


def stems(text: str) -> set[str]:
    """Word stems (5 letters: "minimiseur" and "minimum" meet), so a Concept's name matches the way the Blocks phrase it."""
    return {w[:5] for w in words(text.replace("-", " ")) if len(w) >= 3 and w not in STOP}


def name_stems(concept: str) -> set[str]:
    """The stems of a Concept's name, without its notation in parentheses."""
    return stems(re.split(r"\s*\(", concept)[0])


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


def practised(component: str, data: dict) -> set[str]:
    """The commands, functions and clauses a code drill makes the learner write: its answer's calls and keys, less the data
    its title and task give. A hint or a starter comment naming them does not teach them."""
    if component == "code_exercise" or (component == "fill_blanks" and data.get("language")):
        code = answer_text(data)
        keys = set() if data.get("language") == "python" else {k.lower() for k in JSON_KEY.findall(code)}  # a Python dict's keys are data
        terms = (code_terms(code) - STOP) | keys  # a query's `"range":` is a clause, not the builtin
        if data.get("blanks"):
            terms = set().union(*(in_context(data.get("template") or data.get("starter", ""), i, b["answers"][0])
                                  for i, b in enumerate(data["blanks"], 1) if b.get("answers"))) - STOP
        return terms - words(data.get("title", "") + " " + data.get("task", ""))
    return set()


def example_code(component: str, data: dict) -> str:
    """The code a Block shows working, which is what teaches a command or clause: a session, a code listing, a worked
    answer, an earlier practice's answer, fenced code, or a table row that pairs one piece of code with what it does.
    A name only listed in passing (`bool`, `term`, `range` in one cell) is mentioned, not shown."""
    if component == "terminal":
        return "\n".join(e.get("command", "") + "\n" + (e.get("output") or "") for e in data.get("entries", []))
    if component == "code":
        return data.get("code", "")
    if component in ("fill_blanks", "code_exercise"):
        return answer_text(data)
    fenced = "\n".join(a for a, _ in CODE_SPAN.findall("\n".join(strings(data))) if a)
    if component == "worked_example":
        fenced += "\n" + data.get("answer", "") + "\n" + "\n".join(map(spans, data.get("steps", [])))
    if component == "exercise":
        fenced += "\n" + spans(data.get("correction", ""))
    rows = [r for r in data.get("rows", []) if isinstance(r, list)] if component == "table" else []
    return fenced + "\n" + "\n".join(c.strip("`") for r in rows for c in r if isinstance(c, str) and re.fullmatch(r"`[^`]+`", c.strip()))


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
    shown_code: set[str] = set()  # words of the code earlier Blocks showed working (example_code)
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
            for t in sorted(practised(b["component"], b["data"]) - shown_code):
                if len(t) >= 2 and not number(t) and not any(f'"{t}"' in e for e in errors.get(b["id"], [])):
                    errors.setdefault(b["id"], []).append(
                        f"expects \"{t}\", which no earlier Block shows working (naming it in a table, a hint or the starter is not enough): show it working "
                        "first in a terminal session, code or worked example that says what it does, then practise it")
        taught |= words(" ".join(strings(b["data"])))
        shown_code |= words(example_code(b["component"], b["data"]))
        if b["component"] not in PRACTICE | {"terminal", "code"}:
            here |= words(" ".join(strings(b["data"])))
    return errors


MARK = "progression: "
REPEAT = 0.9  # share of the smaller answer's terms found in the earlier one: same API names with another folder or value is a new case


def answer_terms(component: str, data: dict) -> list[tuple[str, set[str]]]:
    """What a practice Block makes the learner produce, as (label, terms): its filled-in code, or each quiz question's prompt."""
    if component == "quiz":
        return [(f"question {n}", words(q["prompt"]) - STOP) for n, q in enumerate(data["questions"], 1)]
    return [("", words(spans(data["correction"]) if component == "exercise" else answer_text(data)) - STOP)]


def answer_text(data: dict) -> str:
    """The code a fill_blanks or code_exercise expects: its template with the blanks filled, or its solution."""
    if not data.get("blanks"):
        return data.get("solution", "")
    text = data.get("template") or data.get("starter", "")
    for i, b in enumerate(data["blanks"], 1):
        text = text.replace(f"[[{i}]]", (b.get("answers") or [""])[0])
    return text


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
    names = {c: name_stems(c) for c in concepts}
    for b in blocks:
        if b.get("component") in PRACTICE:  # undeclared: its text names a later Concept by words no Concept taught by now uses
            known = set().union(*(names[c] for c, (i, _) in concepts.items() if i <= b["at"]))
            text = {w for x in strings(b["data"]) for w in stems(x)}
            if later := [f"asks about \"{c}\", which is taught later, in Section \"{t}\": move this practice after it or leave it out"
                         for c, (i, t) in concepts.items() if i > b["at"] and c not in b.get("tests", [])
                         and len(new := names[c] - known) >= 2 and new <= text]:
                errors[b["id"]] = later
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


REST = re.compile(r"\b(GET|PUT|POST|DELETE|HEAD)\s+'?(\S*/\S*)")
METHOD_CALL = re.compile(r"\.(\w+)\s*\(")
OVERLAP = 0.6  # share of the smaller Section's operations the other also teaches


def operations(component: str, data: dict) -> set[str]:
    """The commands a Block shows or drills: a REST call as its method and endpoint (PUT _doc), code as the methods it calls."""
    if component == "terminal":
        texts = [e.get("command", "") for e in data.get("entries", [])]
    elif component in ("fill_blanks", "code_exercise", "code"):
        texts = [answer_text(data) if component != "code" else data.get("code", "")]
    else:
        texts = [spans(s) for s in strings(data)]
    out: set[str] = set()
    for t in texts:
        t = re.sub(r"-X\s*([A-Z]+)\s+'?", r"\1 ", t)  # curl -X PUT 'host:9200/i/_doc/1' reads as PUT host:9200/i/_doc/1
        t = re.sub(r"\bcurl\s+'", "GET ", t)  # curl with no method is a GET
        out |= {f"{m} {(re.search(r'/(_\w+)', path) or [None, 'index'])[1]}" for m, path in REST.findall(t)}
        out |= {c.lower() for c in METHOD_CALL.findall(t)}
    return out


def section_overlaps(sections: list[dict]) -> list[tuple[dict, dict, list[str]]]:
    """Pairs of a Chapter's Sections ({id, title, teaches, blocks}) that teach the same operations or Concepts, with what
    they share: two Sections on the same commands (CRUD vs REST request types) should be one."""
    ops = {s["id"]: set().union(*(operations(b["component"], b["data"]) for b in s["blocks"]), {f"concept {c}" for c in s["teaches"]})
           for s in sections}
    if len(sections) >= 4:  # what most Sections use is the Chapter's boilerplate (getOrCreate, pprint), not its topic
        common = {o for o in set().union(*ops.values()) if sum(o in v for v in ops.values()) > len(sections) / 2}
        ops = {k: v - common for k, v in ops.items()}
    return [(a, b, sorted(shared)) for a, b in itertools.combinations(sections, 2)
            if len(shared := ops[a["id"]] & ops[b["id"]]) >= 3 and len(shared) >= OVERLAP * min(len(ops[a["id"]]), len(ops[b["id"]]))]
