from apps.services import RunRequest


def test_chat_uses_governed_semantic_recall_by_default() -> None:
    request = RunRequest(text="continúa nuestra conversación")

    assert request.semantic_recall_enabled is True
