from __future__ import annotations


def test_learning_pipeline_can_import_before_rollback_adapter() -> None:
    from triade.learning.pipeline import LearningPipeline
    from triade.regression.learning_rollback import LearningRollbackAdapter

    assert LearningPipeline is not None
    assert LearningRollbackAdapter is not None


def test_rollback_adapter_can_import_before_learning_pipeline() -> None:
    from triade.regression.learning_rollback import LearningRollbackAdapter
    from triade.learning.pipeline import LearningPipeline

    assert LearningRollbackAdapter is not None
    assert LearningPipeline is not None
