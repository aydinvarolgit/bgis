import pytest

from bgis.models import DiscoveryRequest
from bgis.modules import m01_discovery


def test_normalize_strips_extras():
    url = "https://github.com/Owner/Repo.git/tree/main"
    assert m01_discovery.normalize_github_url(url) == "https://github.com/Owner/Repo"


def test_normalize_rejects_non_github():
    with pytest.raises(ValueError):
        m01_discovery.normalize_github_url("https://gitlab.com/a/b")


def test_source_id_is_deterministic():
    a = m01_discovery.mint_source_id("https://github.com/juliusbrussee/caveman")
    b = m01_discovery.mint_source_id("https://github.com/juliusbrussee/caveman")
    assert a == b
    assert a.startswith("src_")


def test_run_produces_source(ctx):
    req = DiscoveryRequest(url="https://github.com/juliusbrussee/caveman")
    src = m01_discovery.run(req, ctx)
    assert src.type == "github"
    assert src.status == "discovered"
    assert src.url == "https://github.com/juliusbrussee/caveman"
    assert src.source_id.startswith("src_")


def test_run_rejects_bad_url(ctx):
    with pytest.raises(ValueError):
        m01_discovery.run(DiscoveryRequest(url="not a url"), ctx)
