import pytest

from course_factory.checks import check_blocks


def example(*claims, steps=("s",)):
    return {"component": "worked_example", "origin": "model_added", "citations": [],
            "data": {"title": "t", "problem": "p", "steps": list(steps), "answer": "a", "claims": list(claims)}}


def errors_of(*claims):
    _, (errors,) = check_blocks([example(*claims)], {})
    return errors


@pytest.mark.parametrize("claim", [
    {"expr": "(2 - 1)**2 - 1 == 0"},  # an equation in expr, no op or expected
    {"expr": "(3 - 1*1 - 0)**2", "expected": "4"},  # no op
    {"expr": "1/2*(100*x1**2 + x2**2)", "derivative": "100*x1", "var": "x1"},
    {"op": "lt", "expr": "diff(sqrt(x), x, 2)", "expected": "0"},  # an op sympy cannot check is dropped
    {"op": "diff", "expr": "diff(Rational(1,2)*((A*t+B - x)**2), B)", "vars": ["B"], "expected": "A*t + B - x"},
    {"op": "equal", "expr": "Matrix([[2,0],[0,6]]).eigenvals()", "vars": [], "expected": "{2: 1, 6: 1}"},
    {"op": "equal", "expr": "solve([4*x + 2*y - 1, 2*x + 4*y - 1], [x, y])", "vars": [], "expected": "[(1/6, 1/6)]"},
    {"op": "hessian", "expr": "2*x**2 + 2*y**2 + 2*x*y - x - y", "vars": [], "expected": [["4", "2"], ["2", "4"]]},
    {"op": "grad", "expr": "x**2 + y**2 + x*y", "vars": ["x", "y"], "expected": "[2*x + y, x + 2*y]"},
    {"op": "hessian", "expr": "x**2 + y**2 + x*y", "vars": ["x", "y"], "expected": "[[2, 1], [1, 2]]"},
    {"op": "grad", "expr": "x**2 + y**2 + z**2 - 2*x", "vars": ["x", "y", "z"], "expected": "2*x - 2, 2*y, 2*z"},
    {"op": "hessian", "expr": "4*x**2 - 4*x*y + 2*y**2", "vars": ["x", "y"], "expected": "8, -4, -4, 4"},
    {"op": "hessian", "expr": "exp(-x**2/2) + x", "vars": ["x"], "expected": "(x**2 - 1)*exp(-x**2/2)"},
    {"op": "grad", "expr": "1/2*(10*x1**2 + 180*x1*x2) - 123*x1", "vars": ["x1"], "expected": "10*x1 + 90*x2 - 123"},
    {"op": "equal", "expr": "0.8 - 0.1*(-10.8)", "vars": [], "expected": "1.88"},
    {"op": "equal", "expr": "-4*(2.866-1.317)*(-2.909) + (-4*(2.866-1.317)*(-4.194))", "vars": [], "expected": "44.009"},
    {"op": "equal", "expr": "2 + 1", "vars": [], "expected": 3},
])
def test_claims_in_the_shapes_the_model_writes_are_checked_not_flagged(claim):
    assert errors_of(claim) == []


@pytest.mark.parametrize("claim", [
    {"expr": "(2 - 1)**2 == 3"},
    {"op": "grad", "expr": "x**2 + y**2", "vars": ["x", "y"], "expected": "2*x, 3*y"},
    {"op": "equal", "expr": "0.8 - 0.1*(-10.8)", "vars": [], "expected": "1.9"},
    {"op": "equal", "expr": "Matrix([[2,0],[0,6]]).eigenvals()", "vars": [], "expected": "{2: 1, 5: 1}"},
])
def test_a_wrong_claim_is_still_an_error(claim):
    assert [e for e in errors_of(claim) if e.startswith("sympy:")]


def test_a_claim_sympy_cannot_parse_does_not_flag_the_block():
    assert errors_of({"op": "equal", "expr": "f(x) = ??", "vars": [], "expected": "1"}) == []


