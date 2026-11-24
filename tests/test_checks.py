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


@pytest.mark.parametrize("claim", [  # real ops from Traces that failed with "claims.N.op: Input should be ..."
    {"expr": "(1/3)*(0**2 + 1**2 + 1**2)", "op": "eq", "expected": "2/3"},
    {"expr": "Abs(1) + Abs(-2) + Abs(3)", "op": "==", "expected": "6"},
    {"op": "equals", "expr": "diff(-log(1/(1+exp(-x))), x)", "expected": "-exp(-x)/(1+exp(-x))"},
    {"op": "gradient", "expr": "x**2 + y**2 + x*y", "expected": "2*x + y, x + 2*y", "vars": ["x", "y"]},
    {"expr": "1/2*(10*x1**2 + 180*x1*x2) - 123*x1", "op": "derivative", "var": "x1", "expected": "10*x1 + 90*x2 - 123"},
    {"op": "hessian_eigenvalues", "expr": "x**2 + y**2 + x*y", "expected": "1, 3", "vars": ["x", "y"]},  # dropped
    {"expr": "1/2*(A*exp(eps)*sin(om))**2", "op": "d/dA", "expected": "A*exp(2*eps)*sin(om)**2"},  # dropped
])
def test_claim_ops_the_model_aliases_are_not_schema_errors(claim):
    assert errors_of(claim) == []


@pytest.mark.parametrize("claim", [  # real sympy-wrong false alarms: x1 read as x*1, lam as l*a*m
    {"op": "equal", "expr": "2*x1**2 + 2*x1*x2 + 2*x2**2", "vars": [], "expected": "x1**2 + x2**2 + (x1+x2)**2"},
    {"op": "diff", "expr": "(w1**2 + w2**2 - 2*w1*a - 2*w2*b + c)/n", "vars": ["w1"], "expected": "2*(w1 - a)/n"},
    {"op": "equal", "expr": "diff((w1**2 + w2**2 - 2*w1*a - 2*w2*b + c)/n, w1)", "vars": [], "expected": "2*(w1 - a)/n"},
    {"op": "equal", "expr": "diff(2*(w1**2 + w2**2)/n + 2*lam*w1, w1)", "vars": [], "expected": "4*w1/n + 2*lam"},
])
def test_multi_letter_and_indexed_names_are_one_symbol(claim):
    assert errors_of(claim) == []


@pytest.mark.parametrize("claim", [  # real sympy-wrong false alarms: a value at a point the claim never names
    {"op": "equal", "expr": "diff((x-1)**2 + (x-3)**2, x)", "vars": [], "expected": "-8"},
    {"op": "diff", "expr": "(x-1)**2 + (x-3)**2", "vars": ["x"], "expected": "-8"},
    {"op": "hessian", "expr": "x**2 + y**3 - 3*y", "vars": ["x", "y"], "expected": [["2", "0"], ["0", "6"]]},
    {"op": "equal", "expr": "x**2 + y**3 - 3*y", "vars": [], "expected": "[2*x, 3*y**2 - 3]"},  # a gradient under equal
    {"op": "equal", "expr": "10*x1 + 90*x2 - 123", "vars": [], "expected": "0"},  # one equation of a system
    # diff without vars: the variable is whichever one matches
    {"op": "diff", "expr": "1/2*(x**2 + 4*y**2)", "vars": [], "expected": "4*y"},
    {"op": "diff", "expr": "1/2*(A*exp(eps)*sin(om))**2", "vars": [], "expected": "A**2*exp(2*eps)*sin(om)*cos(om)"},
    {"op": "equal", "expr": "-2*log(1/(1+exp(-w)))", "vars": [], "expected": "2*log(1+exp(-w))"},  # a log identity
])
def test_a_claim_sympy_cannot_decide_is_skipped(claim):
    assert errors_of(claim) == []


