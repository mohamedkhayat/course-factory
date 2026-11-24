"""Cleaning a phone photo of a paper page before it is graded: SAM 3 finds the sheet, the photo is cropped and flattened to it,
its light evened out (shadows, a yellow lamp) and turned upright. A step that can't run is skipped: the photo is never lost."""
import io
import logging
import threading

import numpy as np
from PIL import Image, ImageFilter, ImageOps

log = logging.getLogger(__name__)
SAM_REPO = "facebook/sam3"
SAM_SIDE = 1008  # SAM 3's input size: the photo is shrunk to it to find the sheet, then the corners are scaled back
OUT_SIDE = 2200  # enough to read handwriting; a 12 MP photo would only slow the grader
_lock = threading.Lock()  # one SAM 3 in memory at a time


def page_mask(img: Image.Image) -> np.ndarray | None:
    """The largest sheet of paper SAM 3 finds in the image, as a boolean mask the image's size, or None. SAM 3 is loaded for
    this photo and freed right after: on the GPU when the language model leaves 4 GB (~1 s), else on the CPU (~6.5 s, measured
    2026-11-24), never by unloading the language model, whose reload takes longer than the CPU does."""
    import torch
    from transformers import Sam3Model, Sam3Processor
    with _lock:
        dev = "cuda" if torch.cuda.is_available() and torch.cuda.mem_get_info()[0] > 4e9 else "cpu"
        inputs = out = res = None
        model = Sam3Model.from_pretrained(SAM_REPO, local_files_only=True, dtype=torch.bfloat16 if dev == "cuda" else torch.float32)
        try:
            model = model.to(dev).eval()
            proc = Sam3Processor.from_pretrained(SAM_REPO, local_files_only=True)
            inputs = proc(images=img, text="sheet of paper", return_tensors="pt").to(dev)
            inputs = {k: v.to(model.dtype) if v.is_floating_point() else v for k, v in inputs.items()}
            with torch.inference_mode():
                out = model(**inputs)
            res = proc.post_process_instance_segmentation(out, threshold=0.4, mask_threshold=0.5, target_sizes=[img.size[::-1]])[0]
            masks = [m.float().cpu().numpy() > 0.5 for m in res["masks"]]
        finally:
            model = inputs = out = res = None  # every GPU tensor dropped before the cache goes back to the driver
            if dev == "cuda":
                torch.cuda.empty_cache()
    best = max(masks, key=np.sum, default=None)
    return best if best is not None and best.mean() > 0.1 else None  # a small hit is a scrap of paper, not the page


def corners(mask: np.ndarray) -> list[tuple[float, float]]:
    """The four corners of a roughly upright quadrilateral mask: top-left, top-right, bottom-right, bottom-left."""
    ys, xs = np.nonzero(mask)
    s, d = xs + ys, xs - ys
    return [(xs[i], ys[i]) for i in (s.argmin(), d.argmax(), s.argmax(), d.argmin())]


def _perspective(src: list, dst: list) -> list[float]:
    """PIL's PERSPECTIVE coefficients mapping each output point in dst to the input point in src."""
    a = []
    for (x, y), (u, v) in zip(dst, src):
        a += [[x, y, 1, 0, 0, 0, -u * x, -u * y], [0, 0, 0, x, y, 1, -v * x, -v * y]]
    return np.linalg.solve(np.array(a, float), np.array([c for p in src for c in p], float)).tolist()


def flatten(img: Image.Image, quad: list[tuple[float, float]]) -> Image.Image:
    tl, tr, br, bl = (np.array(p, float) for p in quad)
    w = int(max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl)))
    h = int(max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr)))
    return img.transform((w, h), Image.PERSPECTIVE, _perspective(quad, [(0, 0), (w, 0), (w, h), (0, h)]), Image.BICUBIC)


def even_light(img: Image.Image) -> Image.Image:
    """Divides out the paper's own light (a blur far wider than a stroke), so the sheet is white and the ink keeps its colour."""
    # at a quarter size the max filter spans ~28 px: wider than a stroke, so the ink leaves no grey halo
    bg = img.reduce(4).filter(ImageFilter.MaxFilter(7)).filter(ImageFilter.GaussianBlur(max(img.size) / 200)).resize(img.size, Image.BILINEAR)
    out = np.asarray(img, float) / np.maximum(np.asarray(bg, float), 1) * 255
    return ImageOps.autocontrast(Image.fromarray(np.clip(out, 0, 255).astype(np.uint8)), cutoff=(1, 0))


def upright(img: Image.Image) -> Image.Image:
    """Turns a page sideways or upside down so its lines run left to right: written lines make the row profile of the ink
    uneven, and left-to-right lines start at one margin and end ragged."""
    small = ImageOps.grayscale(img)
    small.thumbnail((600, 600))
    ink = np.asarray(small) < 140
    h, w = ink.shape
    ink = ink[h // 25: -h // 25 or None, w // 25: -w // 25 or None]  # a crop's dark edges are not writing
    if ink.sum() < 200:
        return img
    if ink.sum(0).var() > 1.5 * ink.sum(1).var():  # the lines run up and down
        img, ink = img.transpose(Image.Transpose.ROTATE_90), np.rot90(ink)
    rows = [np.nonzero(r)[0] for r in ink if r.sum() > 3]
    if len(rows) > 10:
        starts, ends = np.std([r[0] for r in rows]), np.std([r[-1] for r in rows])
        if ends < 0.6 * starts:  # the aligned margin is on the right: upside down
            img = img.transpose(Image.Transpose.ROTATE_180)
    return img


def clean_photo(data: bytes) -> Image.Image:
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    small = img.copy()
    small.thumbnail((SAM_SIDE, SAM_SIDE))
    try:
        mask = page_mask(small)
    except Exception:  # SAM 3 not downloaded, or out of memory: the photo is still evened out and turned
        log.exception("SAM 3 could not look for the page")
        mask = None
    if mask is not None:
        k = img.width / small.width
        img = flatten(img, [(x * k, y * k) for x, y in corners(mask)])
    img.thumbnail((OUT_SIDE, OUT_SIDE))
    return upright(even_light(img))