def test_text_the_model_mangled_is_repaired_before_rendering():
    block = example(steps=[r"$$a = 1$$$$= b$$", r"Soit :\n1. $u$", r"$f \text{ \mu-fortement convexe}$"])
    (fixed,), (errors,) = check_blocks([block], {})
    assert errors == []
    assert fixed["data"]["steps"] == ["$$a = 1$$\n$$= b$$", "Soit :\n1. $u$", r"$f \text{ }\mu\text{-fortement convexe}$"]


def heal(component, data):
    (fixed,), (errors,) = check_blocks([{"component": component, "origin": "model_added", "citations": [], "data": data}], {})
    assert errors == []
    return fixed["data"]


def test_empty_steps_and_hints_are_dropped():
    assert heal("worked_example", {"title": "t", "problem": "p", "steps": ["a", "", " "], "answer": "x"})["steps"] == ["a"]
    assert heal("exercise", {"title": "t", "statement": "s", "hints": ["", "h"], "correction": "c"})["hints"] == ["h"]


def test_a_display_formula_left_open_is_closed():
    assert heal("prose", {"markdown": "est\n$$\\rho^*=\\frac{2}{3}."})["markdown"] == "est\n$$\\rho^*=\\frac{2}{3}.$$"


def test_latex_escapes_outside_math_become_text():
    md = r"$$a$$\nLa mise $\nabla f$ ok\n- b; $x$;\quad $y$ \neq"
    assert heal("prose", {"markdown": md})["markdown"] == "$$a$$\nLa mise $\\nabla f$ ok\n- b; $x$; $y$ \\neq"


def test_diagram_labels_starting_like_a_markdown_list_are_escaped():
    src = 'flowchart TD\n  A["1. start"] -->|"+ J convexe"| B["- end"]'
    assert heal("diagram", {"mermaid": src, "caption": "c"})["mermaid"] == \
        'flowchart TD\n  A["1#46; start"] -->|"#43; J convexe"| B["#45; end"]'


def test_a_block_the_model_wrapped_in_another_object_is_unwrapped():
    inner = example({"op": "equal", "expr": "2 + 1", "vars": [], "expected": "3"})
    (fixed,), (errors,) = check_blocks([{"block": inner, "data": {}}], {})
    assert errors == [] and fixed["component"] == "worked_example"


def block(component, data):
    return {"component": component, "origin": "model_added", "citations": [], "data": data}


def check_one(component, data):
    (fixed,), (errors,) = check_blocks([block(component, data)], {})
    return fixed["data"], errors


DOCKERFILE = "FROM python:3.12-slim\nWORKDIR /app\nCOPY . .\nRUN pip install -r requirements.txt \\\n    && rm -rf /root/.cache\nCMD [\"python\", \"app.py\"]"
GOOD = {
    "fill_blanks": {"title": "Dockerfile", "language": "dockerfile", "template": "FROM [[1]]\nWORKDIR /app\n[[2]] . .",
                    "blanks": [{"answers": ["python:3.12-slim"], "regex": "python:3\\.1[0-3](-slim)?"}, {"answers": ["COPY", "ADD"], "hint": "copies files in"}]},
    "code_exercise": {"title": "Containerise the app", "task": "Write a Dockerfile for `app.py`.", "language": "dockerfile",
                      "starter": "FROM python:3.12-slim\n# TODO", "solution": DOCKERFILE, "hints": ["Start from a Python image."]},
    "surface_plot": {"title": "Rosenbrock", "expr": "(1 - x)**2 + 100*(y - x**2)**2", "x_range": [-2, 2], "y_range": [-1, 3]},
    "optimizer_animation": {"title": "GD on a bowl", "expr": "x**2 + 10*y**2", "method": "gradient", "start": [2, 1], "step": 0.05},
    "step_diagram": {"mermaid": "flowchart LR\n  A[Client] --> B[LB] --> C[App]", "steps": [
        {"highlight": ["A"], "caption": "The client sends a request"}, {"highlight": ["B", "C"], "edges": [["B", "C"]], "caption": "The load balancer forwards it"}]},
    "terminal": {"entries": [{"command": "docker build -t app .", "output": "Successfully tagged app:latest", "note": "Builds the image"}]},
    "exercise": {"title": "t", "statement": "s", "correction": "c", "mode": "hand", "steps": ["a", "b"]},
}