@pytest.mark.parametrize("claim", [  # real wrong claims the model made: still errors
    {"op": "equal", "expr": "(1/4)*1 + (1/4)*2 + (1/2)*4", "vars": [], "expected": "15/4"},
    {"op": "equal", "expr": "diff(x**2 + y**2 + a*x*y - 2*x - 2*y, x, 2)", "vars": [], "expected": "2 + a"},
    {"op": "diff", "expr": "1/2*(x1**2 + 2*x1*x2 + 4*x2**2)", "vars": ["x1"], "expected": "x1 + 2*x2"},
    {"op": "diff", "expr": "1/2*(x**2 + 4*y**2)", "vars": [], "expected": "3*y"},
])
def test_a_wrong_claim_the_model_made_is_an_error(claim):
    assert [e for e in errors_of(claim) if e.startswith("sympy:")]


@pytest.mark.parametrize("claim, wrong", [  # a claim that names its point is checked at that point
    ({"op": "diff", "expr": "(x-1)**2 + (x-3)**2", "vars": ["x"], "at": {"x": "0"}, "expected": "-8"}, False),
    ({"op": "diff", "expr": "(x-1)**2 + (x-3)**2", "vars": ["x"], "at": {"x": "0"}, "expected": "-10"}, True),
    ({"op": "value", "expr": "x**2 + y**3 - 3*y", "point": [0, 1], "expected": "-2"}, False),  # Trace 573
    ({"op": "value", "expr": "x**2 + y**3 - 3*y", "point": [0, 1], "expected": "-1"}, True),  # Trace 564: f(0,1) = -2
    ({"op": "hessian_at_point", "expr": "x**2 + y**3 - 3*y", "point": [0, 1], "expected": "[[2, 0], [0, 6]]"}, False),
    ({"op": "hessian_at_point", "expr": "x**2 + y**3 - 3*y", "point": [0, 1], "expected": "[[2, 0], [0, -6]]"}, True),
    ({"op": "eval", "expr": "(4-x)**2/2", "var": "x", "at": "1", "expected": "9/2"}, False),
    ({"op": "eval", "expr": "(4-x)**2/2", "var": "x", "at": "1", "expected": "7/2"}, True),
])
def test_a_claim_at_a_point_is_checked_there(claim, wrong):
    assert bool([e for e in errors_of(claim) if e.startswith("sympy:")]) == wrong


@pytest.mark.parametrize("claim", [
    {"op": "equal", "expr": "x**2 + 1", "vars": [], "expected": "0"},  # no real point gives 0: wrong wherever it is taken
    {"op": "diff", "expr": "exp(x)", "vars": ["x"], "expected": "-1"},
    {"op": "equal", "expr": "x**2 + y**2", "vars": [], "expected": "[2*x, 3*y]"},  # a gradient written under equal
    {"op": "equal", "expr": "x**2 + y**2", "vars": [], "expected": "[[2, 0], [0, 3]]"},  # a Hessian written under equal
])
def test_a_claim_with_no_point_is_still_an_error_when_no_point_fits(claim):
    assert [e for e in errors_of(claim) if e.startswith("sympy:")]


def test_an_aliased_op_still_catches_a_wrong_value():
    assert [e for e in errors_of({"expr": "(1/3)*(0**2 + 1**2 + 1**2)", "op": "eq", "expected": "1/3"}) if e.startswith("sympy:")]


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


def test_a_matrix_row_break_before_a_letter_is_kept():
    """Course 12 Block 4542: the heal for "\\rho" escaped twice turned the row break of (s s \\ s t) into "\\s", a KaTeX
    error no repair could fix, since the heal ran again on every repair and on the owner's own edit."""
    md = r"$(B_s,B_t)\sim\mathcal{N}(0, \begin{pmatrix}s&s\\s&t\end{pmatrix})$ et $\\rho = \\frac{1}{2}$"
    assert heal("recap", {"takeaways": [md, "b"], "can_do": ["c"]})["takeaways"][0] == \
        r"$(B_s,B_t)\sim\mathcal{N}(0, \begin{pmatrix}s&s\\s&t\end{pmatrix})$ et $\rho = \frac{1}{2}$"


def test_latex_escapes_outside_math_become_text():
    md = r"$$a$$\nLa mise $\nabla f$ ok\n- b; $x$;\quad $y$ \neq"
    assert heal("prose", {"markdown": md})["markdown"] == "$$a$$\nLa mise $\\nabla f$ ok\n- b; $x$; $y$ \\neq"


