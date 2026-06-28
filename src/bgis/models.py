"""All Pydantic data contracts for BGIS modules.

This file is the single source of truth for inter-module I/O. Every module consumes
one model and returns another. Each top-level Out model carries `source_id` so it can
be persisted/loaded by id at each pipeline stage.

Models are grouped by module number. STUB modules (8, 9, 10, 13) still have full
contracts so the architecture stays uniform and future work is drop-in.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

# --------------------------------------------------------------------------- #
# Module 1 — Discovery
# --------------------------------------------------------------------------- #

# Widened as source plugins land. Each value is owned by one SourcePlugin (see bgis.sources).
SourceType = Literal["github", "hn", "arxiv", "gh_discussions", "rss"]


class DiscoveryRequest(BaseModel):
    source_type: SourceType = "github"
    url: str


class Source(BaseModel):
    source_id: str
    type: SourceType
    url: str
    status: Literal["discovered", "ingested", "failed"] = "discovered"


# --------------------------------------------------------------------------- #
# Module 2 — Repository Ingestion
# --------------------------------------------------------------------------- #


class TreeEntry(BaseModel):
    path: str
    size: int = 0
    type: Literal["blob", "tree"] = "blob"


class Release(BaseModel):
    tag: str
    date: Optional[datetime] = None


class Commit(BaseModel):
    sha: str
    date: Optional[datetime] = None
    message: str = ""


class DependencyFile(BaseModel):
    path: str
    raw: str


class Repository(BaseModel):
    source_id: str
    owner: str
    name: str
    description: str = ""
    default_branch: str = "main"
    topics: list[str] = Field(default_factory=list)
    stars: int = 0
    forks: int = 0
    watchers: int = 0
    open_issues: int = 0
    language: str = ""
    languages: dict[str, int] = Field(default_factory=dict)
    license: str = ""
    created_at: Optional[datetime] = None
    pushed_at: Optional[datetime] = None
    readme_raw: str = ""
    file_tree: list[TreeEntry] = Field(default_factory=list)
    releases: list[Release] = Field(default_factory=list)
    commits_recent: list[Commit] = Field(default_factory=list)
    contributors_count: int = 0
    dependency_files: list[DependencyFile] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Module 3 — Repository Parsing
# --------------------------------------------------------------------------- #

# Repo docs: readme/architecture/dependencies/metadata. Non-repo sources add their own:
# discussion (HN/GH threads), article (blogs/RSS), paper (arXiv).
DocType = Literal[
    "readme", "architecture", "dependencies", "metadata", "discussion", "article", "paper"
]


class Document(BaseModel):
    type: DocType
    title: str
    text: str
    meta: dict = Field(default_factory=dict)


class ParsedDocuments(BaseModel):
    source_id: str
    documents: list[Document] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Module 4 — Claim Extraction
# --------------------------------------------------------------------------- #


# A claim's epistemic kind. fact = verifiable capability/spec; finding = empirical/benchmarked
# result; opinion = a judgment/stance/prediction. Drives m11: facts+findings build confidence,
# opinions are excluded from it and collected as belief stances instead.
ClaimType = Literal["fact", "opinion", "finding"]


class Claim(BaseModel):
    id: str
    text: str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)  # doc refs, e.g. "readme:para4"
    polarity: Literal["positive", "negative", "neutral"] = "positive"
    type: ClaimType = "fact"  # back-compat default: existing repo claims are facts


class Claims(BaseModel):
    source_id: str
    claims: list[Claim] = Field(default_factory=list)


# LLM-facing schema (no ids/source — assigned deterministically after extraction).
class _ClaimDraft(BaseModel):
    text: str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)
    polarity: Literal["positive", "negative", "neutral"] = "positive"
    type: ClaimType = "fact"


class ClaimDraftList(BaseModel):
    claims: list[_ClaimDraft] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Module 5 — Signal Extraction
# --------------------------------------------------------------------------- #


class Signal(BaseModel):
    name: str
    value: float
    unit: str = ""
    period: Optional[str] = None
    source_field: str = ""


class Signals(BaseModel):
    source_id: str
    signals: list[Signal] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Module 6 — Concept Extraction & Normalization
# --------------------------------------------------------------------------- #


class Concept(BaseModel):
    id: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    from_claims: list[str] = Field(default_factory=list)


class Concepts(BaseModel):
    source_id: str
    concepts: list[Concept] = Field(default_factory=list)


class ConceptDraft(BaseModel):
    name: str
    from_claims: list[str] = Field(default_factory=list)  # claim ids this concept derives from


class ConceptDraftList(BaseModel):
    """LLM output: candidate concepts with the claim ids they come from."""

    concepts: list[ConceptDraft] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Module 7 / 12 — Beliefs
# --------------------------------------------------------------------------- #

Trend = Literal["accelerating", "stable", "declining", "new"]


class BeliefHistoryEntry(BaseModel):
    ts: datetime
    conf_before: float
    conf_after: float
    delta: float
    source_id: str
    supporting: list[str] = Field(default_factory=list)
    contradicting: list[str] = Field(default_factory=list)


class Belief(BaseModel):
    id: str
    statement: str
    confidence: float = Field(ge=0.0, le=1.0)
    trend: Trend = "new"
    linked_concepts: list[str] = Field(default_factory=list)
    stances: list[str] = Field(default_factory=list)  # accumulated opinion texts (capped) for m14
    history: list[BeliefHistoryEntry] = Field(default_factory=list)


class RelatedBeliefs(BaseModel):
    source_id: str
    beliefs: list[Belief] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Module 8 — Context Gap Analysis
# --------------------------------------------------------------------------- #

GapKind = Literal["competitor", "adoption", "research", "alternative", "risk", "validation"]


class Gap(BaseModel):
    concept_id: str  # the concept whose belief this question would strengthen/contradict
    question: str
    kind: GapKind


class GapDraft(BaseModel):
    """LLM output per concept: questions to ask about it (concept_id added by m08)."""

    question: str
    kind: GapKind


class GapDraftList(BaseModel):
    gaps: list[GapDraft] = Field(default_factory=list)


class Gaps(BaseModel):
    source_id: str
    gaps: list[Gap] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Module 9 — Retrieval Engine
# --------------------------------------------------------------------------- #


class RetrievedItem(BaseModel):
    concept_id: str  # the concept this external evidence corroborates (routed by m10)
    question: str  # the gap question it answers (or a synthesized relevance note)
    source_url: str
    summary: str


class RetrievedEvidence(BaseModel):
    source_id: str
    items: list[RetrievedItem] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Module 10 — Evidence Packet Builder
# --------------------------------------------------------------------------- #


class EvidencePacket(BaseModel):
    concept_id: str
    concept_name: str
    claims: list[Claim] = Field(default_factory=list)
    signals: list[Signal] = Field(default_factory=list)
    external: list[RetrievedItem] = Field(default_factory=list)
    summary: str = ""


class EvidencePackets(BaseModel):
    source_id: str
    packets: list[EvidencePacket] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Module 11 — Belief Delta Engine
# --------------------------------------------------------------------------- #


class BeliefDelta(BaseModel):
    belief_id: str
    statement: str
    linked_concepts: list[str] = Field(default_factory=list)
    old_conf: float
    evidence_strength: float
    delta: float
    new_conf: float
    supporting: list[str] = Field(default_factory=list)
    contradicting: list[str] = Field(default_factory=list)
    stance_points: list[str] = Field(default_factory=list)  # opinion claim texts arguing the belief
    rationale: list[str] = Field(default_factory=list)


class BeliefDeltas(BaseModel):
    source_id: str
    deltas: list[BeliefDelta] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Module 12 — Global Belief Graph Update
# --------------------------------------------------------------------------- #


class BeliefGraphUpdate(BaseModel):
    source_id: str
    updated_belief_ids: list[str] = Field(default_factory=list)
    created_belief_ids: list[str] = Field(default_factory=list)
    beliefs: list[Belief] = Field(default_factory=list)  # resolved post-update state


# --------------------------------------------------------------------------- #
# Module 13 — User Belief Graph (STUB in MVP)
# --------------------------------------------------------------------------- #


class UserBelief(BaseModel):
    statement: str
    confidence: float = Field(ge=0.0, le=1.0)
    supporting_evidence: list[str] = Field(default_factory=list)


class UserBeliefs(BaseModel):
    beliefs: list[UserBelief] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Module 14 — Narrative Planner
# --------------------------------------------------------------------------- #


class NarrativePlan(BaseModel):
    source_id: str
    main_belief: str
    supporting_beliefs: list[str] = Field(default_factory=list)
    evidence_points: list[str] = Field(default_factory=list)
    counterarguments: list[str] = Field(default_factory=list)
    tone: str = "analytical"
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class _NarrativeDraft(BaseModel):
    """LLM output for the narrative plan (source_id added after)."""

    main_belief: str
    supporting_beliefs: list[str] = Field(default_factory=list)
    evidence_points: list[str] = Field(default_factory=list)
    counterarguments: list[str] = Field(default_factory=list)
    tone: str = "analytical"
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


# --------------------------------------------------------------------------- #
# Module 15 — Content Generator
# --------------------------------------------------------------------------- #


class GeneratedContent(BaseModel):
    source_id: str
    media: Literal["linkedin"] = "linkedin"
    markdown: str
    word_count: int = 0
