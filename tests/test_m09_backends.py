"""Module 9 pluggable retrieval backends: source-plugins, local-corpus, external-APIs.

Each backend's `candidates()` is exercised offline with injected getters, plus an m09.run
integration that confirms a candidate is embedded, routed to a concept, and gated by threshold.
"""

from bgis.models import (
    Claims,
    Concept,
    Concepts,
    Gap,
    Gaps,
    ParsedDocuments,
    Document,
)
from bgis.modules import m09_retrieval
from bgis.persistence import save_artifact
from bgis.retrieval import (
    ExternalApiBackend,
    LocalCorpusBackend,
    SourcePluginBackend,
    WebSearchBackend,
    default_backends,
)

ATOM = """<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Agent Memory Survey</title>
    <summary>We study agent memory.</summary>
    <id>http://arxiv.org/abs/1234</id>
  </entry>
</feed>"""


def _concepts():
    # No from_claims -> concept_rep is just the name, so embeddings are easy to control.
    return Concepts(
        source_id="src_x",
        concepts=[Concept(id="concept_mem", name="agent memory")],
    )


def _claims():
    return Claims(source_id="src_x", claims=[])


def _gaps(kind="research"):
    return Gaps(
        source_id="src_x",
        gaps=[Gap(concept_id="concept_mem", question="what is the research?", kind=kind)],
    )


class _FakeRepo:
    def __init__(self, full_name, description="", stars=0):
        self.full_name = full_name
        self.description = description
        self.stargazers_count = stars


class _FakeGh:
    def __init__(self, repos):
        self._repos = repos

    def search_repositories(self, query, **kw):
        return list(self._repos)


# --- Backend 1: SourcePlugin reuse -------------------------------------------------------- #
def test_source_plugin_backend_arxiv_routes_by_kind(ctx):
    b = SourcePluginBackend(arxiv_fetch=lambda url: ATOM)
    cands = b.candidates(_gaps("research"), _concepts(), _claims(), ctx)
    assert len(cands) == 1
    assert cands[0].concept_id == "concept_mem"
    assert cands[0].summary.startswith("[arxiv] Agent Memory Survey")
    assert "arxiv.org/abs/1234" in cands[0].source_url


def test_source_plugin_backend_hn_for_adoption(ctx):
    hn_json = {"hits": [{"title": "Show HN: memory", "points": 99, "objectID": "7", "url": "http://h"}]}
    b = SourcePluginBackend(hn_fetch=lambda url: hn_json)
    cands = b.candidates(_gaps("adoption"), _concepts(), _claims(), ctx)
    assert len(cands) == 1
    assert cands[0].source_url == "http://h"
    assert "[hn 99pts]" in cands[0].summary


def test_source_plugin_backend_github_for_competitor(ctx):
    gh = _FakeGh([_FakeRepo("acme/mem", "memory engine", 500)])
    b = SourcePluginBackend(gh=gh)
    cands = b.candidates(_gaps("competitor"), _concepts(), _claims(), ctx)
    assert len(cands) == 1
    assert cands[0].source_url == "https://github.com/acme/mem"
    assert "[github 500★]" in cands[0].summary


def test_source_plugin_backend_skips_unknown_concept(ctx):
    gaps = Gaps(source_id="src_x", gaps=[Gap(concept_id="ghost", question="q", kind="research")])
    b = SourcePluginBackend(arxiv_fetch=lambda url: ATOM)
    assert b.candidates(gaps, _concepts(), _claims(), ctx) == []


# --- Backend 2: local corpus -------------------------------------------------------------- #
def test_local_corpus_backend_reads_other_sources(ctx):
    # A previously-ingested source on disk; current run is src_x and must be excluded.
    other = ParsedDocuments(
        source_id="src_other",
        documents=[Document(type="article", title="Memory systems", text="agent memory recall",
                            meta={"url": "http://o"})],
    )
    save_artifact(ctx.settings, "parsed", "src_other", other)
    save_artifact(ctx.settings, "parsed", "src_x",
                  ParsedDocuments(source_id="src_x", documents=[
                      Document(type="article", title="self", text="should be excluded")]))
    b = LocalCorpusBackend()
    cands = b.candidates(_gaps(), _concepts(), _claims(), ctx)
    urls = [c.source_url for c in cands]
    assert "http://o" in urls
    assert all(c.concept_id is None for c in cands)  # routed by embedding, not hinted
    assert "should be excluded" not in " ".join(c.text for c in cands)


