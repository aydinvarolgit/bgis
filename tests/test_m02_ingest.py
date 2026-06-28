"""Module 2 tests — PyGithub fully mocked, no network."""

from datetime import datetime
from types import SimpleNamespace

import pytest

from bgis.models import Source
from bgis.modules import m02_ingest


class FakeContent:
    def __init__(self, text):
        self.decoded_content = text.encode("utf-8")


class FakeTreeEntry:
    def __init__(self, path, size, type):
        self.path = path
        self.size = size
        self.type = type


class FakeRepo:
    def __init__(self, with_deps=True):
        self.description = "A caveman tool"
        self.default_branch = "main"
        self.stargazers_count = 1200
        self.forks_count = 80
        self.subscribers_count = 30
        self.open_issues_count = 5
        self.language = "Python"
        self.created_at = datetime(2024, 1, 1)
        self.pushed_at = datetime(2024, 6, 1)
        self._with_deps = with_deps

    def get_topics(self):
        return ["cli", "ai"]

    def get_languages(self):
        return {"Python": 9000, "Shell": 500}

    def get_license(self):
        return SimpleNamespace(license=SimpleNamespace(spdx_id="MIT"))

    def get_readme(self):
        return FakeContent("# Caveman\nTalk like caveman. Save tokens.")

    def get_git_tree(self, branch, recursive):
        return SimpleNamespace(
            tree=[
                FakeTreeEntry("src/main.py", 1000, "blob"),
                FakeTreeEntry("src", 0, "tree"),
                FakeTreeEntry("README.md", 200, "blob"),
            ]
        )

    def get_releases(self):
        return [SimpleNamespace(tag_name="v1.0", published_at=datetime(2024, 5, 1), created_at=None)]

    def get_commits(self):
        return [
            SimpleNamespace(
                sha="abc123",
                commit=SimpleNamespace(
                    message="fix: thing\n\nbody",
                    author=SimpleNamespace(date=datetime(2024, 6, 1)),
                ),
            )
        ]

    def get_contributors(self):
        return SimpleNamespace(totalCount=7)

    def get_contents(self, path):
        if self._with_deps and path == "requirements.txt":
            return FakeContent("requests\npydantic\n")
        raise Exception("404 not found")


class FakeGithub:
    def __init__(self, repo):
        self._repo = repo

    def get_repo(self, full):
        return self._repo


@pytest.fixture
def source():
    return Source(
        source_id="src_test", type="github", url="https://github.com/juliusbrussee/caveman"
    )


def test_ingest_maps_core_fields(source, ctx):
    repo = m02_ingest.run(source, ctx, gh=FakeGithub(FakeRepo()))
    assert repo.owner == "juliusbrussee"
    assert repo.name == "caveman"
    assert repo.stars == 1200
    assert repo.forks == 80
    assert repo.watchers == 30
    assert repo.language == "Python"
    assert repo.license == "MIT"
    assert repo.topics == ["cli", "ai"]
    assert repo.languages == {"Python": 9000, "Shell": 500}
    assert "Caveman" in repo.readme_raw
    assert len(repo.file_tree) == 3
    assert repo.releases[0].tag == "v1.0"
    assert repo.commits_recent[0].message == "fix: thing"  # first line only
    assert repo.contributors_count == 7
    assert [d.path for d in repo.dependency_files] == ["requirements.txt"]


def test_ingest_handles_missing_optionals(source, ctx):
    repo_obj = FakeRepo(with_deps=False)
    # Simulate missing README/license/releases by raising.
    repo_obj.get_readme = lambda: (_ for _ in ()).throw(Exception("no readme"))
    repo_obj.get_license = lambda: (_ for _ in ()).throw(Exception("no license"))
    repo = m02_ingest.run(source, ctx, gh=FakeGithub(repo_obj))
    assert repo.readme_raw == ""
    assert repo.license == ""
    assert repo.dependency_files == []
