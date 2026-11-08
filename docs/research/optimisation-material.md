# Research #5: what is in the optimisation course material?

Source: `~/uni/optimisation` (read-only). Inventory done with `pdfinfo`, `pdftotext`, `pdffonts`, `pdfimages`, plus skims of notebooks and exams. Nothing in the source folder was changed.

## Short answer

- 276 pages across 24 PDFs, 6 Jupyter notebooks, 2 identical CSVs (about 23k rows of air-quality data), and some Python and HTML visualisation code.
- Almost everything is French. Only some table-of-contents labels and two HTML lab titles are English.
- About 249 pages have a usable text layer. About 27 pages are image-only: 18 pages of handwritten Samsung Notes (`downloadfile(1).PDF`, `downloadfile(2).PDF`) and 9 pages at the front of `samsung_notes_avec_visuels.pdf`.
- Every TD and TP has a correction. The 23/24 exam has a paper and a correction. The 24/25 file is only the correction, so the question paper is missing.
- The exams are mostly the same few kinds of task: gradient and Hessian computation, convexity and existence/uniqueness arguments, a few hand-run iterations of Newton, gradient descent or SGD, and short Python functions (loss, gradient, line search).

## Inventory

Pages come from `pdfinfo`. "Text" means `pdftotext` returned characters for the pages. Chars per page are the average over the whole file.

### chap1 (optimisation fundamentals, descent intuition)

| File | Type | Pages | Text or scan | Lang | Content | Correction |
|---|---|---|---|---|---|---|
| `Optimisation_pour_le_ML_CH1_5DS_2627.pdf` | Beamer slides | 22 | Text (449 chr/p) | FR | Ch. 1 course: formulation, existence and uniqueness, optimality conditions | None separate |
| `1.1.pdf` | Slides (third-party course, "Partie 1") | 26 | Text (308 chr/p), 10 images | FR | Motivations, example problems (constrained and unconstrained) | None |
| `Optimisation_pour_le_ML_TD1_5DS_2627.pdf` | Beamer slides | 14 | Text (534 chr/p) | FR | TD1 in slide form: Exercises 1 to 6, Exercise 6 marked asynchronous, Exercise 5 starred | Refers to `Correction TD1.pdf` |
| `TD1-1.pdf` | TeX exercise sheet | 3 | Text (843 chr/p) | FR | TD1: 6 exercises on differentiability, critical points, convexity, and one Bernoulli/probability question | `Correction TD1.pdf` |
| `Correction TD1.pdf` | TeX correction | 5 | Text (874 chr/p) | FR | Corrections for TD1 | Correction itself |
| `downloadfile(1).PDF` | Samsung Notes export, handwritten | 9 | **Image only** (JPEG, 1800x1272, 212 ppi) | FR (handwritten, grid paper) | Handwritten intro notes: norms on R^n, optimisation intro | None |
| `downloadfile(2).PDF` | Samsung Notes export, handwritten | 9 | **Image only** | FR (handwritten) | Same kind of notes, second batch | None |
| `samsung_notes_avec_visuels.pdf` | pypdf-assembled notes | 14 | Mixed: pp. 1-9 image only, pp. 10-14 text (385 to 735 chr/p), 13 images | FR | Typed-up notes with visuals, Taylor/intuition material | None |
| `notes/supplement_visuels.pdf` and `_paysage.pdf` | matplotlib PDFs (portrait and landscape copies) | 5 each | Text, 4 images each | FR | "Visuels d'intuition: la marche sur la colline", companion to Taylor-Young pages | None |
| `taylor-viz/` (Python, `uv`) | Code and figures | n/a | n/a | FR comments | `taylor_viz.py` renders 4 figures (step, curvature, half-factor, 2D Hessian) as PNG and Plotly HTML | n/a |
| `notes/build_supplement.py` | Python | n/a | n/a | FR | Builds the supplement PDFs | n/a |

Chapter 1 topics, from the slide outline: outillage mathématique (norms, scalar product, matrices), formulation of an optimisation problem, existence (continuity and coercivity) and uniqueness (strict convexity), optimality conditions.

### chap2 (gradient descent and Newton)

