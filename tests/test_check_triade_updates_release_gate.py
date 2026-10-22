"""Safety policy of the Colab update checker: never install an unreviewed tip."""
from tools.check_triade_updates import decision


SOURCE = "a" * 40
BRANCH = "codex/triade-5.8.0-runtime-recovery"


def manifest(*, channel="stable", requires_review=False, commit=SOURCE, branch=BRANCH):
    return {
        "project": "triadees",
        "commit": commit,
        "branch": branch,
        "channel": channel,
        "requires_review": requires_review,
    }


def test_candidate_is_never_offered_as_installable():
    result = decision(manifest(channel="stable-candidate", requires_review=True), head="b" * 40)
    assert result["status"] == "review_required"
    assert result["update_available"] is False


def test_claimed_stable_release_must_be_verified_against_branch():
    result = decision(
        manifest(), head="b" * 40,
        release_tree_verified=False,
        local_is_ancestor=True,
    )
    assert result["status"] == "manifest_mismatch"
    assert result["update_available"] is False


def test_verified_fast_forward_is_offered():
    result = decision(
        manifest(), head="b" * 40,
        release_tree_verified=True,
        local_is_ancestor=True,
        remote_is_ancestor=False,
    )
    assert result["relation"] == "fast_forward_available"
    assert result["update_available"] is True


def test_divergent_local_code_cannot_be_force_updated():
    result = decision(
        manifest(), head="b" * 40,
        release_tree_verified=True,
        local_is_ancestor=False,
        remote_is_ancestor=False,
    )
    assert result["status"] == "manual_review_required"
    assert result["update_available"] is False


def test_local_ahead_does_not_receive_old_release():
    result = decision(
        manifest(), head="b" * 40,
        release_tree_verified=True,
        local_is_ancestor=False,
        remote_is_ancestor=True,
    )
    assert result["relation"] == "local_ahead_or_equal"
    assert result["update_available"] is False


def test_same_verified_release_not_offered_twice():
    result = decision(manifest(), head=SOURCE, release_tree_verified=True)
    assert result["relation"] == "same"
    assert result["update_available"] is False


def test_invalid_manifest_ref_is_rejected():
    result = decision(manifest(commit="origin/main; rm -rf ."), head="b" * 40)
    assert result["status"] == "invalid_manifest"
    assert result["update_available"] is False