def test_diagram_labels_starting_like_a_markdown_list_are_escaped():
    src = 'flowchart TD\n  A["1. start"] -->|"+ J convexe"| B["- end"] --> C --> D'
    assert heal("diagram", {"mermaid": src, "caption": "c"})["mermaid"] == \
        'flowchart TD\n  A["1#46; start"] -->|"#43; J convexe"| B["#45; end"] --> C --> D'


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
    "fill_blanks": {"task": "Write the Dockerfile of a slim Python 3.12 image.", "title": "Dockerfile", "language": "dockerfile", "template": "FROM [[1]]\nWORKDIR /app\n[[2]] . .",
                    "blanks": [{"answers": ["python:3.12-slim"], "regex": "python:3\\.1[0-3](-slim)?"}, {"answers": ["COPY", "ADD"], "hint": "copies files in"}]},
    "code_exercise": {"title": "Containerise the app", "task": "Write a Dockerfile for `app.py`.", "language": "dockerfile",
                      "starter": "FROM python:3.12-slim\n# TODO", "solution": DOCKERFILE, "hints": ["Start from a Python image."]},
    "surface_plot": {"title": "Rosenbrock", "expr": "(1 - x)**2 + 100*(y - x**2)**2", "x_range": [-2, 2], "y_range": [-1, 3]},
    "optimizer_animation": {"title": "GD on a bowl", "expr": "x**2 + 10*y**2", "method": "gradient", "start": [2, 1], "step": 0.05},
    "step_diagram": {"mermaid": "flowchart LR\n  A[Client] --> B[LB] --> C[App]", "steps": [
        {"highlight": ["A"], "caption": "The client sends a request"}, {"highlight": ["B", "C"], "edges": [["B", "C"]], "caption": "The load balancer forwards it"}]},
    "terminal": {"entries": [{"command": "docker build -t app .", "output": "Successfully tagged app:latest", "note": "Builds the image"}]},
    "exercise": {"title": "t", "statement": "s", "correction": "c", "mode": "hand", "steps": ["a", "b"]},
    "intuition": {"idea": "Le gradient indique la direction où $f$ monte le plus vite.", "analogy": "Sur une colline, c'est la ligne de plus grande pente.",
                  "limits": "Une colline a deux dimensions ; $f$ peut en avoir mille."},
    "misconception": {"belief": "Un pas plus grand converge toujours plus vite.", "why_wrong": "Au-delà de $2/L$ les itérés divergent.",
                      "correct": "Le pas doit rester sous $2/L$ ; le meilleur est près de $1/L$."},
    "recap": {"takeaways": ["Le gradient pointe vers la montée la plus forte.", "La descente suit $-\\nabla f$."],
              "can_do": ["Écrire une itération de descente de gradient."]},
    "explain_back": {"concept": "pas fixe", "prompt": "Expliquez pourquoi un pas trop grand fait diverger la descente.",
                     "rubric": ["L'itéré dépasse le minimum", "L'écart grandit à chaque pas au-delà de $2/L$"],
                     "model_answer": "Avec un pas trop grand, chaque itération saute au-delà du minimum et l'écart grandit."},
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


def dockerfile_blanks(template, answers):
    return {"title": "Dockerfile", "task": "Containerise the FastAPI service on port 8080.", "language": "dockerfile",
            "template": template, "blanks": [{"answers": [a]} for a in answers]}


def test_a_dockerfile_that_would_fail_to_build_or_start_is_flagged():
    # Qwen 3.8 (eval 2026-11-21): several sources into a path with no trailing slash fail at docker build
    errors = check_one("fill_blanks", dockerfile_blanks("FROM python:3.11\nCOPY app.py requirements.txt [[1]]\nRUN pip install -r requirements.txt\n"
                                                        "CMD [\"python\", \"/srv/app.py\"]", ["/srv"]))[1]
    assert any("must be a directory ending in /" in e for e in errors), errors
    # Inkling 2 Mini (same eval): only the requirements are copied, so uvicorn finds no service.py at start
    errors = check_one("fill_blanks", dockerfile_blanks("[[1]] python:3.11\nWORKDIR /srv/api\nCOPY [[2]] .\nRUN pip install -r service-requirements.txt\n"
                                                        "CMD [\"uvicorn\", \"service:app\", \"--host\", \"0.0.0.0\", \"--port\", \"8080\"]",
                                                        ["FROM", "service-requirements.txt"]))[1]
    assert any("'service'" in e and "no COPY/ADD" in e for e in errors), errors


