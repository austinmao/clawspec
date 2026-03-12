from clawspec.runner.score_tracker import ScoreTracker


def test_rolling_average_and_pass_metrics_use_recent_window(tmp_path) -> None:
    tracker = ScoreTracker(base_dir=tmp_path, window=3)

    tracker.record_score("newsletter", "happy-path", "llm_judge", score=2.0, passed=False)
    tracker.record_score("newsletter", "happy-path", "llm_judge", score=4.0, passed=True)
    tracker.record_score("newsletter", "happy-path", "llm_judge", score=5.0, passed=True)
    tracker.record_score("newsletter", "happy-path", "llm_judge", score=1.0, passed=False)

    summary = tracker.get_metrics("newsletter", "happy-path", "llm_judge", threshold=3.0)

    assert round(summary["rolling_average"], 4) == round((4.0 + 5.0 + 1.0) / 3, 4)
    assert summary["pass_at_k"] == 1.0
    assert summary["pass_caret_k"] == 0.0
    assert summary["alert"] is False


def test_threshold_alert_triggers_when_average_drops_below_threshold(tmp_path) -> None:
    tracker = ScoreTracker(base_dir=tmp_path, window=2)

    tracker.record_score(
        "brand", "voice-check", "agent_identity_consistent", score=2.0, passed=False
    )
    tracker.record_score(
        "brand", "voice-check", "agent_identity_consistent", score=3.0, passed=True
    )

    summary = tracker.get_metrics(
        "brand", "voice-check", "agent_identity_consistent", threshold=3.5
    )

    assert summary["rolling_average"] == 2.5
    assert summary["alert"] is True
