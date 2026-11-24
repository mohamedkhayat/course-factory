from concurrent.futures import ThreadPoolExecutor

from conftest import make_pdf

from course_factory import pdf, refresh


def test_pdfium_from_many_threads_at_once(tmp_path):
    """Two Sources read at once crashed the app inside libpdfium (a segfault): every pdfium call now holds one lock."""
    files = []
    for i in range(4):
        files.append(tmp_path / f"s{i}.pdf")
        make_pdf(files[-1], 3)
    with ThreadPoolExecutor(8) as pool:
        counts = list(pool.map(lambda k: pdf.page_count(str(files[k % 4])), range(64)))
        prints = list(pool.map(lambda k: refresh._page_fingerprints(files[k % 4]), range(32)))
    assert counts == [3] * 64
    assert all(len(p) == 3 for p in prints)