def test_a_blank_can_accept_a_pattern_and_a_code_exercise_can_have_blanks():
    assert check_one("fill_blanks", GOOD["fill_blanks"] | {"blanks": [
        {"answers": ["python:3.12-slim"], "regex": "python:3\\.1[0-3](-slim)?"}, {"answers": ["COPY"]}]})[1] == []
    assert check_one("code_exercise", GOOD["code_exercise"] | {"starter": "FROM [[1]]\nCOPY . .", "rubric": "Uses a slim image.",
                                                            "blanks": [{"answers": ["python:3.12-slim"]}]})[1] == []
    assert check_one("step_diagram", GOOD["step_diagram"] | {"steps": [{"highlight": ["A", "B"], "edges": [["A", "B"]], "caption": "c"}]})[1] == []


@pytest.mark.parametrize("component", GOOD)
def test_each_new_component_accepts_a_good_block(component):
    assert check_one(component, GOOD[component])[1] == []


@pytest.mark.parametrize("component, change, error", [
    ("fill_blanks", {"template": "FROM [[1]]"}, "blank"),  # 2 blanks, 1 gap
    ("fill_blanks", {"blanks": [{"answers": []}, {"answers": ["COPY"]}]}, "answers"),
    ("code_exercise", {"solution": "FROM python\nCOPPY . ."}, "dockerfile"),
    ("code_exercise", {"language": "yaml", "solution": "a: [1, 2"}, "yaml"),
    ("code_exercise", {"language": "python", "solution": "def f(:\n  pass"}, "python"),
    ("surface_plot", {"expr": "x**2 + z"}, "x and y"),
    ("optimizer_animation", {"expr": "x +* y"}, "parse"),
    ("step_diagram", {"steps": [{"highlight": ["Z"], "caption": "?"}]}, "Z"),
    ("fill_blanks", {"blanks": [{"answers": [" "]}, {"answers": ["COPY"]}]}, "empty"),
    ("fill_blanks", {"blanks": [{"answers": ["python"], "regex": "python:3\\.(1[0-3"}, {"answers": ["COPY"]}]}, "regex"),
    ("code_exercise", {"starter": "FROM [[1]]\n# TODO", "blanks": [{"answers": ["python:3.12"]}, {"answers": ["x"]}]}, "blank"),
    ("code_exercise", {"language": "python", "solution": "x = 1", "starter": "x = [[1]]", "blanks": [{"answers": ["(1"]}]}, "python"),
    ("optimizer_animation", {"expr": "abs(x) + y**2"}, "differentiable"),
    ("surface_plot", {"expr": "ln(x**2 + 1) + y"}, "ln"),
    ("step_diagram", {"mermaid": "flowchart LR\n  L[Load A] --> B[LB]", "steps": [{"highlight": ["A"], "caption": "?"}]}, "A"),
    ("step_diagram", {"steps": [{"highlight": ["A"], "edges": [["A", "C"]], "caption": "?"}]}, "edge"),
])
def test_a_broken_new_block_is_flagged(component, change, error):
    errors = check_one(component, GOOD[component] | change)[1]
    assert errors and any(error in e for e in errors), errors


def test_a_plot_only_uses_functions_the_browser_can_draw():
    plot = {"title": "t", "functions": [{"expr": "ln(x) + 1", "label": "f"}], "x_range": [0.1, 3]}
    assert any("ln" in e for e in check_one("plot", plot)[1])
    assert check_one("plot", plot | {"functions": [{"expr": "log(x) + 1", "label": "f"}]})[1] == []


