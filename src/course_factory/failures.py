"""Failure classes (#21): every check message, flag and owner fix gets a stable class, so recurring problems can be counted
and hardened one class at a time (harness/failures.yaml records how each is handled now)."""
import collections
import json
import re
import sqlite3

import yaml

from .pi_step import HARNESS_DIR

# (pattern, class); the first match wins. Validation errors are classed by their field path in schema_class.
CLASSES = [
    (r"^owner note:", "owner-note"),
    (r"^progression: repeat:", "repeat"),
    (r"^progression:", "progression"),
    (r"should branch", "diagram-chain"),
    (r"^plan:", "plan"),
    (r"^quiz cue:|is a cue, not a mistake", "quiz-cue"),
    (r"^diagram size:", "diagram-size"),
    (r"^definition cram:", "definition-cram"),
    (r"^section overlap:", "section-overlap"),
    (r"^grounding judge (failed|returned no result)", "judge-failed"),
    (r"^contradicts its cited pages", "contradicts-pages"),
    (r"^grounding:", "beyond-pages"),
    (r"^source error:", "source-error"),
    (r"^sympy could not check", "sympy-unparsable"),
    (r"^sympy:", "sympy-wrong"),
    (r"writes a formula as code", "ascii-math"),
    (r"placeholder", "placeholder-section"),
    (r"KaTeX parse error", "katex-parse"),
    (r"is not defined\b", "render-dom-global"),
    (r"node ids that are not in nodes", "diagram-ids"),
    (r"Parse error on line|Lexical error|[Mm]ermaid", "mermaid-render"),
    (r"^citation to .* does not exist", "citation-missing-page"),
    (r"needs at least one Citation", "citation-none"),
    (r"^question \d+: (options are not distinct|a correct index|single-choice)", "quiz-answers"),
    (r"^question \d+: explanation", "quiz-explanations"),
    (r"the plotter cannot draw|expression does not parse|expr must be|not differentiable", "expr"),
    (r"does not parse:", "code-parse"),
    (r"Extra data|Expecting value|Unterminated string|Invalid \\escape|Invalid control character", "bad-json"),
    (r"^not a Block", "not-a-block"),
    (r"^the Check ", "lab-check"),
]


def schema_class(message: str) -> str | None:
    """'claims.3.op: Input should be ...' -> 'schema:claims.op:enum'."""
    m = re.match(r"^([A-Za-z_][\w\[\],. ]*?\.[\w\[\],.]+): (.+)", message)
    if not m:
        return None
    path = ".".join(re.sub(r"\[.*", "", p) for p in m.group(1).split(".") if p and not p.isdigit())
    reason = m.group(2)
    kind = ("missing" if reason.startswith("Field required") else "enum" if re.match(r"Input should be '", reason)
            else "type" if reason.startswith("Input should be a valid") else "invalid")
    return f"schema:{path}:{kind}"


def failure_class(message: str) -> str:
    for pattern, name in CLASSES:
        if re.search(pattern, message):
            return name
    return schema_class(message) or "unclassified"


def ledger() -> dict:
    path = HARNESS_DIR / "failures.yaml"
    return (yaml.safe_load(path.read_text()) or {}) if path.exists() else {}


def lessons(step: str) -> list[str]:
    """Lessons for one Model step: only for classes code can't handle, a few lines each."""
    return [e["lesson"] for e in ledger().values() if e.get("handler") == "lesson" and step in e.get("steps", []) and e.get("lesson")][:5]


def report(db: sqlite3.Connection, course_id: int | None = None) -> list[dict]:
    """Classes ranked by how often they happen: in the checks of Model steps, in Blocks still flagged, and in what the owner fixed.
    Each with examples, the Harness versions it shows up in, its handler, and the rate per checked step before and after hardening."""
    where, args = ("AND course_id=?", (course_id,)) if course_id else ("", ())
    seen: dict[str, dict] = {}
    checked: list[str] = []  # dates of checked steps, for rates

    def add(message: str, source: str, version: str | None, when: str | None, c: str | None = None):
        c = c or failure_class(message)
        e = seen.setdefault(c, {"class": c, "count": 0, "sources": collections.Counter(), "versions": collections.Counter(),
                                "examples": [], "dates": []})
        e["count"] += 1
        e["sources"][source] += 1
        if version:
            e["versions"][version] += 1
        if when:
            e["dates"].append(when)
        if message and len(e["examples"]) < 3 and message not in e["examples"]:
            e["examples"].append(message[:400])

    for row in db.execute(f"SELECT checks, harness_version, created_at FROM traces WHERE checks IS NOT NULL {where}", args):
        checked.append(row["created_at"])
        try:
            data = json.loads(row["checks"])
        except ValueError:
            continue
        for item in data if isinstance(data, list) else [data]:
            if isinstance(item, dict):
                for m in (item.get("errors") or []) + (item.get("warnings") or []):
                    add(str(m), "checks", row["harness_version"], row["created_at"])
    for row in db.execute(f"SELECT inputs, owner_action, harness_version, created_at FROM traces WHERE owner_action IN "
                          f"('edited','regenerated','auto_resolved') {where}", args):
        for c in json.loads(row["inputs"] or "{}").get("classes", []):  # recorded as classes already
            add("", row["owner_action"], row["harness_version"], row["created_at"], c)
    block_where = "AND s.chapter_id IN (SELECT id FROM chapters WHERE course_id=?)" if course_id else ""
    for row in db.execute(f"SELECT b.flags FROM blocks b JOIN sections s ON s.id=b.section_id WHERE b.flags!='[]' {block_where}", args):
        for m in json.loads(row["flags"]):
            add(m, "flagged now", None, None)

    known = ledger()
    out = []
    for e in sorted(seen.values(), key=lambda e: -e["count"]):
        entry = known.get(e["class"], {})
        rates = None
        if entry.get("hardened") and checked:
            cut = str(entry["hardened"])
            before_n, after_n = sum(d < cut for d in checked), sum(d >= cut for d in checked)
            hits_before, hits_after = sum(d < cut for d in e["dates"]), sum(d >= cut for d in e["dates"])
            rates = {"before": round(hits_before / before_n, 3) if before_n else None,
                     "after": round(hits_after / after_n, 3) if after_n else None}
        out.append({"class": e["class"], "count": e["count"], "sources": dict(e["sources"]), "versions": dict(e["versions"].most_common(5)),
                    "examples": e["examples"], "handler": entry.get("handler", "none"), "what": entry.get("what"),
                    "test": entry.get("test"), "rate": rates})
    return out