| File | Type | Pages | Text or scan | Lang | Content | Correction |
|---|---|---|---|---|---|---|
| `Cours - Descente de gradient-1.pdf` | Beamer slides | 26 | Text (528 chr/p), 16 images | FR | Intro activity; gradient descent method; gradient descent on a quadratic; init, iteration, stopping criterion | n/a |
| `Cours - Newton.pdf` | Beamer slides | 21 | Text (593 chr/p), 2 images | FR | Introduction; Newton method (Hessian inversion, local convergence, cost); quasi-Newton (marked out of syllabus); summary | n/a |
| `TD 2 - Descente de gradient (enonce).pdf` | Exercise sheet | 3 | Text (1154 chr/p) | FR | Linear regression as a quadratic problem; existence and uniqueness; fixed and variable step; conditioning and optimal fixed step on a diagonal matrix | Yes, below |
| `TD 2 - Descente de gradient (corrige).pdf` | Correction | 8 | Text (1217 chr/p), 18 images | FR | Corrections to the above | Correction itself |
| `TD 2 - Newton (enonce).pdf` | Exercise sheet | 2 | Text (1028 chr/p) | FR | Newton on a quadratic (one step); a linear-convergence example; a divergence example (non-differentiable at 0) | Yes, below |
| `TD 2 - Newton (corrige).pdf` | Correction | 5 | Text (1326 chr/p), 12 images | FR | Corrections | Correction itself |
| `TD3.ipynb` | Jupyter (Python 3, ipykernel) | n/a | 31 cells (24 code, 7 markdown), 1 image | FR | Eigenvalues, fixed and variable step gradient descent, plotting. Uses numpy, matplotlib, sklearn | Pairs with `correction TD3.ipynb` (31 cells, 7 images) |
| `TP1_descente_gradient_enonce_fr.ipynb` | Jupyter (Python 3) | n/a | 49 cells (26 markdown, 23 code) | FR | Lab on gradient descent in 2D. Part I is theory, then code. Uses numpy, pandas, matplotlib, plotly, contour plots, and `global air pollution dataset.csv` | `TP1_descente_gradient_correction_fr.ipynb` (49 cells, 6 images) |
| `global air pollution dataset.csv` | CSV, 23,463 rows (with header) | n/a | n/a | EN column names | Air-quality AQI data, country, city, AQI per pollutant | n/a |

Note: `TD3.ipynb` in chap2 is not the same as the TD3 PDFs in chap3. The name is reused.

Chapter 2 topics: gradient descent (fixed and variable step, quadratic case, conditioning), Newton (Hessian, local convergence, non-invertible Hessian, cost), eigenvalues of symmetric matrices.

### chap3 (stochastic gradient descent)

| File | Type | Pages | Text or scan | Lang | Content | Correction |
|---|---|---|---|---|---|---|
| `Cours_CH3_descente_gradient_stochastique_fr_v2.pdf` | Beamer slides | 24 | Text (437 chr/p), 14 images | FR | Intro; general principle; SGD; batch GD; worked example: fitting a circle by gradient descent; step choice and summary | n/a |
| `TD3_descente_gradient_stochastique_enonce_fr.pdf` | Exercise sheet | 4 | Text (1095 chr/p), 10 images | FR | Four 1D data points, per-example losses, full vs stochastic gradient, batch iterations with step 0.1 | Yes, below |
| `TD3_descente_gradient_stochastique_corrige_fr.pdf` | Correction | 8 | Text (1492 chr/p), 18 images | FR | Corrections | Correction itself |

Chapter 3 topics: stochastic gradient, mini-batch vs batch vs single sample, epochs, step size, circle-fitting example.

### chap4 (line search)

| File | Type | Pages | Text or scan | Lang | Content | Correction |
|---|---|---|---|---|---|---|
| `Cours_CH4_recherche_lineaire_fr.pdf` | Beamer slides | 17 | Text (458 chr/p), 6 images | FR | Intro; elementary line search (optimal step, phi(rho) = J(x + rho d)); Armijo condition with step halving; Wolfe conditions; summary | n/a |
| `TP4_recherche_linéaire_énoncé_26_27.ipynb` | Jupyter (Python 3) | n/a | 45 cells (26 markdown, 19 code) | FR | Lab on step choice: Part I, Armijo ("steps too large"); later parts on Wolfe. Uses numpy, pandas, matplotlib, a CSV | `TP4_recherche_linéaire_correction_fr__26_27.ipynb` (49 cells, 6 images) |

Chapter 4 topics: line search, Armijo backtracking, Wolfe conditions.

### Root exam folder

| File | Type | Pages | Text or scan | Lang | Content |
|---|---|---|---|---|---|
| `Examen P 2324.pdf` | Exam paper (Nov 2023, 1h30, calculator allowed, no documents) | 8 | Text (3984 chr/p), 6 images | FR | QCU (4 pts), Ex. 1 (8 pts), Ex. 2 (8 pts) |
| `Examen P 2324 Correction.pdf` | Correction | 7 | Text (1380 chr/p) | FR | Corrections; QCU answers marked with glyphs (X = correct, W = wrong) |
| `Corrigé_Exam_Optimisation_SP_2425.pdf` | Correction only (Nov 2024, 1h30) | 7 | Text (1341 chr/p), 4 images | FR | QCU (4 pts), Ex. 1 (10 pts), Ex. 2 (6 pts). Question paper not in the folder |

