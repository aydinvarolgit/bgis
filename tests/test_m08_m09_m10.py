from bgis.models import (
    Belief,
    Claim,
    Claims,
    Concept,
    Concepts,
    Gap,
    GapDraft,
    GapDraftList,
    Gaps,
    RelatedBeliefs,
    Repository,
    RetrievedEvidence,
    RetrievedItem,
    Signal,
    Signals,
)
from bgis.modules import m08_gap, m09_retrieval, m10_evidence


def _concepts():
    return Concepts(
        source_id="src_test",
        concepts=[
            Concept(id="concept_a", name="orchestration", from_claims=["c1", "c2"]),
            Concept(id="concept_b", name="token compression", from_claims=["c3"]),
            Concept(id="concept_empty", name="ghost", from_claims=[]),
        ],
    )


def _claims():
    return Claims(
        source_id="src_test",
        claims=[
            Claim(id="c1", text="orchestrates agents", confidence=0.9),
            Claim(id="c2", text="coordination matters", confidence=0.7),
            Claim(id="c3", text="compresses tokens", confidence=0.8),
        ],
    )


def _signals():
    return Signals(
        source_id="src_test",
        signals=[Signal(name="stars", value=1200, unit="count", source_field="stars")],
    )


# --- Module 8 ---
def test_gap_tags_each_question_with_concept_id(ctx):
    ctx.llm.structured_responses["GapDraftList"] = GapDraftList(
        gaps=[
            GapDraft(question="Who competes with this?", kind="competitor"),
            GapDraft(question="Is adoption growing?", kind="adoption"),
        ]
    )
    g = m08_gap.run(_concepts(), RelatedBeliefs(source_id="src_test"), ctx)
    # concept_empty (no claims) is skipped; concept_a + concept_b each get 2 questions
    assert {gap.concept_id for gap in g.gaps} == {"concept_a", "concept_b"}
    assert len(g.gaps) == 4
    assert all(gap.kind in {"competitor", "adoption"} for gap in g.gaps)


def test_gap_caps_questions_per_concept(ctx):
    ctx.llm.structured_responses["GapDraftList"] = GapDraftList(
        gaps=[GapDraft(question=f"q{i}", kind="research") for i in range(5)]
    )
    g = m08_gap.run(_concepts(), RelatedBeliefs(source_id="src_test"), ctx)
    per_concept = {}
    for gap in g.gaps:
        per_concept[gap.concept_id] = per_concept.get(gap.concept_id, 0) + 1
    assert all(n <= m08_gap.MAX_QUESTIONS_PER_CONCEPT for n in per_concept.values())


def test_gap_passes_related_beliefs_as_context(ctx):
    # Belief linked to concept_a must reach the LLM prompt (don't crash, still tags).
    related = RelatedBeliefs(
        source_id="src_test",
        beliefs=[Belief(id="bel_x", statement="orchestration is hot", confidence=0.8,
                        linked_concepts=["concept_a"])],
    )
    ctx.llm.structured_responses["GapDraftList"] = GapDraftList(
        gaps=[GapDraft(question="validate?", kind="validation")]
    )
    g = m08_gap.run(_concepts(), related, ctx)
    assert any(gap.concept_id == "concept_a" for gap in g.gaps)


def test_gap_no_concepts_empty(ctx):
    g = m08_gap.run(Concepts(source_id="src_test"), RelatedBeliefs(source_id="src_test"), ctx)
    assert g.gaps == []


# --- Module 9 (GitHub-native retrieval) ---
class _FakeRepoResult:
    def __init__(self, full_name, description="", topics=(), stars=0):
        self.full_name = full_name
        self.description = description
        self._topics = list(topics)
        self.stargazers_count = stars

    def get_topics(self):
        return self._topics


class _FakeGh:
    """search_repositories(query=...) -> list; get_repo(full_name) -> result."""

    def __init__(self, by_topic=None, by_name=None):
        self.by_topic = by_topic or {}
        self.by_name = by_name or {}

    def search_repositories(self, query, **kw):
        topic = query.split("topic:")[-1].strip()
        return list(self.by_topic.get(topic, []))

    def get_repo(self, full_name):
        if full_name in self.by_name:
            return self.by_name[full_name]
        raise KeyError(full_name)


def _repo(topics=("agent-memory", "ai")):
    return Repository(source_id="src_test", owner="me", name="mine",
                      topics=list(topics), readme_raw="see https://github.com/other/linked")


