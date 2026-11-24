"""pdfium is not thread-safe: two threads in it at once crash the whole app (a segfault, no traceback). Every call into it
holds LOCK, and documents and pages are closed while holding it, so no finalizer frees one later from another thread."""
import threading

import pypdfium2 as pdfium

LOCK = threading.RLock()


def page_count(src) -> int:
    """Pages of a PDF given as a path or bytes; raises pdfium.PdfiumError when it is not a readable PDF."""
    with LOCK:
        pdf = pdfium.PdfDocument(src)
        try:
            return len(pdf)
        finally:
            pdf.close()