# --- Backend 3: external APIs ------------------------------------------------------------- #
def test_external_api_backend_three_sources(ctx):
    b = ExternalApiBackend(
        wiki_fetch=lambda u: {"query": {"search": [{"title": "Memory", "snippet": "<b>mem</b> x"}]}},
        s2_fetch=lambda u: {"data": [{"title": "Mem paper", "abstract": "abs", "url": "http://s2",
                                      "citationCount": 12}]},
        crossref_fetch=lambda u: {"message": {"items": [{"title": ["Mem work"], "URL": "http://cr",
                                                         "type": "journal-article"}]}},
    )
    cands = b.candidates(_gaps(), _concepts(), _claims(), ctx)
    summaries = " ".join(c.summary for c in cands)
    assert "[wikipedia]" in summaries
    assert "[semanticscholar 12 cites]" in summaries
    assert "[crossref]" in summaries
    assert all(c.concept_id == "concept_mem" for c in cands)


def test_external_api_backend_failsoft(ctx):
    def boom(u):
        raise RuntimeError("api down")

    b = ExternalApiBackend(wiki_fetch=boom, s2_fetch=boom, crossref_fetch=boom)
    assert b.candidates(_gaps(), _concepts(), _claims(), ctx) == []


# --- Backend 4: open-web search (DuckDuckGo) ---------------------------------------------- #
def test_web_search_backend_routes_results_to_concept(ctx):
    def fake_search(query, n):
        assert "agent memory" in query
        return [
            {"title": "Agent memory deep dive", "href": "http://w1", "body": "<b>recall</b> systems"},
            {"title": "Unrelated", "href": "http://w2", "body": "cooking recipes"},
        ]

    b = WebSearchBackend(search=fake_search)
    cands = b.candidates(_gaps("research"), _concepts(), _claims(), ctx)
    assert len(cands) == 2
    assert all(c.concept_id == "concept_mem" for c in cands)
    assert cands[0].source_url == "http://w1"
    assert cands[0].summary.startswith("[web] Agent memory deep dive")
    assert "<b>" not in cands[0].text  # html stripped
    assert cands[0].question == "what is the research?"


def test_web_search_backend_failsoft(ctx):
    def boom(query, n):
        raise RuntimeError("ddg down")

    assert WebSearchBackend(search=boom).candidates(_gaps(), _concepts(), _claims(), ctx) == []


def test_web_search_backend_caps_per_concept(ctx):
    ctx.settings.retrieval_websearch_per_concept = 1
    b = WebSearchBackend(search=lambda q, n: [{"title": f"r{i}", "href": f"http://w{i}", "body": "x"}
                                              for i in range(5)])
    cands = b.candidates(_gaps(), _concepts(), _claims(), ctx)
    assert len(cands) == 1  # capped to per_concept


# --- m09 integration: routing + threshold gate through a backend -------------------------- #
def test_m09_routes_backend_candidate_to_concept(ctx):
    ctx.embedder.table = {
        "agent memory": [1.0, 0.0],
        "Agent Memory Survey\n\nWe study agent memory.": [1.0, 0.0],  # matches -> kept
    }
    b = SourcePluginBackend(arxiv_fetch=lambda url: ATOM)
    r = m09_retrieval.run(_gaps("research"), _concepts(), _claims(), None, ctx, backends=[b])
    assert len(r.items) == 1
    assert r.items[0].concept_id == "concept_mem"
    assert r.items[0].question == "what is the research?"


def test_m09_gates_backend_candidate_below_threshold(ctx):
    ctx.embedder.table = {
        "agent memory": [1.0, 0.0],
        "Agent Memory Survey\n\nWe study agent memory.": [0.0, 1.0],  # orthogonal -> dropped
    }
    b = SourcePluginBackend(arxiv_fetch=lambda url: ATOM)
    r = m09_retrieval.run(_gaps("research"), _concepts(), _claims(), None, ctx, backends=[b])
    assert r.items == []


def test_default_backends_respects_flags(ctx):
    # The test fixture pins web_search off for offline safety; with all flags off, no backends.
    assert default_backends(ctx) == []
    # web_search is ON by default in prod (Settings.retrieval_use_web_search=True); the other three
    # are opt-in.
    from bgis.config import Settings
    assert Settings(github_token="t").retrieval_use_web_search is True
    ctx.settings.retrieval_use_source_plugins = True
    ctx.settings.retrieval_use_local_corpus = True
    ctx.settings.retrieval_use_external_apis = True
    ctx.settings.retrieval_use_web_search = True
    names = {b.name for b in default_backends(ctx)}
    assert names == {"source_plugins", "local_corpus", "external_apis", "web_search"}
