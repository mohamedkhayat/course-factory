"""The media lane: Listen audio, Video renders and Voice installs, one job at a time, in the open. Each job shows how far it is;
the owner can pause the lane or stop a job. Both take effect at the job's next step (a sentence spoken, a render started)."""
import itertools
import threading
from concurrent.futures import Future


class Stopped(Exception):
    """The owner stopped the job from the media queue."""

    def __init__(self):
        super().__init__("stopped from the media queue")


class MediaJob:
    def __init__(self, jid: int, fn, args, kind: str, label: str, course: int | None, background: bool, stoppable: bool):
        self.id, self.fn, self.args, self.kind, self.label, self.course = jid, fn, args, kind, label, course
        self.background, self.stoppable = background, stoppable
        self.state, self.done, self.total, self.step, self.stop = "queued", 0, 0, "", False
        self.future: Future = Future()

    def view(self) -> dict:
        return {"id": self.id, "kind": self.kind, "label": self.label, "course": self.course, "state": self.state, "done": self.done,
                "total": self.total, "step": self.step, "stoppable": self.stoppable, "stopping": self.stop, "background": self.background}


class MediaQueue:
    def __init__(self):
        self.queued: list[MediaJob] = []
        self.current: MediaJob | None = None
        self.paused = False
        self.cv = threading.Condition()
        self.ids = itertools.count(1)
        threading.Thread(target=self.run, daemon=True, name="media").start()

    def submit(self, fn, *args, kind: str = "other", label: str = "", course: int | None = None, background: bool = False,
               stoppable: bool = False) -> Future:
        """Queues fn(*args). Background work (audio made ahead while a Course is written) waits behind anything the owner asked for."""
        job = MediaJob(next(self.ids), fn, args, kind, label, course, background, stoppable)
        with self.cv:
            at = len(self.queued) if background else next((i for i, j in enumerate(self.queued) if j.background), len(self.queued))
            self.queued.insert(at, job)
            self.cv.notify_all()
        return job.future

    def run(self):
        while True:
            with self.cv:
                while True:  # paused, only what cannot pause runs (an install, a Voice preview), and stopped jobs report so
                    job = next((j for j in self.queued if j.stop), None) or next(
                        (j for j in self.queued if not self.paused or not j.stoppable), None)
                    if job:
                        break
                    self.cv.wait()
                self.queued.remove(job)
                self.current = job
                job.state = "running"
            try:  # a job stopped while queued still starts: its first checkpoint stops it, so whatever waits on it hears
                job.future.set_result(job.fn(*job.args))
            except BaseException as e:
                job.future.set_exception(e)
            finally:
                with self.cv:
                    self.current = None
                    self.cv.notify_all()

    def checkpoint(self, done: int | None = None, total: int | None = None, step: str | None = None) -> None:
        """The running job reports how far it is between steps; here it waits while the lane is paused, and stops when told to."""
        if threading.current_thread().name != "media":
            return  # called outside the lane (a test running the work directly)
        with self.cv:
            job = self.current
            if job is None:
                return
            if done is not None:
                job.done = done
            if total is not None:
                job.total = total
            if step is not None:
                job.step = step
            while self.paused and not job.stop:
                self.cv.wait()
            if job.stop:
                raise Stopped()

    def pause(self, paused: bool) -> None:
        with self.cv:
            self.paused = paused
            self.cv.notify_all()

    def stop(self, jid: int) -> bool:
        """A job stops at its next checkpoint: a queued one is started next only to stop there."""
        with self.cv:
            for job in ([self.current] if self.current else []) + self.queued:
                if job.id == jid and job.stoppable:
                    job.stop = True
                    self.cv.notify_all()  # a queued one is picked next, only to report it was stopped
                    return True
        return False

    def view(self) -> dict:
        with self.cv:
            return {"paused": self.paused, "jobs": [j.view() for j in ([self.current] if self.current else []) + self.queued]}
