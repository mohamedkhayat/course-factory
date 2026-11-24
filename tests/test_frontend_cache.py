import pytest

from course_factory import app as app_mod


@pytest.mark.skipif(not (app_mod.WEB_DIST / "index.html").exists(), reason="web/dist is not built")
def test_hashed_assets_are_cached_and_pages_revalidated(client):
    asset = next((app_mod.WEB_DIST / "assets").glob("*.js")).name
    assert client.get(f"/assets/{asset}").headers["cache-control"] == "public, max-age=31536000, immutable"
    assert client.get("/c/1/practice").headers["cache-control"] == "no-cache"  # index.html, so a new build reaches devices
    assert client.get("/sw.js").headers["cache-control"] == "no-cache"