@pytest.mark.parametrize("dockerfile", [
    "FROM python:3.11\nWORKDIR /srv\nCOPY requirements.txt predict.py .\nCMD [\"python\", \"predict.py\"]",
    "FROM python:3.9.1\nCOPY ./requirements.txt ./\nWORKDIR /app\nCOPY ingest_data.py ingest_data.py\nENTRYPOINT [ \"python\", \"ingest_data.py\" ]",
    "FROM python:3.9\nCOPY . /app\nWORKDIR /app\nCMD [\"uvicorn\", \"app:app\", \"--host\", \"0.0.0.0\", \"--port\", \"8000\"]",
    "FROM python:3.12\nCOPY --chown=app requirements.txt src/ /code/\nCMD gunicorn src.main:app -b 0.0.0.0:80",
    "FROM python:3.12\nCMD [\"python\", \"app.py\"]",  # nothing copied: a bind-mounted dev image
])
def test_a_working_dockerfile_passes(dockerfile):
    assert check_one("code", {"language": "dockerfile", "code": dockerfile})[1] == []


def test_a_blank_regex_must_work_in_the_app():
    postman = {"title": "Postman", "task": "Test POST /predict on localhost:8000 with surface = 95 and etages = 2.", "language": "",
               "template": "Méthode : [[1]]\nBody JSON : [[2]]", "blanks": [
                   {"answers": ["POST"], "regex": "POST"},
                   {"answers": ['{"surface": 95, "etages": 2}'], "regex": r'\{\s*"surface"\s*:\s*95\s*,\s*"etages"\s*:\s*2\s*\}'}]}
    assert check_one("fill_blanks", postman)[1] == []
    # Inkling 2 Mini (eval 2026-11-21): the escapes written twice match a backslash, so no typed body is ever accepted
    twice = postman | {"blanks": [postman["blanks"][0], postman["blanks"][1] | {"regex": r'\\{\\s*"surface"\\s*:\\s*95\\s*,\\s*"etages"\\s*:\\s*2\\s*\\}'}]}
    assert any("matches none of the accepted answers" in e for e in check_one("fill_blanks", twice)[1])
    # and "(?i)POST" throws in the browser's RegExp, so the regex never matches there
    flags = postman | {"blanks": [{"answers": ["POST"], "regex": "(?i)POST"}, postman["blanks"][1]]}
    assert any("Python-only" in e for e in check_one("fill_blanks", flags)[1])


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


def test_a_quiz_answer_written_as_text_is_an_index():
    q = {"prompt": "p", "options": ["a", "b"], "correct": "1", "explanation": "e"}
    assert check_one("quiz", {"questions": [q]})[0]["questions"][0]["correct"] == [1]


def test_every_component_tells_the_model_when_to_use_it():
    from course_factory.catalogue import describe
    components, shapes = describe().split("\nShapes used above:\n")
    assert all("(Use " in line for line in components.splitlines())
    assert "- QuizQuestion {prompt: str, options: list[str], correct: list[int]" in shapes  # the model no longer guesses these


def test_a_single_correct_index_becomes_a_list():
    q = {"prompt": "p", "options": ["a", "b"], "correct": 1, "explanation": "e"}
    assert heal("quiz", {"questions": [q]})["questions"][0]["correct"] == [1]


def test_diagram_labels_with_line_breaks_and_math_render():
    data = heal("diagram", {"mermaid": 'flowchart TD\n  A["$(M_n)_{n\\\\geq 0}$<br/>suite"] --> B{"Condition 1<br/>Adaptation"} --> C --> D'})
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
    _, (e,) = check_blocks([block("callout", {"tone": "tip", "text": "**G**it**H**ub **A**ctions"})], {})
    assert e == []  # mlops repair_block traces: "t**H" was read as t to the power H


