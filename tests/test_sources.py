import pytest

from bgis.sources import resolve
from bgis.sources.arxiv import ArxivSourcePlugin
from bgis.sources.gh_discussions import GHDiscussionsSourcePlugin
from bgis.sources.github import GitHubSourcePlugin
from bgis.sources.hn import HNSourcePlugin
from bgis.sources.rss import RSSSourcePlugin


# --- registry / resolve ---------------------------------------------------- #

def test_resolve_github_url():
    assert isinstance(resolve("https://github.com/owner/repo"), GitHubSourcePlugin)


def test_resolve_hn_ref():
    assert isinstance(resolve("hn:agent memory"), HNSourcePlugin)


def test_resolve_arxiv_ghd_rss():
    assert isinstance(resolve("arxiv:rag"), ArxivSourcePlugin)
    assert isinstance(resolve("ghd:mem0ai/mem0"), GHDiscussionsSourcePlugin)
    assert isinstance(resolve("rss:https://x.com/feed"), RSSSourcePlugin)


def test_resolve_unknown_raises():
    with pytest.raises(ValueError):
        resolve("ftp://nope")


def test_github_does_not_match_kind_query():
    assert GitHubSourcePlugin().matches("hn:agent memory") is False
    assert HNSourcePlugin().matches("https://github.com/o/r") is False


# --- HN ingest (fake fetch, no network) ------------------------------------ #

def _fake_fetch(url: str) -> dict:
    if "search?" in url:
        return {
            "hits": [
                {"objectID": "1", "title": "Low story", "points": 10, "num_comments": 1},
                {"objectID": "2", "title": "Top story", "points": 200, "num_comments": 2},
            ]
        }
    if "/items/2" in url:
        return {
            "id": 2,
            "title": "Top story",
            "text": "<p>Body of the <b>top</b> story</p>",
            "points": 200,
            "children": [
                {"id": 21, "text": "Agents are <i>overhyped</i> &amp; brittle"},
                {"id": 22, "text": "Memory is the real bottleneck"},
                {"id": 23, "text": ""},  # empty -> skipped
            ],
        }
    if "/items/1" in url:
        return {"id": 1, "title": "Low story", "text": "minor", "points": 10, "children": []}
    raise AssertionError(f"unexpected url {url}")


def test_hn_ingest_builds_parsed_documents(ctx):
    plugin = HNSourcePlugin(fetch=_fake_fetch)
    result = plugin.ingest("hn:agents", ctx)

    parsed = result.parsed
    assert parsed.source_id.startswith("src_")
    assert result.repo is None  # HN has no Repository -> Module 9 skipped
    assert result.signals.signals == []

    types = [d.type for d in parsed.documents]
    # Top story first (sorted by points): article + discussion; low story: article only (no comments).
    assert types == ["article", "discussion", "article"]

    article = parsed.documents[0]
    assert article.title == "Top story"
    assert "Body of the top story" in article.text  # HTML stripped

    discussion = parsed.documents[1]
    assert "overhyped & brittle" in discussion.text  # entity unescaped
    assert "Memory is the real bottleneck" in discussion.text
    assert discussion.meta["n_comments"] == 2  # empty comment dropped


def test_hn_source_id_is_stable_per_query(ctx):
    p = HNSourcePlugin(fetch=_fake_fetch)
    a = p.ingest("hn:agents", ctx).source.source_id
    b = p.ingest("hn:agents", ctx).source.source_id
    assert a == b


# --- arXiv ingest (canned Atom XML, no network) ---------------------------- #

_ATOM_XML = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2401.00001v1</id>
    <title>Retrieval Augmented   Generation Survey</title>
    <summary>We benchmark RAG and find a 12% gain over baselines.</summary>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2401.00002v1</id>
    <title>Agent Memory Systems</title>
    <summary>A study of long-term memory for agents.</summary>
  </entry>