def test_code_is_syntax_checked_and_never_rewritten_as_markdown():
    data, errors = check_one("code", {"language": "python", "code": "print('a\\nb')\nx = 1"})
    assert errors == [] and data["code"] == "print('a\\nb')\nx = 1"
    assert any("python" in e for e in check_one("code", {"language": "python", "code": "def ("})[1])


def test_quiz_option_explanations_match_the_options():
    q = {"prompt": "p", "options": ["a", "b"], "correct": [0], "explanation": "e", "explanations": ["yes", "no", "extra"]}
    assert any("explanations" in e for e in check_one("quiz", {"questions": [q]})[1])


def test_every_component_tells_the_model_when_to_use_it():
    from course_factory.catalogue import describe
    assert all("(Use " in line for line in describe().splitlines())


def test_a_single_correct_index_becomes_a_list():
    q = {"prompt": "p", "options": ["a", "b"], "correct": 1, "explanation": "e"}
    assert heal("quiz", {"questions": [q]})["questions"][0]["correct"] == [1]


def test_diagram_labels_with_line_breaks_and_math_render():
    data = heal("diagram", {"mermaid": 'flowchart TD\n  A["$(M_n)_{n\\\\geq 0}$<br/>suite"] --> B{"Condition 1<br/>Adaptation"}'})
    assert "{n\\geq 0}" in data["mermaid"]  # escaped twice by the model, it would show a line break and "geq"


def test_a_formula_written_as_code_in_text_is_flagged():
    def errs(component, data):
        _, (e,) = check_blocks([{"component": component, "origin": "model_added", "citations": [], "data": data}], {})
        return e
    assert any("as LaTeX" in e for e in errs("diagram", {"mermaid": 'flowchart TD\n  A["lim E(e^(iu.X_n))"] --> B'}))
    assert any("as LaTeX" in e for e in errs("prose", {"markdown": "The density is 1/sqrt(2*pi)*exp(-x**2/2)."}))
    assert errs("prose", {"markdown": "**Bold** $\\sqrt{n}$ and `x**2` in code."}) == []
    assert errors_of({"expr": "exp(x)", "op": "diff", "expected": "exp(x)"}) == []  # claims are sympy syntax


def test_a_diagram_given_as_nodes_and_edges_compiles_to_mermaid_that_renders():
    raw = {"component": "step_diagram", "origin": "model_added", "citations": [], "data": {
        "nodes": {"start": "Définition<br/>$\\lim \\mathbb{E}(e^{iuX_n})$", "end": "1. Fin, dit \"stop\""},
        "edges": [["start", "end", "donne"]],
        "steps": [{"highlight": ["end"], "edges": [["start", "end"]], "caption": "c"}]}}
    (block,), (errors,) = check_blocks([raw], {})
    assert errors == []
    src = block["data"]["mermaid"]
    assert 'n_end["1#46; Fin, dit #quot;stop#quot;"]' in src  # "end" is a Mermaid keyword; a list-like start and quotes are escaped
    assert block["data"]["steps"][0]["highlight"] == ["n_end"] and not block["data"]["nodes"]


def test_a_diagram_edge_to_a_missing_node_is_flagged():
    _, (errors,) = check_blocks([{"component": "diagram", "origin": "model_added", "citations": [],
                                  "data": {"nodes": {"A": "a"}, "edges": [["A", "B"]]}}], {})
    assert any("not in nodes: B" in e for e in errors)


