def test_registry_keeps_legacy_and_inferred_scoring_handlers():
    from app.tasks.handlers import registry

    handlers = registry()
    assert handlers[("topic.score", "1")].version == "1"
    assert handlers[("topic.score", "2")].version == "2"