</feed>"""


def test_arxiv_ingest_parses_papers(ctx):
    plugin = ArxivSourcePlugin(fetch=lambda url: _ATOM_XML)
    result = plugin.ingest("arxiv:retrieval augmented generation", ctx)
    docs = result.parsed.documents
    assert [d.type for d in docs] == ["paper", "paper"]
    assert docs[0].title == "Retrieval Augmented Generation Survey"  # whitespace collapsed
    assert "12% gain" in docs[0].text
    assert docs[0].meta["url"] == "http://arxiv.org/abs/2401.00001v1"
    assert result.repo is None


# --- GH Discussions/Issues ingest (fake gh + graphql) ---------------------- #

class _FakeComment:
    def __init__(self, body):
        self.body = body


class _FakeIssue:
    def __init__(self, number, title, body, comments, comment_bodies, pr=None):
        self.number = number
        self.title = title
        self.body = body
        self.comments = comments
        self.pull_request = pr
        self._comment_bodies = comment_bodies

    def get_comments(self):
        return [_FakeComment(b) for b in self._comment_bodies]


class _FakeRepo:
    def __init__(self, issues):
        self._issues = issues

    def get_issues(self, state="all"):
        return self._issues


class _FakeGH:
    def __init__(self, repo):
        self._repo = repo

    def get_repo(self, slug):
        return self._repo


def test_ghd_ingest_issues_and_discussions(ctx):
    issues = [
        _FakeIssue(1, "Quiet bug", "minor", comments=0, comment_bodies=[]),
        _FakeIssue(2, "Hot debate", "is this the right approach?", comments=5,
                   comment_bodies=["I disagree", "agreed, it scales poorly"]),
        _FakeIssue(3, "A PR", "code", comments=9, comment_bodies=["lgtm"], pr={"url": "x"}),
    ]
    gh = _FakeGH(_FakeRepo(issues))

    def fake_graphql(ctx, query, variables):
        return {"data": {"repository": {"discussions": {"nodes": [
            {"title": "Roadmap", "body": "where next?",
             "comments": {"nodes": [{"body": "more memory features"}]}},
        ]}}}}

    plugin = GHDiscussionsSourcePlugin(gh=gh, graphql=fake_graphql)
    result = plugin.ingest("ghd:owner/repo", ctx)
    docs = result.parsed.documents
    titles = [d.title for d in docs]

    # PR excluded; busiest issue first; discussion appended after issues.
    assert titles == ["Issue: Hot debate", "Issue: Quiet bug", "Discussion: Roadmap"]
    assert "it scales poorly" in docs[0].text
    assert all(d.type == "discussion" for d in docs)
    assert result.repo is None


def test_ghd_survives_graphql_failure(ctx):
    gh = _FakeGH(_FakeRepo([_FakeIssue(1, "Only issue", "b", 1, ["c"])]))

    def boom(ctx, query, variables):
        raise RuntimeError("graphql down")

    plugin = GHDiscussionsSourcePlugin(gh=gh, graphql=boom)
    docs = plugin.ingest("ghd:owner/repo", ctx).parsed.documents
    assert [d.title for d in docs] == ["Issue: Only issue"]  # issues still work


# --- RSS ingest (canned feed string, no network) --------------------------- #

_RSS_XML = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <title>Expert Blog</title>
  <item>
    <title>Why agents need memory</title>
    <link>https://blog.example/agents</link>
    <description>&lt;p&gt;The real bottleneck is &lt;b&gt;state&lt;/b&gt;, not models.&lt;/p&gt;</description>
  </item>
</channel></rss>"""


def test_rss_ingest_single_feed(ctx):
    plugin = RSSSourcePlugin(fetch=lambda url: _RSS_XML)
    result = plugin.ingest("rss:https://blog.example/feed", ctx)
    docs = result.parsed.documents
    assert len(docs) == 1
    assert docs[0].type == "article"
    assert docs[0].title == "Why agents need memory"
    assert "The real bottleneck is state, not models" in docs[0].text  # HTML stripped
    assert docs[0].meta["url"] == "https://blog.example/agents"


def test_rss_all_uses_configured_feeds(ctx):
    ctx.settings.rss_feeds = ["feedA", "feedB"]
    seen = []

    def fake_fetch(url):
        seen.append(url)
        return _RSS_XML

    plugin = RSSSourcePlugin(fetch=fake_fetch)
    result = plugin.ingest("rss:all", ctx)
    assert seen == ["feedA", "feedB"]
    assert len(result.parsed.documents) == 2  # one entry per feed
