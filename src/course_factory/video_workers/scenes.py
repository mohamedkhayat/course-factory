"""The Manim scene code of the Video templates. It runs only in the Manim environment (render.py starts it) and imports nothing from
course_factory. A template gets its parameters and each scene's length (fitted to the narration) in `spec`; it plays what the scene shows
and holds the picture until the scene's end. Change a template here and bump its VERSION in video_templates.py."""
import textwrap

from manim import (BLUE_B, DOWN, GREY_B, LEFT, RIGHT, UP, WHITE, Arrow, Axes, Create, DashedLine, Dot, FadeIn, FadeOut, Group, Indicate,
                   LaggedStart, MathTex, Rectangle, RoundedRectangle, Scene, Text, Transform, TransformMatchingTex, VGroup, Write, config)

BG, PANEL = "#14161c", "#242833"
COLOURS = ["#6aa9ff", "#ffb454", "#7bd88f", "#f07178", "#c792ea", "#4dd0e1"]
FRAME_W = config.frame_width - 1.0


def wrap(text: str, width: int) -> str:
    return "\n".join(textwrap.wrap(text, width)) or " "


def say(text: str, size: float = 30, width: int = 60, colour=WHITE, max_w: float | None = None) -> Text:
    t = Text(wrap(text, width), font_size=size, color=colour, line_spacing=0.9)
    if t.width > (max_w or FRAME_W):
        t.scale_to_fit_width(max_w or FRAME_W)
    return t


class Template(Scene):
    """Scene i lasts spec["durations"][i] seconds in all: `hold` waits out what the animations did not use."""

    def __init__(self, spec: dict):
        super().__init__()
        self.p, self.w, self.ends, t = spec["params"], spec["words"], [], 0.0
        for d in spec["durations"]:
            t += d
            self.ends.append(t)
        self.i = 0
        self.holds: dict[int, float] = {}  # scene -> when its animations ended: another Voice's narration may cut the still part after it

    def setup(self):
        self.camera.background_color = BG

    def begin(self, i: int):
        self.i = i

    def left(self) -> float:
        return max(0.0, self.ends[self.i] - self.time)

    def act(self, *animations, t: float = 1.0, **kw):
        """Plays at most `t` seconds, and never more than half of what the scene has left, so a short narration still shows everything."""
        self.play(*animations, run_time=max(0.1, min(t, self.left() * 0.5)), **kw)

    def hold(self):
        self.holds.setdefault(self.i, self.time)
        self.wait(max(0.04, self.left()))

    def construct(self):
        for i in range(len(self.ends)):
            self.begin(i)
            self.scene(i)
            self.hold()


class ChapterOverview(Template):
    def scene(self, i):
        sections = self.p["sections"]
        if i == 0:
            title = say(self.p["title"], 44, 34).to_edge(UP, buff=0.9)
            points = VGroup(*[say("•  " + x, 30, 70) for x in self.p["points"]]).arrange(DOWN, aligned_edge=LEFT, buff=0.35).next_to(title, DOWN, buff=0.8)
            self.title_mob = title
            self.act(Write(title), t=1.2)
            self.act(LaggedStart(*[FadeIn(x, shift=RIGHT * 0.3) for x in points], lag_ratio=0.5), t=2.5)
            self.first = VGroup(title, points)
            return
        if i == 1:
            self.act(FadeOut(self.first), t=0.6)
            head = say(self.w["map"], 34).to_edge(UP, buff=0.7)
            rows = []
            for k, s in enumerate(sections):
                box = RoundedRectangle(corner_radius=0.12, width=5.6, height=0.62, stroke_width=2, stroke_color=GREY_B, fill_color=PANEL, fill_opacity=1)
                label = say(f"{k + 1}.  {s['title']}", 22, 38, max_w=5.2).move_to(box)
                rows.append(VGroup(box, label))
            self.rows = VGroup(*rows).arrange(DOWN, buff=0.18).to_edge(LEFT, buff=0.7)
            self.act(FadeIn(head), LaggedStart(*[FadeIn(r) for r in self.rows], lag_ratio=0.15), t=1.5)
            self.note = None
        k = i - 1
        shown = self.rows[k]
        line = say(sections[k]["line"] or sections[k]["title"], 30, 32, COLOURS[0], max_w=5.6)
        card = RoundedRectangle(corner_radius=0.2, width=6.2, height=max(2.4, line.height + 1.2), stroke_color=COLOURS[0], fill_color=PANEL, fill_opacity=1)
        right = VGroup(card, line).to_edge(RIGHT, buff=0.7)
        line.move_to(card)
        for r in self.rows:
            r[0].set_stroke(GREY_B, 2)
        self.act(shown[0].animate.set_stroke(COLOURS[0], 5).set_fill("#2d3a55", 1), *([Transform(self.note, right)] if self.note else [FadeIn(right)]), t=0.8)
        self.note = self.note or right
        if k:
            self.rows[k - 1][0].set_fill(PANEL, 1)