### revision/

| File | Type | Pages | Text or scan | Lang | Content | Correction |
|---|---|---|---|---|---|---|
| `Introduction à Machine Learning & notions de base.pdf` | Slides | 24 | Text (449 chr/p), 1 image | FR | Basics for optimisation: norms, matrix analysis, differential calculus, convex functions. Includes a Python plotting exercise | None |
| `convex-viz.html` | Interactive lab (HTML) | n/a | n/a | EN title ("convexity lab") | Convex sets and functions | n/a |
| `matrix-viz.html` | Interactive lab (HTML) | n/a | n/a | EN title ("matrices-as-transformations lab") | Matrices as transformations, eigenvalues, quadratic forms | n/a |
| `LEARNING_LOG.md` | Personal tutoring log (7 lines, EN) | n/a | n/a | EN | Learner-model entries from earlier tutoring sessions (quiz scores, weak points). Not course material | n/a |

Also in the folder: `.playwright-mcp/` and `.pi/` directories (tool logs), and `.ruff_cache/`. These are not content.

## Exercises and corrections

- TD1: sheet (`TD1-1.pdf`) and correction (`Correction TD1.pdf`). Also a slide version with Exercises 1 to 6.
- TD2 descente de gradient: sheet and correction. TD2 Newton: sheet and correction.
- TD3 (chap3, SGD): sheet and correction. TD3 notebook (chap2): notebook and correction.
- TP1 (chap2): notebook and correction. TP4 (chap4): notebook and correction.
- Exams: 23/24 has paper and correction. 24/25 has correction only.
- Chapter slides (CH1, CH2 x2, CH3, CH4, `1.1.pdf`, revision intro): no exercises or corrections seen in the skim.

Coverage is complete for the TDs and TPs. The gap is that the 24/25 exam paper is missing, so its QCU wording and layout come only from the correction.

## Exams: content and recurring question types

Both exams are 20 points: QCU (4 pts), Exercise 1, Exercise 2. The 23/24 exam is in French and has no working. The 24/25 correction is full worked solutions, many in proof form.

### 23/24 (Examen P 2324)

- QCU: 8 questions, one correct answer each. Topics: descent direction definition; Hessian of a quadratic; drawback of a fixed step; critical points of x^2 + y^2 + 2xy; Hessian and convexity; strict convexity; coercivity; advantage of SGD.
- Exercise 1 (8 pts): least squares f(X) = 1/2 ||AX - b||^2. Steps: rewrite as 1/2 <A'X, X> - <b', X> + c'; gradient and Hessian; show Hessian is PSD so f is convex; identify A', b', c' for given numbers; show a unique minimiser; one Newton iteration; five SGD iterations by hand.
- Exercise 2 (8 pts): logistic regression. Steps: P(Y | X, w) with the sigmoid; log-likelihood L_n(w); show the cross-entropy form; show the gradient formula; then four Python functions: `LV` (log-likelihood), `Gradient_LV`, a line-search routine, and gradient descent with Armijo step.

### 24/25 (Corrigé_Exam_Optimisation_SP_2425)

- QCU (4 questions): critical points of a cubic in two variables; first-order necessary condition for a differentiable problem; Hessian of a C^2 function is symmetric; variable-step gradient descent (direction is minus the gradient, optimal step is a line minimisation).
- Exercise 1 (10 pts): quadratic J(X) = 1/2 <AX, X> - <b, X> with A symmetric positive definite. Parts: (1) show J is C^1 with gradient AX - b, via a differentiability proof; (2) Hessian A; (3) show a constant c > 0 with the quadratic lower bound; (4) coercivity; (5) existence and uniqueness of the minimiser X* = A^{-1} b; (6) optimal step gradient descent; (7) one Newton iteration; (8) a numerical gradient descent from X0 = (0,0,0): first iterate and a further computation.
- Exercise 2 (6 pts): nonlinear regression F(theta) = 1/2 sum (f(x_i, theta) - y_i)^2 with f(x, theta) = A exp(eps x) sin(omega x). Steps: gradient (three partials given in the correction); Python `f(x, theta)`, `F(X, Y, theta)`, `gradF(X, Y, theta)`; fixed-step gradient descent `descente_de_gradient_pas_fixe(x, y, theta0, rho)`.

### Recurring question types (both exams and TDs)

