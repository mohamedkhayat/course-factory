# course-factory: the vision after v1

This file describes what comes after v1, so a later session can pick any part up without the original conversations. These are descriptions, not specs. Each section gets its own planning effort when its turn comes.

Lines marked **(proposed)** are Claude's fill-ins. They haven't been confirmed by the owner yet.

## 1. More than one user

v1 is single-user. Later, other people use it too.
- **(proposed)** The first other users are classmates taking the same modules.
- **(proposed)** A course generated once can be shared. One generation run serves many learners, and each learner keeps their own progress, lab work, grades and tutor history.
- **(proposed)** Feedback from every learner flows back into the shared course (see section 4). A question that many people get wrong, or that someone flags, is evidence about the course itself, not only about that learner.
- This brings in accounts and auth.
- Open questions: who hosts it, how one GPU's local models serve several people, and what is private (your notes, copies, grades) vs shared (the course).

## 2. More kinds of source

The point is learning anything, not only uni courses. A course can be built from:
- books (PDF, EPUB);
- blog posts and articles;
- forum threads (Stack Exchange, Reddit, mailing lists);
- YouTube videos, via their transcripts with timestamps, and key frames for slides or blackboard shots.

Each kind keeps citations back to an exact place: a page, a heading, a post, a timestamp. Clicking a citation opens that spot.
- **(proposed)** Sources can be mixed, e.g. a textbook plus a lecture series plus a forum thread on a hard point.

## 3. Deep-research mode

You name a topic you have no material for. The system researches it, proposes a lesson plan for your approval, then builds the course from what it found, citing every source. This is the stretch goal for v2.
- **(proposed)** The research step ranks sources by trust (official docs, textbooks and papers above blog posts) and tells you when sources disagree.

## 4. Self-improvement loop

**Signals.** Every interaction leaves a signal:
- flags on bad content;
- quiz stats and which wrong answers get picked;
- your edits and regenerations;
- approvals and rejections of model-made components;
- tutor conversations where the explanation didn't land;
- grades on handwritten copies.

**Tickets and evals.** Signals become tickets and evals, much as in Matt Pocock's software factory. There, agents turn tickets into changes, and brakes stop bad changes before they land: automated checks, automated review, then human review. "Accelerators without brakes make a slop cannon."

**Harness optimisation first.** In the style of google-research/harness2, the system improves its own harness (system prompts, skills, tool guidance, checks, memory) by proposing a change, probing it against evals, and keeping what helps, with evidence for each lesson. The model weights stay fixed.

**Fine-tuning later.** Fine-tuning or distilling small models comes only after harness gains level off. Candidates:
- distilling the Qwen 3.8 27B model's approved outputs into smaller models;
- training on content that passed review.

## 5. A software factory around the app itself

- Components the local model made carry a "made by local model" tag. Claude Code works through a review queue of them: promote, fix, or reject. Courses using a rejected component get flagged.
- Later, agents take tickets from the feedback loop and open pull requests against course-factory itself. Matt Pocock's Sandcastle (Docker plus a git worktree per agent) is the prior art. Human review stays the last brake.

## 6. ML Mastery Atlas

Atlas stays separate and untouched. course-factory does no integration, migration or other work for it. Reading Atlas's code and ADRs as prior art is fine.

## 7. Other kinds of lab

v1 labs are math and science work with plots and visual output. Later:
- **ML labs:** training runs on the GPU, datasets, tracking experiments.
- **Graded coding exercises:** your code is checked by unit tests.
- **(proposed)** Languages beyond Python where a course needs them (C/C++, R, Julia, MATLAB/Octave).

## 8. Tablet and phone

- Use the app from a tablet on the home network: read courses, take quizzes, sit exams in exam mode.
- Write answers by hand on the tablet with a stylus, or photograph paper copies, and send them straight to the grader.
- **(proposed)** The tablet pairs with the host machine the way Atlas pairs devices. The models and data stay on the host.