def test_a_visual_that_shows_nothing_more_than_the_text_is_an_error():
    """Course 6, block 1514: Armijo's bound and the merit function drawn as two unlabelled curves."""
    armijo = {"title": "Fonction de mérite et borne d'Armijo", "x_range": [0.0, 1.0], "functions": [
        {"expr": "256*x**4 - 256*x**3 + 100*x**2 - 20*x + 2", "label": ""}, {"expr": "2 - 18*x", "label": ""}]}
    assert any("label" in m for m in check_one("plot", armijo)[1])
    named = [f | {"label": n} for f, n in zip(armijo["functions"], ["$\\varphi_k$", "borne d'Armijo"])]
    assert check_one("plot", armijo | {"functions": named})[1] == []
    two = {"mermaid": 'flowchart LR\n  a["données"] --> b["modèle"]', "caption": "c"}
    assert any("only 2 elements" in m for m in check_one("diagram", two)[1])
    markov = {"mermaid": 'graph LR\n  B -->|"1/2"| P\n  B -->|"1/2"| N\n  P -->|"1/4"| B\n  N -->|"1/4"| P', "caption": "météo"}
    assert check_one("diagram", markov)[1] == []  # 3 states, 4 transitions: course 2's weather chain is worth drawing
    big = {"mermaid": "flowchart LR\n  " + " --> ".join(f"n{i}" for i in range(11)), "caption": "c"}
    assert any("11 nodes" in m for m in check_one("diagram", big)[1])
    dag = {"mermaid": 'flowchart TD\n  r["textFile"]\n  c["collect()  [ACTION]"]\n  r -->|"narrow"| m["map"]\n  m --> c --> d["driver"]', "caption": "c"}
    assert check_one("diagram", dag)[1] == []  # a bracket inside a quoted label is still a label (block 1120)


def test_shapes_from_the_mlops_review_are_healed_or_accepted():
    """Flagged Blocks found reviewing mlops (2026-11-10)."""
    step = heal("step_diagram", {"mermaid": "flowchart LR\n  T1[a] --> T2[b]", "steps": [{"target": "T1", "caption": "c", "highlight": True}]})["steps"][0]
    assert step["highlight"] == ["T1"]
    src = heal("diagram", {"mermaid": "flowchart TD\n  A[Client] --> B[Web Server : Uvicorn (ASGI)]\n  B --> F[(Database MySQL)]\n  B --> R[Redis]"})["mermaid"]
    assert 'B["Web Server : Uvicorn (ASGI)"]' in src and "F[(Database MySQL)]" in src  # a cylinder keeps its shape
    console = {"title": "t", "task": "Create the index mlflow-metrics with no replica.", "language": "json", "template": 'PUT /[[1]]\n{"settings": {"number_of_replicas": [[2]]}}',
               "blanks": [{"answers": ["mlflow-metrics"]}, {"answers": ["0"]}]}
    assert heal("fill_blanks", console)  # an Elasticsearch console request: a request line, then JSON


def test_chinese_slipped_into_a_french_block_is_an_error():
    draft = {"component": "callout", "data": {"tone": "tip", "text": "ce qui élimine l'瓶颈 I/O de MapReduce."}, "origin": "model_added"}
    (_,), (errors,) = check_blocks([draft], {})
    assert any("瓶颈" in e for e in errors)
    draft["data"]["text"] = "ce qui élimine le goulot d'étranglement I/O — « Spark » ≠ Hadoop."
    (_,), (errors,) = check_blocks([draft], {})
    assert errors == []


def test_a_python_solution_that_crashes_when_run_is_an_error():
    from course_factory.checks import _lab_image_built, run_errors
    if not _lab_image_built():
        pytest.skip("the Lab image is not built")
    assert run_errors("import numpy as np\nprint(np.ones(3).dot(np.ones((1, 1))))")[0].startswith("the solution crashes when run: ValueError")
    assert run_errors("import numpy as np\nprint(np.ones(3).dot(np.ones(3)))") == []
    assert run_errors("import pyspark_that_is_not_installed") == []  # a module the image lacks is not the solution's fault
    assert run_errors("df = spark.read.json('x')") == []  # a fragment written for a Spark shell


