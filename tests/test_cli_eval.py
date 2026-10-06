"""CLI smoke tests and a small end-to-end evaluation run (hashing embedder, extractive model, no API calls)."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from clearance.cli import app
from clearance.eval.dataset import CorpusOracle, load_canaries, load_questions
from clearance.eval.runner import prepare, run_acl_change, run_leak, run_recall
from clearance.llm.extractive import ExtractiveModel
from tests.conftest import CORPUS, ROOT, TEST_DATABASE_URL, make_settings

runner = CliRunner()


def test_cli_help_and_users() -> None:
    assert runner.invoke(app, ["--help"]).exit_code == 0
    env = {"CLEARANCE_GROUP_MAPPING_FILE": str(ROOT / "configs" / "group-mapping.yaml"), "COLUMNS": "250"}
    result = runner.invoke(app, ["users"], env=env)
    assert result.exit_code == 0 and "bob.tanner@fernhill.test" in result.output
    assert "group:contractors" in result.output


def test_question_set_and_canaries_are_consistent() -> None:
    questions = load_questions(ROOT / "data" / "eval" / "questions.yaml")
    canaries = load_canaries(ROOT / "data" / "eval" / "canaries.yaml")
    oracle = CorpusOracle.build(CORPUS, canaries)
    assert len(questions.authorized) >= 50 and len(questions.adversarial) >= 30
    for question in questions.authorized:
        assert all(d in oracle.acls for d in question.docs)
        if question.answerable:  # the asker may read every gold document they are asked about
            assert any(oracle.can_read_any(_principals(question.user), d) for d in question.docs), question.id
    locations = oracle.canary_locations()
    assert all(locations[c.id] for c in canaries)  # every canary is planted somewhere
    everyone = ["user:x@fernhill.test", "group:all-employees", "group:contractors"]
    assert not oracle.visible_canaries(everyone)  # and none of them is readable company-wide


def _principals(email: str) -> list[str]:
    from clearance.auth.devidp import Directory
    from clearance.auth.mapping import GroupMapping

    user = Directory.load(ROOT / "data" / "directory.yaml").user(email)
    groups, _ = GroupMapping.load(ROOT / "configs" / "group-mapping.yaml").principals_for_claims(user.idp_groups)
    return [f"user:{email}", *groups]


@pytest.mark.db
def test_cli_ingest_ask_and_acl(tmp_path: Path) -> None:
    env = {
        "CLEARANCE_DATABASE_URL": TEST_DATABASE_URL,
        "CLEARANCE_EMBEDDING_PROVIDER": "hash",
        "CLEARANCE_LLM_PROVIDER": "extractive",
        "CLEARANCE_DEV_IDP_KEY_FILE": str(tmp_path / "k.pem"),
        "CLEARANCE_LLM_LEDGER": "",
    }
    ingest = runner.invoke(app, ["ingest", str(CORPUS)], env=env)
    assert ingest.exit_code == 0, ingest.output
    answer = runner.invoke(app, ["ask", "What is the per diem in Portugal?", "--as", "dan.kim"], env=env)
    assert answer.exit_code == 0 and "€55" in answer.output and "searchable documents: 31" in answer.output
    shown = runner.invoke(app, ["acl", "show", "all-hands/travel-policy.md"], env=env)
    assert "group:all-employees" in shown.output
    changed = runner.invoke(app, ["acl", "set", "all-hands/travel-policy.md", "--allow", "group:finance"], env=env)
    assert changed.exit_code == 0 and "updated" in changed.output
    after = runner.invoke(app, ["ask", "What is the per diem in Portugal?", "--as", "dan.kim"], env=env)
    assert "€55" not in after.output


@pytest.mark.db
def test_evaluation_end_to_end_without_api_calls(tmp_path: Path) -> None:
    from clearance.embeddings import HashEmbedder

    settings = make_settings(database_url=TEST_DATABASE_URL, dev_idp_key_file=tmp_path / "k.pem")
    ctx = prepare(settings, embedder=HashEmbedder(), model=ExtractiveModel())
    leak = run_leak(ctx, ExtractiveModel(), generate_for=["clearance", "unfiltered"])
    clearance, unfiltered = leak["systems"]["clearance"], leak["systems"]["unfiltered"]
    assert clearance["pairs"] == 30 * 11
    assert (
        clearance["pairs_with_restricted_chunk_in_context"] == 0
        and clearance["pairs_with_hidden_canary_in_answer"] == 0
    )
    assert leak["systems"]["rls_only"]["pairs_with_restricted_chunk_in_context"] == 0
    assert leak["systems"]["postfilter"]["pairs_with_restricted_chunk_in_context"] == 0
    assert (
        unfiltered["pairs_with_restricted_chunk_in_context"] > 100
        and unfiltered["pairs_with_hidden_canary_in_answer"] > 0
    )
    recall = run_recall(ctx)
    assert recall["systems"]["clearance"]["recall_at_k"] >= recall["systems"]["postfilter"]["recall_at_k"]
    change = run_acl_change(ctx)
    revocations = change["revocations"]
    assert revocations["trials"] > 20
    assert revocations["excluded_on_next_query"] == revocations["trials"] == revocations["back_after_restore"]
    assert revocations["embeddings_computed"] == 0
    assert change["deletions"]["gone_on_next_query"] == change["deletions"]["trials"] > 0