def _retrieval_ctx(ctx):
    # Concept "orchestration" embedding; a candidate repo text embeds identically -> matches.
    ctx.embedder.table = {
        "orchestration": [1.0, 0.0],
        "token compression": [0.0, 1.0],
        "ghost": [0.5, 0.5],
    }
    return ctx


def test_retrieval_matches_candidate_to_concept(ctx):
    ctx = _retrieval_ctx(ctx)
    sibling = _FakeRepoResult("acme/orchestrator", "an orchestration engine",
                              ["agent-memory"], 500)
    # candidate text embeds to the orchestration vector
    ctx.embedder.table["acme/orchestrator. an orchestration engine. topics: agent-memory"] = [1.0, 0.0]
    gh = _FakeGh(by_topic={"agent-memory": [sibling]})
    gaps = Gaps(source_id="src_test", gaps=[Gap(concept_id="concept_a", question="rivals?", kind="competitor")])
    r = m09_retrieval.run(gaps, _concepts(), Claims(source_id='src_test'), _repo(), ctx, gh=gh)
    assert len(r.items) == 1
    it = r.items[0]
    assert it.concept_id == "concept_a"  # orchestration
    assert it.question == "rivals?"
    assert "acme/orchestrator" in it.summary


def test_retrieval_drops_below_threshold(ctx):
    ctx = _retrieval_ctx(ctx)
    sibling = _FakeRepoResult("acme/unrelated", "totally different", ["agent-memory"], 5)
    ctx.embedder.table["acme/unrelated. totally different. topics: agent-memory"] = [0.0, 1.0, 0.0]
    gh = _FakeGh(by_topic={"agent-memory": [sibling]})
    gaps = Gaps(source_id="src_test")
    r = m09_retrieval.run(gaps, _concepts(), Claims(source_id='src_test'), _repo(), ctx, gh=gh)
    # cos to orchestration[1,0,0]=0, to token-compression[0,1,0]... best ~ but len mismatch ->0
    assert r.items == []


def test_retrieval_skips_generic_topics_and_self(ctx):
    ctx = _retrieval_ctx(ctx)
    gh = _FakeGh(by_topic={"ai": [_FakeRepoResult("x/y", "", ["ai"], 9)]})
    # only generic topic "ai" -> no distinctive topic searched -> no items
    r = m09_retrieval.run(Gaps(source_id='src_test'), _concepts(), Claims(source_id='src_test'), _repo(topics=['ai']), ctx, gh=gh)
    assert r.items == []


def test_retrieval_no_concepts_empty(ctx):
    r = m09_retrieval.run(Gaps(source_id='src_test'), Concepts(source_id='src_test'),
                          Claims(source_id='src_test'), _repo(), ctx, gh=_FakeGh())
    assert r.items == []


# --- Module 10 ---
def test_evidence_groups_by_concept(ctx):
    pkts = m10_evidence.run(
        _concepts(), _claims(), _signals(),
        RelatedBeliefs(source_id="src_test"), RetrievedEvidence(source_id="src_test"), ctx,
    )
    # concept_empty has no claims -> dropped
    names = {p.concept_name for p in pkts.packets}
    assert names == {"orchestration", "token compression"}
    orch = next(p for p in pkts.packets if p.concept_name == "orchestration")
    assert {c.id for c in orch.claims} == {"c1", "c2"}
    assert orch.signals[0].name == "stars"
    assert orch.external == []
    assert "avg confidence 0.80" in orch.summary  # (0.9+0.7)/2
    assert "1200 stars" in orch.summary


def test_evidence_routes_external_by_concept_id(ctx):
    retrieved = RetrievedEvidence(
        source_id="src_test",
        items=[
            RetrievedItem(concept_id="concept_a", question="rivals?",
                          source_url="https://github.com/x/y", summary="x/y (9★): sibling"),
            RetrievedItem(concept_id="concept_b", question="papers?",
                          source_url="https://github.com/p/q", summary="p/q (3★): other"),
        ],
    )
    pkts = m10_evidence.run(
        _concepts(), _claims(), _signals(),
        RelatedBeliefs(source_id="src_test"), retrieved, ctx,
    )
    by_id = {p.concept_id: p for p in pkts.packets}
    assert [it.source_url for it in by_id["concept_a"].external] == ["https://github.com/x/y"]
    assert [it.source_url for it in by_id["concept_b"].external] == ["https://github.com/p/q"]
    # no cross-contamination: concept_a doesn't get concept_b's evidence
    assert all(it.concept_id == "concept_a" for it in by_id["concept_a"].external)