def test_a_citation_matches_a_file_name_whose_apostrophe_is_typed_differently():
    """From proba2: the file is "gain d’une stratégie.pdf", the model cited "gain d'une stratégie.pdf"."""
    (b,), (errors,) = check_blocks([{"component": "prose", "data": {"markdown": "m"}, "citations": [{"source": "gain d'une.pdf", "page": 1}]}],
                                   {"gain d’une.pdf": 2})
    assert errors == [] and b["citations"][0]["source"] == "gain d’une.pdf"


def test_a_correction_that_argues_with_itself_is_rejected():
    """From proba2 Block 2540: the marked answer was 7, the explanation said "Attendez — relisons … Total = 6"."""
    quiz = lambda text: {"component": "quiz", "data": {"questions": [{"prompt": "p ?", "options": ["6", "7", "9"], "correct": [0], "explanation": text}]}}  # noqa: E731
    _, (bad, good) = check_blocks([quiz("Total : 6. Attendez — relisons : 2+3+1."), quiz("Attendez-vous à 6 arcs : 2+3+1.")], {})
    assert "argues with itself" in bad[0] and good == []


def test_a_code_gap_text_without_its_task_is_rejected():
    """From Advanced BD Block 1180: a `bool` query with five gaps and no task, so `gte` against `gt` was a guess."""
    assert "task" in check_one("fill_blanks", GOOD["fill_blanks"] | {"task": ""})[1][0]


def test_dollars_in_a_code_span_are_not_math():
    """A Makefile's $(VENV_DIR) in a fenced block is code: remark-math leaves it alone, so the check must too (Block 3597)."""
    from course_factory.checks import math_in
    text = "Le Makefile :\n\n```makefile\ninstall:\n\t. $(VENV_DIR)/bin/activate && pip install -r requirements.txt\n```\n\nEt `$HOME` puis $x^2$."
    assert math_in({"text": text}) == [("x^2", False)]


# The real Course 14 (SAPUI5) quiz Inkling wrote: the right option is the long, specific one in most questions.
MANIFEST = [
    {"prompt": "Le fichier manifest.json contient...", "correct": [2], "explanation": ".", "options": [
        "les éléments graphiques (UI Controls)", "la partie logique et les event handler des controls UI5",
        "la configuration de l'application : i18n file, les modèles, les routes, les datasource", "la page HTML qui lance l'application standalone"]},
    {"prompt": "Quel fichier constitue le point d'entrée de l'application SAPUI5 ?", "correct": [1], "explanation": ".", "options": [
        "manifest.json", "Component.js (extends sap.ui.core.Component)", "index.html", "App.view.xml (sap.m.App)"]},
    {"prompt": "Que contient un fichier .controller.js ?", "correct": [2], "explanation": ".", "options": [
        "les éléments graphiques (UI Controls)", "la configuration de l'application (i18n, modèles, routes, datasource)",
        "la partie logique de l'application et les event handler des contrôles UI5", "la page HTML de lancement standalone"]}]


def test_a_quiz_whose_right_option_is_clearly_the_longest_goes_to_repair():
    from course_factory.failures import failure_class
    errs = check_one("quiz", {"questions": MANIFEST})[1]
    assert [failure_class(e) for e in errs] == ["quiz-cue"] and "questions 1, 2" in errs[0]
    even = [q | {"options": [o if i == q["correct"][0] else o + " (" + "x" * 40 + ")" for i, o in enumerate(q["options"])]} for q in MANIFEST]
    assert check_one("quiz", {"questions": even})[1] == []  # wrong options as long: no cue
    one = MANIFEST[0] | {"options": ["UI", "la configuration de l'application : i18n, modèles, routes", "HTML", "JS"], "correct": [1]}
    assert "question 1" in check_one("quiz", {"questions": [one]})[1][0]  # one right option twice as long gives that question away
    names = {"prompt": "Laquelle est annexe ?", "correct": [2], "explanation": ".", "options": ["sap.ca", "sap.ui.table", "sap.ui.richtexteditor", "sap.me"]}
    assert check_one("quiz", {"questions": [names] * 3})[1] == []  # bare names: their length is the name's