def test_field_names_the_model_writes_instead_are_healed_not_repaired():
    """From mlops: these names cost about 60 repair calls (~20 min) in one Course."""
    q = {"question": "p", "options": ["a", "b"], "correct": 1, "explanations": ["no", "yes"]}
    assert heal("quiz", {"questions": [q]})["questions"][0].items() >= {"prompt": "p", "explanation": "yes"}.items()
    blank = heal("fill_blanks", {"title": "t", "template": "[[1]] [[2]]", "blanks": [{"n": 1, "accepted": ["a"]}, {"answer": "b"}]})["blanks"]
    assert [b["answers"] for b in blank] == [["a"], ["b"]]
    entry = heal("terminal", {"entries": [{"input": "ls", "output": "x", "comment": "lists"}]})["entries"][0]
    assert (entry["command"], entry["note"]) == ("ls", "lists")
    step = heal("step_diagram", {"mermaid": "flowchart LR\n  A[a] --> B[b]", "steps": [{"node": "A", "caption": "c"}]})["steps"][0]
    assert step["highlight"] == ["A"]
    assert heal("theorem_box", {"kind": "definition", "statement": "s", "proof": None})["proof"] == ""
    q = heal("quiz", {"questions": [{"question": "p", "options": [{"text": "a", "correct": False, "explanation": "no"},
                                                               {"text": "b", "correct": True, "explanation": "yes"}]}]})["questions"][0]
    assert (q["options"], q["correct"], q["explanation"]) == (["a", "b"], [1], "yes")
    q = heal("quiz", {"questions": [{"question": "p", "options": ["a", "b"], "correct_index": 0, "explanation": ["yes", "no"]}]})["questions"][0]
    assert (q["correct"], q["explanation"], q["explanations"]) == ([0], "yes", ["yes", "no"])
    assert heal("terminal", {"entries": [{"cmd": "ls", "description": "d"}]})["entries"][0]["command"] == "ls"


def test_a_block_without_origin_takes_it_from_its_citations():
    (b,), (errors,) = check_blocks([{"component": "prose", "data": {"markdown": "m"}, "citations": [{"source": "a.pdf", "page": 1}]}], {"a.pdf": 1})
    assert errors == [] and b["origin"] == "from_source"


def test_markdown_bold_inside_a_word_is_not_ascii_math():
    """From mlops: "**D**éveloppeurs **G**èrent" was flagged as a formula 15 times."""
    assert heal("callout", {"tone": "tip", "text": "**D**éveloppeurs **G**èrent **C**ode, **M**a **R**egistre, x"})["text"]
    _, (e,) = check_blocks([block("prose", {"markdown": "so x**2 grows"})], {})
    assert any("as LaTeX" in m for m in e)


def test_shapes_from_the_mlops_review_are_healed_or_accepted():
    """Flagged Blocks found reviewing mlops (2026-11-10)."""
    step = heal("step_diagram", {"mermaid": "flowchart LR\n  T1[a] --> T2[b]", "steps": [{"target": "T1", "caption": "c", "highlight": True}]})["steps"][0]
    assert step["highlight"] == ["T1"]
    src = heal("diagram", {"mermaid": "flowchart TD\n  A[Client] --> B[Web Server : Uvicorn (ASGI)]\n  B --> F[(Database MySQL)]"})["mermaid"]
    assert 'B["Web Server : Uvicorn (ASGI)"]' in src and "F[(Database MySQL)]" in src  # a cylinder keeps its shape
    console = {"title": "t", "language": "json", "template": 'PUT /[[1]]\n{"settings": {"number_of_replicas": [[2]]}}',
               "blanks": [{"answers": ["mlflow-metrics"]}, {"answers": ["0"]}]}
    assert heal("fill_blanks", console)  # an Elasticsearch console request: a request line, then JSON


def test_chinese_slipped_into_a_french_block_is_an_error():
    draft = {"component": "callout", "data": {"tone": "tip", "text": "ce qui élimine l'瓶颈 I/O de MapReduce."}, "origin": "model_added"}
    (_,), (errors,) = check_blocks([draft], {})
    assert any("瓶颈" in e for e in errors)
    draft["data"]["text"] = "ce qui élimine le goulot d'étranglement I/O — « Spark » ≠ Hadoop."
    (_,), (errors,) = check_blocks([draft], {})
    assert errors == []
