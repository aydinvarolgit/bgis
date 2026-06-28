"""Module 15 — Content Generator (LinkedIn for MVP).

Render a NarrativePlan into a finished piece of content. Media-specific generation lives
behind the ContentGenerator interface so blog / report / video / newsletter generators
plug in later without touching the belief engine. The plan is media-independent; only this
layer knows about LinkedIn.

In:  NarrativePlan
Out: GeneratedContent{ media, markdown, word_count }  (+ written to data/posts/<id>.md)

LLM: gemma4 (freeform markdown). Author voice from settings.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..context import Context
from ..models import GeneratedContent, NarrativePlan


class ContentGenerator(ABC):
    media: str

    @abstractmethod
    def generate(self, plan: NarrativePlan, ctx: Context) -> str:
        """Return the content body as markdown."""


class LinkedInGenerator(ContentGenerator):
    media = "linkedin"

    SYSTEM = (
        "You are a ghostwriter producing a single LinkedIn post in the author's voice: {voice}. "
        "Write FROM the narrative plan provided — its main message, supporting beliefs, evidence, "
        "and counterarguments. The post must: open with a hook that states a concrete specific or "
        "a sharp claim (NOT a grand abstraction); develop the argument in short, punchy paragraphs; "
        "weave in the concrete evidence verbatim — name the real projects, capabilities, and numbers "
        "from the evidence points; briefly acknowledge the strongest counterargument; close with a "
        "takeaway and one question to drive comments. "
        "\n\nHARD RULES: Ground every paragraph in a specific from the evidence — if a sentence "
        "could appear in any generic AI post, cut or replace it. BANNED phrases/metaphors: 'nervous "
        "system', 'the brain', 'industrial wave', 'holy grail', 'game-changer', 'paradigm shift', "
        "'north star', 'moat', 'unlock', 'supercharge', 'composite capability', 'leverage' (as a "
        "verb), 'synergy', 'in today's fast-paced world'. (Real technical terms like 'orchestration' "
        "are fine when they name an actual capability.) No emoji. "
        "\n\n150-250 words. Return ONLY the post as markdown — no preamble, no 'here is your post', "
        "no surrounding quotes."
    )

    def generate(self, plan: NarrativePlan, ctx: Context) -> str:
        system = self.SYSTEM.format(voice=ctx.settings.author_voice)
        user = (
            f"MAIN MESSAGE: {plan.main_belief}\n\n"
            f"SUPPORTING BELIEFS:\n" + _bullets(plan.supporting_beliefs) + "\n\n"
            f"EVIDENCE POINTS:\n" + _bullets(plan.evidence_points) + "\n\n"
            f"COUNTERARGUMENTS (acknowledge the strongest, briefly):\n"
            + _bullets(plan.counterarguments) + "\n\n"
            f"TONE: {plan.tone}\n"
            "Write the LinkedIn post now."
        )
        return ctx.llm.text(system=system, user=user).strip()


# Media registry — add blog/report/etc. here later.
GENERATORS: dict[str, ContentGenerator] = {g.media: g for g in [LinkedInGenerator()]}


def run(inp: NarrativePlan, ctx: Context, media: str = "linkedin") -> GeneratedContent:
    generator = GENERATORS.get(media)
    if generator is None:
        raise ValueError(f"no content generator for media: {media!r}")

    markdown = generator.generate(inp, ctx)

    # Persist the finished post as a markdown file.
    posts_dir = ctx.settings.stage_dir("posts")
    (posts_dir / f"{inp.source_id}.md").write_text(markdown, encoding="utf-8")

    return GeneratedContent(
        source_id=inp.source_id,
        media="linkedin",
        markdown=markdown,
        word_count=len(markdown.split()),
    )


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {x}" for x in items) if items else "- (none)"