class PartitionFlow(Template):
    SLOT, LANE_H = 1.45, 1.35

    def layout(self, parts):
        """Positions of every record in lanes: lane l holds parts[l] left to right."""
        n = len(parts)
        top = 1.9 if n < 4 else 2.0
        out = []
        for l, rs in enumerate(parts):
            y = top - l * self.LANE_H - (0.2 if n == 4 else 0)
            out.append([(-3.6 + c * self.SLOT, y) for c in range(len(rs))])
        return out

    def scene(self, i):
        parts = self.p["partitions"]
        keys = sorted({r["key"] for rs in parts for r in rs})
        colour = {k: COLOURS[n % len(COLOURS)] for n, k in enumerate(keys)}
        if i == 0:
            self.title = say(self.p["title"], 36, 50).to_edge(UP, buff=0.35)
            spots = self.layout(parts)
            self.lanes, self.recs, self.tags = [], {}, []
            for l, rs in enumerate(parts):
                y = spots[l][0][1]
                lane = RoundedRectangle(corner_radius=0.15, width=9.6, height=1.15, stroke_color=GREY_B, stroke_width=2, fill_color=PANEL, fill_opacity=0.6).move_to((-1.1, y, 0))
                name = say(f'{self.w["partition"]} {l + 1}', 22, 20).move_to((-5.0, y + 0.0, 0)).align_to(lane, LEFT).shift(RIGHT * 0.2)
                self.lanes.append(VGroup(lane, name))
                for c, r in enumerate(rs):
                    self.recs[(l, c)] = self.record(r, colour[r["key"]], (spots[l][c][0] + 1.1, y))
            self.act(Write(self.title), LaggedStart(*[FadeIn(x) for x in self.lanes], lag_ratio=0.2), t=1.2)
            self.act(LaggedStart(*[FadeIn(r, scale=0.6) for r in self.recs.values()], lag_ratio=0.08), t=2.0)
            self.caption = None
            self.say(self.w["split"])
        elif i == 1:
            tasks = [say(f'{self.w["task"]} {l + 1}', 20, 10, GREY_B).move_to((5.6, self.lanes[l][0].get_y(), 0)) for l in range(len(parts))]
            self.say(self.w["narrow"].format(self.p["narrow"]))
            self.act(LaggedStart(*[FadeIn(t) for t in tasks], lag_ratio=0.2), t=0.8)
            self.act(LaggedStart(*[Indicate(r, color=WHITE, scale_factor=1.2) for r in self.recs.values()], lag_ratio=0.1), t=2.5)
            self.tasks = tasks
        elif i == 2:
            self.say(self.w["wide"].format(self.p["wide"]))
            where = {k: n % len(parts) for n, k in enumerate(keys)}
            after = [[] for _ in parts]
            for (l, c), r in self.recs.items():
                after[where[parts[l][c]["key"]]].append((l, c))
            spots = self.layout([[0] * len(a) for a in after])
            moves = []
            for l, ids in enumerate(after):
                for c, rid in enumerate(ids):
                    moves.append(self.recs[rid].animate.move_to((spots[l][c][0] + 1.1, spots[l][c][1], 0)))
            self.act(LaggedStart(*moves, lag_ratio=0.12), t=3.0)
        else:
            self.say(self.w["cache"])
            tags = [say(self.w["cached"], 20, 10, COLOURS[2]).move_to((5.6, ln[0].get_y(), 0)) for ln in self.lanes]
            self.act(*[FadeOut(t) for t in getattr(self, "tasks", [])], LaggedStart(*[FadeIn(t) for t in tags], lag_ratio=0.2),
                     *[r[0].animate.set_stroke(WHITE, 5) for r in self.recs.values()], t=1.5)

    def record(self, r, colour, at):
        text = r["key"] + (":" + r["value"] if r["value"] else "")
        label = Text(text, font_size=22, color="#101216")
        box = RoundedRectangle(corner_radius=0.1, width=max(1.1, label.width + 0.3), height=0.7, fill_color=colour, fill_opacity=1, stroke_color=colour, stroke_width=2)
        label.move_to(box)
        return VGroup(box, label).move_to((at[0], at[1], 0))

    def say(self, text):
        """The line at the bottom: placed the first time, then turned into the next."""
        new = say(text, 24, 78).to_edge(DOWN, buff=0.35)
        if self.caption is None:
            self.caption = new
            self.add(new)
        else:
            self.play(Transform(self.caption, new), run_time=0.4)


