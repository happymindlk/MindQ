"""Golden vectors from assessments.json scored through the production engine."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from app.services.instrument_results import build_score_details, hexaco_subscales
from app.services.psychometric_catalog import (
    TARGET_SLUGS,
    TIMER_CONFIG,
    assert_catalog_shape,
    questions_for,
    score_catalog_vector,
)
from app.services.report_synthesis import build_module_outcomes
from app.services.scoring import score_assessment_detailed

CATALOG = assert_catalog_shape()
DONE = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)


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


def test_mini_ipip_reports_all_five_official_facets():
    module = CATALOG["mini_ipip"]
    vector = next(v for v in module["testVectors"] if v["name"] == "all_mid")
    result, _answers = score_catalog_vector(module, vector)
    details = build_score_details(
        questions=questions_for(module),
        result=result,
        category="personality",
    )
    assert details["instrument"] == "big_five"
    assert [row["name"] for row in details["subscales"]] == [
        "Surgency or Extraversion",
        "Agreeableness",
        "Conscientiousness",
        "Neuroticism",
        "Intellect or Imagination",
    ]
    assert set(result.facet_scores) == {"E", "A", "C", "N", "I"}


def test_hexaco_reverse_keys_match_official_spec():
    module = CATALOG["hexaco_hh"]
    reverse_ns = sorted(int(item["n"]) for item in module["items"] if item.get("keying") == "-")
    assert reverse_ns == [
        3,
        5,
        6,
        7,
        8,
        9,
        13,
        15,
        16,
        17,
        18,
        19,
        21,
        25,
        27,
        28,
        29,
        30,
        31,
        32,
        33,
        34,
        35,
        36,
        37,
        38,
        39,
        40,
    ]
    assert len(reverse_ns) == 28
    vector = next(v for v in module["testVectors"] if v["name"] == "all_mid")
    result, _ = score_catalog_vector(module, vector)
    rows = hexaco_subscales(result.facet_scores)
    assert [row["name"] for row in rows] == [
        "Sincerity",
        "Fairness",
        "Greed Avoidance",
        "Modesty",
    ]
    assert set(result.facet_scores) == {"Sinc", "Fair", "Gree", "Mode"}


def test_personal_initiative_persists_sum_and_mean_on_seven_point_scale():
    module = CATALOG["personal_initiative"]
    vector = next(v for v in module["testVectors"] if v["name"] == "mixed_seeded")
    result, _ = score_catalog_vector(module, vector)
    facet = result.facet_scores["Personal Initiative"]
    assert facet["sum"] == 35
    assert facet["mean"] == 3.5
    assert facet["n"] == 10
    details = build_score_details(
        questions=questions_for(module),
        result=result,
        category="behavioral",
    )
    assert details["instrument"] == "initiative"
    assert details["sum"] == 35
    assert details["mean"] == 3.5
    assert details["scale_max"] == 7
    assert details["module_pct"] == 41.7


def test_reports_withhold_numerical_scores_while_package_pending():
    done = SimpleNamespace(
        id=uuid4(),
        title="SQL",
        module_kind="technical",
        questions=[],
        global_module_id=None,
    )
    pending = SimpleNamespace(
        id=uuid4(),
        title="Python",
        module_kind="technical",
        questions=[],
        global_module_id=None,
    )
    progresses = [
        SimpleNamespace(
            assessment_id=done.id,
            status="COMPLETED",
            score=88.0,
            facet_scores=None,
            completed_at=DONE,
            score_details=None,
        ),
        SimpleNamespace(
            assessment_id=pending.id,
            status="IN_PROGRESS",
            score=40.0,
            facet_scores=None,
            completed_at=None,
            score_details=None,
        ),
    ]
    outcomes = build_module_outcomes([done, pending], progresses, [], {})
    assert len(outcomes) == 2
    assert [o.status for o in outcomes] == ["COMPLETED", "IN_PROGRESS"]
    assert all(o.score is None for o in outcomes)
    assert all(o.scores_released is False for o in outcomes)
    assert all(o.display_score is None for o in outcomes)
    assert all(o.subscales == () for o in outcomes)