1. Gradient and Hessian of a quadratic or least-squares function.
2. Convexity: Hessian PSD, strict convexity, coercivity, existence and uniqueness of the minimiser.
3. Hand computation of a few iterations: Newton (usually one), gradient descent (fixed or optimal step), SGD (a few samples).
4. Python: a loss, its gradient, and a descent loop (fixed step, or line search with Armijo).
5. Logistic regression: sigmoid, Bernoulli likelihood, gradient.
6. Multiple-choice (QCU) items testing the same definitions as the proofs.

## Mapping onto course-factory components

- **Theorem boxes:** definitions and results are stated in slide-style boxes already: descent direction, existence (coercivity plus continuity), uniqueness (strict convexity), first-order condition, Hessian criterion for convexity, Armijo and Wolfe conditions, Newton's local convergence, SGD vs batch. Good fit.
- **Proofs (collapsible):** the 24/25 correction and the TD corrections have full proofs, e.g. differentiability of a quadratic via the remainder bound, coercivity from the lower bound, PSD Hessian implies convexity. These fit the collapsible proof component.
- **Worked exercises:** each TD correction pairs with its sheet by filename (`enonce`/`corrige`), except `TD1-1.pdf` which pairs with `Correction TD1.pdf`, and the two chap2/chap3 "TD3" files which need manual pairing. The notebook correction TP1 has a clear split of enonce and correction.
- **Quizzes:** the QCUs have answers, from the correction markers (X = right, W = wrong in the 23/24 correction; a single X per question in the 24/25 correction). The glyphs survive text extraction as plain letters, so the answer key is recoverable, but this should be checked by a human on a few items.
- **Plots:** the course set calls for:
  - level sets (contour plots) of 2D quadratics and of the logistic loss; TP1 has four contour calls and a meshgrid;
  - gradient-descent trajectories over those level sets; TD2 Exercise 2 (conditioning) and TP1 both produce iterate sequences;
  - line-search plots of phi(rho) and Armijo acceptance (chap4 course and TP4);
  - a Taylor-style "marche sur la colline" plot, already built in `taylor-viz/`;
  - the SGD circle-fitting example (chap3), which is a 2D point-cloud plot.
  - Feasible regions: the course has constrained problems in `1.1.pdf`, but the TDs and exams are unconstrained. Low priority.
- **Labs:** TP1 (2D gradient descent, contours, plotly), TP4 (line search, Armijo/Wolfe), TD3 notebook (eigenvalues, fixed and variable step GD, sklearn). The exam's Python tasks (LV, Gradient_LV, gradF, fixed-step descent) are a good model for coding labs with short numpy functions. All labs use Python 3 with numpy, matplotlib, pandas, plotly, and sklearn, in French.

## Ingestion needs

- **Text PDFs (about 249 pages with a text layer):** `pdftotext` works. Math is the problem. Slides and sheets use CM fonts, and `pdftotext` splits fractions, subscripts and matrices into lines, and mangles some symbols. For math-heavy pages the reliable route is a LaTeX-aware extractor (Marker, Nougat, or a vision model reading the page image), then human check. The sources are LaTeX, but only PDFs are available here, so there is no `.tex` to read.
- **Scanned handwriting (18 pages, `downloadfile(1).PDF` and `(2).PDF`):** French handwriting on grid paper, with red headings and some diagrams. Needs OCR for handwriting or a vision model. Also a low priority: the content is the same as the typed Ch.1 slides.
- **Image-only pages in `samsung_notes_avec_visuels.pdf` (pp. 1-9):** same treatment as above.
- **Image-heavy figures:** chap2 cours (16 images) and chap3 corrections (18 images) carry figures, possibly plots. Not checked page by page; extract the figures as images and keep them with their captions.
- **Notebooks:** easy to parse (JSON). Outputs contain images (chap2 corrections, TP4 correction) that can be extracted as-is.
- **CSVs:** both air-pollution files are identical (`cmp` says same). Keep one copy. The file has a UTF-8 BOM.
- **French throughout:** the pipeline's prompts and outputs must handle French. The notebooks' comments are in French too.
- **Private material to exclude:** `revision/LEARNING_LOG.md` is a personal tutoring log, not course content. Do not ingest it into a shared course. The `.playwright-mcp/`, `.pi/` and `.ruff_cache/` folders are tool leftovers.

## Caveats

- Page counts and character counts come from `pdfinfo` and `pdftotext`. Nothing was rendered, so the figure content is inferred from image counts and file names.
- The 23/24 correction's QCU answer key was read from the X/W markers in the text layer. Not checked against the rendered page.
- The 24/25 exam paper is not in the folder. Its questions are inferred from the correction.
- Only the first pages of each chapter and some exam pages were skimmed. Full content was not read.