class EquationTransform(Template):
    def scene(self, i):
        steps = self.p["steps"]
        eq = MathTex(steps[i]["latex"], font_size=84)
        if eq.width > FRAME_W - 1:
            eq.scale_to_fit_width(FRAME_W - 1)
        eq.move_to((0, 0.3, 0))
        note = say(steps[i]["note"], 30, 60, COLOURS[1]).to_edge(DOWN, buff=1.3) if steps[i]["note"] else None
        if i == 0:
            if self.p["title"]:
                self.add(say(self.p["title"], 36, 50).to_edge(UP, buff=0.6))
            self.act(Write(eq), t=1.5)
            self.eq, self.note = eq, None
            if note:
                self.act(FadeIn(note), t=0.6)
                self.note = note
            return
        anims = [TransformMatchingTex(self.eq, eq, transform_mismatches=True)]
        if self.note:
            anims.append(FadeOut(self.note))
        if note:
            anims.append(FadeIn(note))
        self.act(*anims, t=1.6)
        self.eq, self.note = eq, note


class FunctionPlot(Template):
    def scene(self, i):
        p, curve = self.p, self.curve
        marks = p["marks"]
        if i == 0:
            ys = [y for _, y in curve]
            lo, hi = min(ys), max(ys)
            pad = (hi - lo) * 0.1 or 1.0
            lo, hi = lo - pad, hi + pad
            x_lo, x_hi = p["x_range"]
            self.axes = Axes(x_range=[x_lo, x_hi, self.step(x_hi - x_lo)], y_range=[lo, hi, self.step(hi - lo)], x_length=10.5, y_length=4.6,
                             axis_config={"include_numbers": True, "font_size": 22, "color": GREY_B, "include_tip": True}).shift(DOWN * 0.4)
            self.axes.x_axis.numbers.set_color(GREY_B)
            labels = self.axes.get_axis_labels(MathTex("x", font_size=30), MathTex("y", font_size=30))
            if p["title"]:
                self.add(say(p["title"], 36, 50).to_edge(UP, buff=0.4))
            self.act(Create(self.axes), FadeIn(labels), t=2.0)
        elif i == 1:
            graph = self.axes.plot_line_graph([x for x, _ in curve], [y for _, y in curve], add_vertex_dots=False, line_color=COLOURS[0], stroke_width=5)
            self.act(Create(graph), t=2.5)
            if p["latex"]:
                tag = MathTex(p["latex"], font_size=40, color=COLOURS[0]).to_corner(UP + RIGHT, buff=0.7)
                self.act(FadeIn(tag), t=0.6)
        else:
            m = marks[i - 2]
            y = m["y"]
            dot = Dot(self.axes.c2p(m["x"], y), color=COLOURS[1], radius=0.12)
            drop = DashedLine(self.axes.c2p(m["x"], 0 if self.axes.y_range[0] <= 0 <= self.axes.y_range[1] else self.axes.y_range[0]), self.axes.c2p(m["x"], y), color=COLOURS[1])
            label = say(m["label"], 26, 30, COLOURS[1]).next_to(dot, UP + RIGHT, buff=0.15)
            label.shift(LEFT * max(0.0, label.get_right()[0] - (config.frame_width / 2 - 0.3)))  # kept on screen
            self.act(Create(drop), FadeIn(dot, scale=0.5), Write(label), t=1.2)

    @staticmethod
    def step(span: float) -> float:
        for s in (0.1, 0.2, 0.25, 0.5, 1, 2, 2.5, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000):
            if span / s <= 8:
                return s
        return span / 6

    def __init__(self, spec):
        super().__init__(spec)
        self.curve = spec["curve"]


TEMPLATES = {"chapter_overview": ChapterOverview, "partition_flow": PartitionFlow, "equation_transform": EquationTransform, "function_plot": FunctionPlot}
