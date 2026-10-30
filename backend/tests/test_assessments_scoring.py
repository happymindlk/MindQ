"""Golden vectors from assessments.json scored through the production engine."""
from __future__ import annotations

from pathlib import Path

from app.services.psychometric_catalog import (
    TARGET_SLUGS,
    TIMER_CONFIG,
    assert_catalog_shape,
    questions_for,
    score_catalog_vector,
)
from app.services.scoring import score_assessment_detailed

CATALOG = assert_catalog_shape()


def _facet_sum(facet_scores: dict, key: str) -> float:
    wanted = key.casefold()
    for name, entry in facet_scores.items():
        if str(name).casefold() == wanted or str(name).casefold().endswith(":" + wanted):
            return round(float(entry["mean"]) * int(entry["n"]), 6)
    raise AssertionError(f"missing facet {key} in {list(facet_scores)}")


def test_seed_wipe_sql_does_not_touch_optional_progress_columns():
    import inspect

    from scripts.seed_assessments import _wipe_child_rows

    source = inspect.getsource(_wipe_child_rows)
    assert "select(CandidateProgress)" not in source
    assert "score_details =" not in source
    assert "scoring_version =" not in source
    assert "DELETE FROM candidate_responses" in source
    assert "UPDATE candidate_progress" in source


def test_seed_timer_minutes_round_up():
    from scripts.seed_assessments import _minutes

    assert _minutes(180) == 3
    assert _minutes(270) == 5
    assert _minutes(330) == 6


def test_crt_is_the_only_strict_timer():
    assert TIMER_CONFIG["crt"] == (180, "strict", False)
    for slug, (_seconds, mode, _shuffle) in TIMER_CONFIG.items():
        if slug != "crt":
            assert mode == "flexible", slug
    assert TIMER_CONFIG["mini_ipip"][2] is True
    assert TIMER_CONFIG["hexaco_hh"][2] is True


def test_catalog_has_seven_modules_and_item_counts_match():
    total = sum(len(CATALOG[slug]["items"]) for slug in TARGET_SLUGS)
    assert len(TARGET_SLUGS) == 7
    assert total == sum(int(CATALOG[slug]["itemCount"]) for slug in TARGET_SLUGS)
    assert {item["id"] for item in CATALOG["ipip_ipc"]["items"]} == {
        f"ipc_{i:02d}" for i in range(1, 33)
    }


def test_cognicheck_9_16_point_at_icar_assets():
    images = [
        item["image"]
        for item in CATALOG["cognicheck"]["items"]
        if int(item["n"]) >= 9
    ]
    assert len(images) == 8
    assert all(path.startswith("assets/icar/") for path in images)
    stored = questions_for(CATALOG["cognicheck"])
    media = [q["media_url"] for q in stored if q.get("media_url")]
    assert len(media) == 8
    assert all(url.startswith("assets/icar/") for url in media)


def test_score_lookup_uses_item_id_not_index():
    questions = questions_for(CATALOG["mini_ipip"])
    shuffled = list(reversed(questions))
    answers = {questions[0]["id"]: 5, questions[-1]["id"]: 1}
    from types import SimpleNamespace

    rows = [SimpleNamespace(question_id=qid, response={"answer": val}) for qid, val in answers.items()]
    result = score_assessment_detailed(shuffled, rows)
    assert result.items_answered == 2


def test_all_catalog_vectors_pass():
    for slug in TARGET_SLUGS:
        module = CATALOG[slug]
        for vector in module.get("testVectors") or []:
            result, answers = score_catalog_vector(module, vector)
            expected = vector.get("expected") or {}
            name = f"{slug}:{vector.get('name')}"
            if "expectedTotal" in vector:
                total = vector["expectedTotal"]
                if result.sjt_points is not None:
                    assert result.sjt_points == total, name
                elif result.crt_correct is not None:
                    assert result.crt_correct == total, name
                else:
                    assert result.score == round(total / result.gradable_count * 100, 2), name
                continue
            if "sum" in expected and "mean" in expected:
                facet = next(iter(result.facet_scores.values()))
                assert facet["mean"] == expected["mean"], name
                assert round(facet["mean"] * facet["n"], 6) == expected["sum"], name
                continue
            if "facetSums" in expected:
                for key, value in expected["facetSums"].items():
                    assert _facet_sum(result.facet_scores, key) == value, f"{name}:{key}"
                if "domainSum" in expected:
                    total = sum(
                        float(entry["mean"]) * int(entry["n"]) for entry in result.facet_scores.values()
                    )
                    assert round(total, 6) == expected["domainSum"], name
                continue
            for key, value in expected.items():
                if key in {"facetMeans", "domainMean"}:
                    continue
                assert _facet_sum(result.facet_scores, key) == value, f"{name}:{key} answers={len(answers)}"
