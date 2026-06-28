from bgis.models import DependencyFile, Repository, TreeEntry
from bgis.modules import m03_parse


def _repo(**kw):
    base = dict(
        source_id="src_test",
        owner="juliusbrussee",
        name="caveman",
        description="Talk like caveman",
        topics=["ai", "cli"],
        stars=1200,
        forks=80,
        language="Python",
        languages={"Python": 9000, "Shell": 1000},
        license="MIT",
        readme_raw="# Caveman\nSave tokens.",
        file_tree=[
            TreeEntry(path="src/main.py", size=100, type="blob"),
            TreeEntry(path="src/util.py", size=50, type="blob"),
            TreeEntry(path="README.md", size=20, type="blob"),
            TreeEntry(path="src", size=0, type="tree"),
        ],
        dependency_files=[DependencyFile(path="requirements.txt", raw="requests\n")],
    )
    base.update(kw)
    return Repository(**base)


def test_produces_all_doc_types(ctx):
    parsed = m03_parse.run(_repo(), ctx)
    types = {d.type for d in parsed.documents}
    assert types == {"readme", "architecture", "dependencies", "metadata"}
    for d in parsed.documents:
        assert d.text.strip()


def test_readme_omitted_when_empty(ctx):
    parsed = m03_parse.run(_repo(readme_raw=""), ctx)
    types = {d.type for d in parsed.documents}
    assert "readme" not in types
    assert "architecture" in types  # still present


def test_dependencies_omitted_when_none(ctx):
    parsed = m03_parse.run(_repo(dependency_files=[]), ctx)
    assert "dependencies" not in {d.type for d in parsed.documents}


def test_architecture_counts_files_and_langs(ctx):
    parsed = m03_parse.run(_repo(), ctx)
    arch = next(d for d in parsed.documents if d.type == "architecture")
    assert arch.meta["file_count"] == 3  # blobs only, tree entry excluded
    assert "Python" in arch.text
    assert "src: 2 files" in arch.text


def test_metadata_contains_signals(ctx):
    parsed = m03_parse.run(_repo(), ctx)
    md = next(d for d in parsed.documents if d.type == "metadata")
    assert "Stars: 1200" in md.text
    assert "MIT" in md.text
