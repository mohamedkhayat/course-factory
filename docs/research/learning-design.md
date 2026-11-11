# Learning design: what the Chapter plan and the checks enforce

Researched 2026-11-10 for the Chapter plan (#23). Two reports follow: practice design, then explanations and visuals. Both were
gathered from abstracts and secondary summaries; numbers marked "unverified" need a full-text check before being quoted.
The Course is for one student cramming for an exam, so we keep only rules that are both well supported and checkable.

## Rules we adopt

| Rule | Where it's enforced | Evidence | Strength |
|---|---|---|---|
| Every Section practises after it teaches; never before (no pretests) | #22 progression check, plan order | Roediger & Karpicke 2006; Rowland 2014 (g = 0.50) | strong |
| Every objective has a level (remember, understand, apply, analyse) and at least one practice Block at that level | plan check | Biggs 1996 (constructive alignment); Anderson & Krathwohl 2001 | moderate |
| In Cram, objectives come from the Chapter's Question Types first; every Question Type has an objective | plan check | Wiggins & McTighe 2005 (backward design) | weak, but it is the Course's goal |
| An "apply" objective goes worked example → independent problem (a faded step in between when it has several steps) | plan check | Renkl & Atkinson 2003; Kalyuga et al. 2003 | moderate |
| Recall core ideas by producing them (fill_blanks, short answers); MCQ is for telling confusable things apart | plan prompt | Roediger & Karpicke 2006; Little & Bjork 2016 | moderate |
| Each MCQ distractor is a named misconception from the plan; 3-4 options; no "all/none of the above"; the correct option is not always the longest; every option has feedback | plan + quiz check | Haladyna et al. 2002; Roediger & Marsh 2005; Butler & Roediger 2008 | moderate to strong |
| Interleave look-alike problem types only after each was practised alone (revision Sections) | plan prompt | Brunmair & Richter 2019 (g = 0.42) | moderate |
| A visual only when the relation is a process, structure, fan-out, comparison, cycle, state or quantity; its type matches the relation | plan check | Larkin & Simon 1987; Mayer coherence | strong (direction) |
| A process of more than ~5 stages is a step_diagram the learner steps through | plan check, diagram warning | Mayer segmenting; transient information effect | moderate |
| A diagram stays small (≤ 9 nodes; labels ≤ 6 words), labels on the figure, colour only with meaning | diagram warnings, house theme | Purchase 2002; Mayer spatial contiguity, signalling | weak (numbers), strong (direction) |
| After a worked example or diagram, one question asks the learner why a step holds | write prompt | Chi et al. 1994; Bisra et al. 2018 (g = 0.50) | strong |
| Spaced review | already done by Cards | Cepeda et al. 2008 | strong |

Not adopted: pretesting (Richland et al. 2009) contradicts "never practise what wasn't taught" (#22); adaptive fading thresholds
(no validated number); continuous animation beyond optimizer_animation.


# Evidence for Chapter planning rules (cram-mode self-study)

Sources were checked via search snippets and abstracts. Items marked (unverified) rely on memory or secondary summaries and need a full-text check before citing numbers. Confidence: strong = multiple meta-analyses or replicated lab/field work; moderate = single meta-analysis or several primary studies; weak = small or mixed evidence.

## 1. Retrieval practice

Evidence: Dunlosky, Rawson, Marsh, Nathan & Willingham (2013), Psychological Science in the Public Interest 14(1), 4-58, rates practice testing and distributed practice as "high utility" (https://www.psychologicalscience.org/publications/journals/pspi/learning-techniques.html). Rowland (2014), Psychological Bulletin 140(6), 1432-1463, DOI 10.1037/a0037559 (unverified DOI), pools 159 effects from 61 studies: testing vs restudy g = 0.50, 95% CI [0.42, 0.58]. Rowland excluded classroom studies. Roediger & Karpicke (2006), Psychological Science 17(3), 249-255, DOI 10.1111/j.1467-9280.2006.01693.x: testing beat restudy at 2 days and 1 week, and not at 5 minutes.

Rules:
- Every Section has at least one retrieval block placed after its teaching blocks, not before them in the same session. Strength: strong.
- Retrieval items are free-recall or cued-recall for the core ideas (answer produced from memory), and recognition (MCQ) is used for discrimination among confusable items, not as the main retrieval. Strength: moderate. Basis: Roediger & Karpicke's effect was shown with free recall; Little & Bjork (2016) below shows MCQ benefits, but MCQ alone is less consistently tested.
- Retrieval is repeated at least twice across the cram period (Roediger & Karpicke: delayed tests help more). Strength: moderate.
- Conflict: Rowland's feedback moderator is disputed. A later review reports feedback effects of 0.73 vs 0.39, while Adesope et al. found no feedback moderation (unverified). Treat feedback as a moderator, not a given.

## 2. Worked examples, faded examples, expertise reversal

Evidence: Renkl & Atkinson (2003), Educational Psychologist 38(1), 15-22, propose fading worked steps so problem-solving demands rise as intrinsic load falls. Kalyuga, Ayres, Chandler & Sweller (2003), Educational Psychologist 38(1), 23-31, DOI 10.1207/S15326985EP3801_4 (unverified DOI), describe the expertise reversal: detailed examples help novices but add redundancy for learners with more knowledge. Kalyuga (2007), Educational Psychology Review 19, 509-539, is the main review.

Rules:
- Each objective at "apply" level has a worked example followed by at least one faded example (some steps blank) and at least one independent problem. Strength: moderate.
- Fading is gradual: at least two intermediate steps between the full example and the independent problem, rather than an abrupt switch. Strength: moderate (Renkl et al.: gradual fading beat abrupt switch on near transfer).
- Switch to independent problems early for items the student already answers correctly. Use the learner's pretest or prior correct answers as the expertise signal. Strength: moderate (expertise reversal is well replicated, but the trigger threshold is not standardised).
- No fixed fade rate is supported. The evidence says "gradual" and "adaptive" are better than fixed. Strength: weak for any specific number.

## 3. Interleaving vs blocking

Evidence: Brunmair & Richter (2019), Psychological Bulletin 145(11), 1029-1052, meta-analysis of 59 studies, 238 effects: interleaved beats blocked, g = 0.42, 95% CI [0.34, 0.50]. Blocking beats interleaving for word lists (about g = -0.39, sign per Firth et al.). Note: the search output wrongly listed Educational Research Review; the paper is Psychological Bulletin. Rohrer, Dedrick & Stershic (2015), Journal of Educational Psychology 107, 900-908: 7th-grade maths, d = 0.42 immediate and 0.79 delayed (figures from abstract summaries). Firth et al. (2021), Review of Education, DOI 10.1002/rev3.3266.

Rules:
- Interleave only items from the same Section that look alike but need different solutions (e.g., two formulas, two definitions that are easily confused). Strength: moderate.
- Do not interleave a topic's first exposure. Teach one type with worked examples first, then mix. Strength: moderate. Basis: Brunmair & Richter's moderator analysis shows effects depend on material, and word-list results favour blocking.
- Interleaved sets include at least one item per type, and the mix is planned in the Chapter plan, not left to the local model. Strength: weak (this is a design choice, not a tested rule).

## 4. Spacing within a cram period (days to two weeks)

Evidence: Cepeda, Pashler, Vul, Wixted & Rohrer (2006), Psychological Bulletin 132(3), 354-380: distributed beats massed across 317 experiments. Cepeda, Vul, Rohrer, Wixted & Pashler (2008), Psychological Science 19(11), 1095-1102, DOI 10.1111/j.1467-9280.2008.02209.x: the best gap is about 20% of the test delay for delays of a few weeks, falling to about 5% at one year. Conflict: a secondary review says the spacing effect was not modulated by retention interval, contradicting the 2006 abstract (check the original).

Rules (derived from the 20% ratio, not directly tested for two-week windows):
- For an exam D days away, schedule sessions at roughly 0, 0.2D, 0.4D, 0.8D (for D = 14 this gives days 0, 3, 6, and 11). Strength: moderate for the ratio, weak for this exact schedule.
- No Section's practice is massed into one session. Each Section has at least two practice sessions separated by at least one day. Strength: strong.
- Flashcards use expanding gaps, with the next review after the last one doubled or more. Strength: moderate.

## 5. Writing MCQ items: distractors and misconceptions

Evidence: Haladyna, Downing & Rodriguez (2002), Applied Measurement in Education 15(3), 309-334, DOI 10.1207/S15324818AME1503_5, gives 31 validated item-writing guidelines. Rodriguez (2005), Educational Measurement: Issues and Practice 24(2), 3-13, finds three options are optimal (unverified). Roediger & Marsh (2005), JEP:LMC 31(5), 1155-1159, DOI 10.1037/0278-7393.31.5.1155: prior MCQ testing improved later recall, but lures produced false knowledge. Butler & Roediger (2008), Memory & Cognition 36(3), 604-616, DOI 10.3758/MC.36.3.604: feedback reduced lure intrusions on a delayed test. Little & Bjork (2016), Memory & Cognition 44(7), 1085-1101, DOI 10.3758/s13421-016-0621-z: competitive MCQ pretests helped learning of related, untested information. Pan & Sana (2021) replication found the MC advantage less consistent.

Rules:
- Every MCQ distractor is tied to a named misconception or a plausible confusion from the course material, and the Chapter plan lists it. Strength: moderate (Little & Bjork; Roediger & Marsh).
- Use three options (correct plus two distractors) unless a source needs more; no "all of the above" or "none of the above". Strength: moderate. Basis: Haladyna et al. guidelines; Rodriguez 2005 (unverified).
- Option length, grammar and position do not give away the answer. The correct answer is not systematically the longest. Strength: moderate (Haladyna et al.).
- Every MCQ has feedback that names the misconception. Strength: strong (Butler & Roediger 2008).
- Conflict: MCQ can create false knowledge if feedback is missing. Never serve MCQ without feedback. Strength: strong.

## 6. Feedback: timing and content

Evidence: Hattie & Timperley (2007), Review of Educational Research 77(1), 81-112, DOI 10.3102/003465430298487: average feedback effect d = 0.79 (secondary summaries; a different table reports 0.95, check source). Butler, Karpicke & Roediger (2007), J. Experimental Psychology: Applied 13(4), immediate vs delayed feedback on MCQ (unverified). Butler & Roediger (2008) as above: immediate and delayed both help.

Rules:
- Feedback includes the correct answer and a reason (elaborated). Answer-only feedback is not enough for MCQ and hand exercises. Strength: moderate.
- Immediate feedback for new material; delayed feedback (within the same session or the next day) for retrieval of material already learned. Strength: weak to moderate. Conflict: Butler et al. found delayed feedback helped retention more on some measures and immediate feedback helped more on others; no consistent winner.
- Feedback targets the task and process, not the person (Hattie & Timperley). Strength: moderate.

## 7. Learning objectives and alignment

Evidence: Anderson & Krathwohl (2001), A Taxonomy for Learning, Teaching, and Assessing (Longman; book, not peer-reviewed). Biggs (1996), Higher Education 32, 347-364, DOI 10.1007/BF00138871, on constructive alignment: objectives, teaching and assessment must match. Wiggins & McTighe (2005), Understanding by Design (ASCD; book, not peer-reviewed). Backward design is a planning framework, not a tested effect.

Rules:
- Every objective states a verb from one taxonomy level (remember, understand, apply, analyse). Strength: moderate (taxonomy widely used; validation mixed).
- Every objective maps to at least one practice block whose level matches the objective (recall items for "remember", applied problems for "apply"). Strength: moderate (constructive alignment, Biggs).
- Objectives are taken from the target exam's past questions first, then slides. Strength: weak (backward design is a framework, not an experiment).

## 8. Prerequisites and difficulty ramps

Evidence: Kulik, Kulik & Bangert-Drowns (1990), Review of Educational Research 60(2), 265-299, mastery learning meta-analysis (effect size about 0.5, unverified). Sweller's cognitive load work (Sweller, Ayres & Kalyuga 2011, Springer; book) supports ordering that keeps element interactivity manageable. Renkl & Atkinson (2003) on fading (above).

Rules:
- A Section lists its prerequisite Sections, and the plan does not introduce a concept before its prerequisites are in an earlier Section. Strength: moderate (logical prerequisite; cognitive load).
- Move to the next difficulty level only after a set threshold on the current level (for example, 80% correct across two sessions). Strength: weak to moderate (mastery learning gains are consistent but the threshold is a design choice).
- Ramp difficulty in steps: recall, then faded example, then application, then transfer. Strength: moderate (Renkl & Atkinson).

## 9. Pretesting and generation before instruction

Evidence: Richland, Kornell & Kao (2009), JEP:Applied 15(3), 243-257, DOI 10.1037/a0016496: pretests improved later learning, even though most pretest answers were wrong. Kornell, Hays & Bjork (2009), JEP:LMC 35(4), 989-998 (word pairs). Pan & Sana (2021), JEP:Applied 27: five experiments, pretesting comparable to or above posttesting; mechanism is enhanced processing of passage content. Little & Bjork (2016): benefit reaches untested related material.

Rules:
- Each Section may open with a pretest of 2-4 questions on its key idea before the teaching blocks. Strength: moderate (Richland et al.; Pan & Sana).
- Pretest questions are answerable from the course material the student will read next, not from material outside the Chapter. This resolves the "never quiz on what wasn't taught" concern. Strength: moderate (design rule; the pretesting effect has been replicated with unanswered questions, but the evidence base for quizzing on untaught content is weaker).
- Pretest results are not graded; they only set the expertise signal for fading (see rule 2). Strength: weak (design choice).
- Conflict: Pan & Sana find pretesting comparable to posttesting, while Pan & Agarwal (2018) and others find posttesting stronger in some settings. A 2025 replication found a larger posttest effect. Treat pretesting as a complement to posttesting, not a replacement. Strength: moderate.

## Summary of conflicts

- Feedback moderator of the testing effect (Rowland vs Adesope, unverified).
- Retention interval and spacing (Cepeda 2006 abstract vs secondary review).
- Pretesting vs posttesting (Pan & Sana vs 2025 replication).
- Interleaving: strong for maths and concept discrimination, blocking wins for word lists.

## Citations to verify before use

- Rowland (2014) DOI, Kalyuga et al. (2003) DOI, Brunmair & Richter (2019) DOI, Rodriguez (2005) option count, Butler, Karpicke & Roediger (2007), Kulik et al. (1990) effect size, Hattie & Timperley effect size (0.79 vs 0.95).
- Renkl & Atkinson (2003) and Richland et al. (2009) effect sizes: no values retrieved.

# Evidence for written + diagram lessons: rules for the Chapter planner and diagram checks

Confidence: strong = replicated meta-analysis or multiple reviews; moderate = one review or consistent narrow evidence; weak = secondary source only or mechanism inference.

**Source caveat.** Primary texts were mostly not retrievable. Several effect sizes below come from secondary summaries and conflict across sources. Mermaid's official theming page could not be fetched, so Mermaid rules rest on search snippets. Verify numbers before citing them in a thesis.

## 1. Mayer principles as checkable rules

Sources: Mayer (ed.) *Cambridge Handbook of Multimedia Learning*, 2nd ed. (2014), ch. "Principles for Reducing Extraneous Processing" (Mayer & Fiorella/Pilegard); 2025 independent meta-analysis of Mayer's principles, ScienceDirect, https://www.sciencedirect.com/science/article/pii/S1747938X25000673

- **Coherence:** Each Section has no decorative images, seductive anecdotes or tangential facts. Checkable: every visual and sentence traces to a learning objective in the Chapter plan. Effect: reported median around 0.7 to 0.9 across secondary summaries. Independent meta-analysis (2025) gives overall g = 0.37 across Mayer's work, so expect smaller effects in practice. Confidence: strong for direction, weak for size.
- **Signaling:** The key relation is marked on the figure, for example a highlighted edge and a bold term. Checkable: each diagram has at most one highlighted path per step, and the Section text names it. Effect: reported d around 0.46 in a secondary summary. Confidence: moderate.
- **Spatial contiguity:** Labels sit on or next to their parts, not in a separate legend or a caption that forces eye travel. Checkable: no diagram has a legend block that holds more than 3 meanings. Effect: reported medians of 1.10 (handbook) and d = 0.79 (summary); independent meta-analysis g = 0.63 for integrated designs. Confidence: strong.
- **Redundancy:** Do not repeat the same words on screen and in narration or caption. Checkable: a diagram caption does not restate the Section text verbatim. Effect: reported d around 0.87 to 1.39 across editions. Confidence: moderate, because the effect is larger when the on-screen text is dense.
- **Segmenting:** Break a multi-stage process into user-paced segments. Checkable: a process with more than about 5 steps is split into steps the learner advances. Effect: Rey et al. 2019 (meta-analysis, 88 studies) found small to medium effects; a secondary summary of the 2014 review gives median 0.79. Confidence: moderate.
- **Pre-training:** Name the main components before the process. Checkable: a process diagram is preceded in the Section by a sentence naming each node once. Effect: median 0.75 (2014 review, secondary); stronger for low prior knowledge. Confidence: moderate.

## 2. When a visual helps or hurts

Sources: Larkin & Simon (1987) *Cognitive Science* 11, 65–99, https://onlinelibrary.wiley.com/doi/10.1111/j.1551-6708.1987.tb00863.x; Mayer 2014 handbook (above); Sweller, Ayres & Kalyuga (2011) *Cognitive Load Theory* (Springer).

- **Helps:** Diagrams make relations explicit that sentences leave implicit (Larkin & Simon's "locality" argument). Good candidates are processes, structures, spatial layouts, comparisons across several attributes, and quantitative relations.
- **Hurts:** Decorative or seductive details that add interesting but irrelevant content. Checkable: each node or annotation answers "what does this teach?" Otherwise remove it. Effect: seductive details reduce transfer (Mayer's coherence principle). Confidence: strong.
- **Redundant visuals** repeat the text and add load. Confidence: moderate.
- **Element interactivity (Sweller 2010; secondary):** A diagram with many mutually dependent elements raises intrinsic load. Checkable: a diagram holds no more than about 7 interacting elements; beyond that, split it. Confidence: moderate, because the number is a heuristic, not a measured threshold.

## 3. Static vs animated vs step-by-step

Sources: Höffler & Leutner (2007) *Learning and Instruction* 17(6), 722–738, DOI 10.1016/j.learninstruc.2007.09.013; Tversky, Bauer Morrison & Betrancourt (2002) *IJHCS* 57(4), 247–262, DOI 10.1006/ijhc.2002.1017; Mayer 2014 transient information principle (Cambridge Handbook).

- **Meta-analysis:** Animations beat static pictures overall, d = 0.37 (95% CI 0.25–0.49). The effect is d = 0.40 for representational animations and larger for procedural-motor content (d about 1.06). Later reanalyses find smaller effects, g = 0.23 (Castro-Alonso et al. 2019). Confidence: strong that effect is positive for procedures with change; moderate on size.
- **Tversky et al. (2002):** Animation looks better in many studies only because animated and static versions differ in content. Checkable: a static and step version must show the same content, with only the state change added. Confidence: strong as a design constraint.
- **Transient information effect (Mayer 2014):** Animated information disappears, so learners cannot re-inspect it. Rules: (a) keep each step on screen long enough to read, and (b) give the learner control. Checkable: a step-through diagram has next/previous controls and a "show all" state. Confidence: strong.
- **Use static when:** the learner must compare parts at once or the relation is spatial, not temporal. Use step-by-step when the learner must follow a sequence of state changes. Use continuous animation only when the change itself is the content (for example, optimiser trajectories) and playback is user-controlled. Confidence: moderate.

## 4. Multiple representations (diagram + equation, table, code)

Sources: Ainsworth (2006) "DeFT: A conceptual framework for considering learning with multiple representations," *Learning and Instruction* 16, 183–198, DOI 10.1016/j.learninstruc.2006.03.001; Ainsworth (1999) "The functions of multiple representations," *Computers & Education* 33; Clark & Paivio (1991) "Dual Coding Theory and Education," *Educational Psychology Review* 3(3), 149–210.

- **DeFT's functions:** complementary (different information per representation), constraining (one rules out wrong interpretations of the other), and constructing deeper understanding. Checkable: for each pair (diagram + equation), the Section says which function it serves.
- **Support for linking is required.** Learners need help mapping elements across representations. Checkable: each equation or code line that pairs with a diagram names the diagram element it corresponds to, by the same label. Confidence: moderate.
- **Dual coding:** Verbal and visual codes together improve recall, but dense combinations can reduce understanding (per secondary report of Clark & Paivio). Confidence: moderate for recall, weak for understanding.
- **Rule:** Pair a diagram with an equation only when the Section explains the link. Do not put an equation next to a diagram it does not map to. Confidence: moderate.

## 5. Self-explanation prompts

Sources: Chi, De Leeuw, Chiu & Lavancher (1994) "Eliciting self-explanations improves understanding," *Cognitive Science* 18, 439–477, DOI 10.1207/s15516709cog1803_3; Fiorella & Mayer (2015) *Learning as a Generative Activity* (Cambridge UP); Bisra et al. (2018) *Educational Psychology Review* (meta-analysis, 69 studies, g = 0.50); Renkl (2014) "Toward an instructionally oriented theory of example-based learning," *Cognitive Science* 38 (primary not retrieved; claims below from secondary).

- **Rule:** After each worked example or diagram, ask the learner to explain one step in their own words ("why does this node come after that one?"). Effect: g = 0.50 (Bisra et al. 2018); median about 0.6 in Fiorella & Mayer (secondary). Confidence: strong for the direction.
- **Prompt type:** Use prompts that name the target relation (gap-filling or mental-model prompts). Assisting prompts beat open prompts when learning with multiple representations (Berthold et al. 2009, secondary). Confidence: moderate.
- **Conflict:** Explanations added by the tutor can reduce gains compared with learner-generated explanations (Schworm & Renkl 2006, secondary). Rule: generate the explanation first, then show the tutor's version. Confidence: weak.

## 6. Readable diagrams

Sources: Purchase (2002) "Metrics for graph drawing aesthetics," *J. Visual Languages and Computing* 13(5), 501–516, DOI 10.1006/jvlc.2002.0232 (full text not retrieved); Ware, Purchase, Colpoys & McGill (2002) "Cognitive measurements of graph aesthetics," *Information Visualization* 1(2); Purchase (1997/2000) on aesthetics and comprehension.

- **Edge crossings** are the strongest readability factor in Purchase's experiments (secondary report). Checkable: a diagram has zero crossings if possible, and at most 2 otherwise. Confidence: strong for direction.
- **Node count:** No primary number from these sources. Working-memory heuristic: at most about 7 nodes per step view; above that, use steps or subgraphs. Confidence: weak (heuristic).
- **Direction:** One reading direction per diagram (top-to-bottom or left-to-right), with no mixed flows. Confidence: moderate.
- **Label length:** Keep node labels to 2–4 words; put detail in the text. Confidence: weak (practice rule).
- **Colour:** Use colour only to carry a meaning used in the text, and do not rely on hue alone. Use a colourblind-safe palette and add shape or dash style as a second cue. Confidence: moderate (WCAG 1.4.1 "use of colour" supports the second-cue rule).
- **Labels on the figure:** Put labels on nodes and edges, not in a separate key. Confidence: strong (spatial contiguity above).

## 7. Mermaid specifics

Sources: mermaid.js.org configuration and flowchart syntax docs (search snippets; theming page not fetched); GitHub `docs/config/theming.md`.

- **Theme:** Use `theme: 'base'` with `themeVariables` in frontmatter. `themeVariables` has no effect on other themes. Frontmatter (v10.5+) replaces `%%{init}%%`. Confidence: strong (official docs, as reported).
- **Shared styles:** Define `classDef` once and attach it with `:::name`. Confidence: strong.
- **Layout:** ELK is the default engine in current Mermaid; use `layout: dagre` only when needed. The tiny build lacks ELK. Confidence: moderate.
- **Subgraphs:** A subgraph's `direction` is overridden when nodes inside link to nodes outside it. Rule: keep subgraph edges internal, or set direction at the top level. Confidence: moderate.
- **Render badly:** Long labels with unescaped punctuation, many crossings, and per-diagram directives in renderers that strip them (one blog reports GitHub strips `%%{init}%%`; unverified). Confidence: weak.
- **Limits:** No node-count limit found in these sources; check `maxTextSize` and `maxEdges` in the config reference. Confidence: weak.

## 8. Matching diagram type to relation

Sources: Larkin & Simon (1987) (above); Ainsworth (2006) (above); Mayer 2014 (above). The mapping below is a design heuristic, not a finding from one study.

- **Process or sequence:** flowchart (left-to-right or top-to-bottom), with steps as nodes. Use a step-through for more than about 5 steps.
- **Hierarchy:** tree, one parent per node.
- **One-to-many / fan-out:** branching diagram from a single root, one direction only.
- **Comparison:** table or side-by-side panels, not a graph.
- **Cycle:** loop with a marked start node. Keep it to one loop.
- **State:** state diagram with named transitions.
- **Quantitative:** function plot or table. Use 3D surfaces only when the learner must read a shape; otherwise use a 2D contour or a table.

## Conflicts

1. Mayer's effect sizes conflict across editions (2009/2014/2021 summaries) and are inflated relative to the 2025 independent meta-analysis (g = 0.37). Use the independent figure for planning.
2. Animations help for procedural change (Höffler & Leutner) but Tversky et al. (2002) and transience research argue many animation wins come from content differences. Resolve by giving static and step versions identical content.
3. Dense multiple representations: dual coding predicts gains, but co-presentation can reduce understanding. Resolve by linking explicitly (Ainsworth's support requirement).
4. Self-explanation effects vary (0.40 to 0.61 across summaries). Use the 0.50 meta-analytic figure.

## Gaps to close before relying on this

- Retrieve the 2014/2021 Mayer handbook tables directly for exact medians.
- Retrieve Purchase (2002) and Renkl (2014) full texts for prompt-type and aesthetics numbers.
- Retrieve Mermaid `theming.md` and the config reference for `maxEdges` and `maxTextSize`.
