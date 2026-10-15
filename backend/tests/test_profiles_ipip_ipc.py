"""IPIP-IPC circumplex resolver and profile registry."""
from __future__ import annotations

import json
import math

import pytest
from pydantic import ValidationError

from app.services.profiles import DerivedProfile, ProfileInputs, resolve_profile
from app.services.profiles.ipip_ipc import OCTANTS, IpipIpcResolver, classify_angle

NEUTRAL = 3.0


def _facets(overrides: dict[str, float] | None = None, n: int = 4) -> dict[str, dict]:
    means = {octant: NEUTRAL for octant in OCTANTS}
    means.update(overrides or {})
    return {octant: {"mean": mean, "n": n} for octant, mean in means.items()}


def _resolve(facets: dict[str, dict]) -> DerivedProfile:
    return IpipIpcResolver().resolve(ProfileInputs(facet_scores=facets))


@pytest.mark.parametrize(
    "octant, expected_label",
    [
        ("LM", "Warm-Agreeable"),
        ("NO", "Gregarious-Extraverted"),
        ("PA", "Assured-Dominant"),
        ("BC", "Arrogant-Calculating"),
        ("DE", "Cold-Hearted"),
        ("FG", "Aloof-Introverted"),
        ("HI", "Unassured-Submissive"),
        ("JK", "Unassuming-Ingenuous"),
    ],
)
def test_elevated_single_octant_maps_to_its_style(octant, expected_label):
    profile = _resolve(_facets({octant: 5.0}))
    assert profile.status == "complete"
    assert profile.data["style_code"] == octant
    assert profile.data["style_label"] == expected_label


def test_formulas_match_spec_exactly():
    means = {"PA": 4.0, "BC": 2.5, "DE": 1.5, "FG": 2.0, "HI": 2.25, "JK": 3.5, "LM": 4.5, "NO": 3.75}
    profile = _resolve({k: {"mean": v, "n": 4} for k, v in means.items()})
    y = 4.0 - 2.25 + 0.707 * (2.5 + 3.75 - 2.0 - 3.5)
    x = 4.5 - 1.5 + 0.707 * (3.75 + 3.5 - 2.5 - 2.0)
    assert profile.data["dominance"] == round(y, 3)
    assert profile.data["warmth"] == round(x, 3)
    assert profile.data["vector_length"] == round(math.hypot(x, y), 3)
    assert profile.data["angle_deg"] == round(math.degrees(math.atan2(y, x)) % 360.0, 3)
    assert profile.data["octant_means"] == means
    assert profile.resolver == "ipip_ipc_v1"
    assert profile.version == "1.0.0"


@pytest.mark.parametrize(
    "angle, code",
    [
        (0.0, "LM"),
        (22.4999, "LM"),
        (22.5, "NO"),
        (67.4999, "NO"),
        (67.5, "PA"),
        (112.5, "BC"),
        (157.5, "DE"),
        (202.5, "FG"),
        (247.5, "HI"),
        (292.5, "JK"),
        (337.4999, "JK"),
        (337.5, "LM"),
        (359.9999, "LM"),
    ],
)
def test_angle_band_boundaries(angle, code):
    assert classify_angle(angle)[0] == code


def test_vector_below_threshold_is_undifferentiated():
    # Only LM moves: x = 0.299, y = 0 -> r just under 0.3.
    profile = _resolve(_facets({"LM": NEUTRAL + 0.299}))
    assert profile.status == "complete"
    assert profile.data["style_label"] == "undifferentiated"
    assert profile.data["style_code"] is None
    assert profile.data["angle_deg"] is None


def test_vector_at_threshold_is_differentiated():
    # Zero baseline so x is exactly the float 0.3 (3.3 - 3.0 would round below it).
    facets = {octant: {"mean": 0.0, "n": 4} for octant in OCTANTS}
    facets["LM"]["mean"] = 0.3
    profile = _resolve(facets)
    assert profile.data["vector_length"] == 0.3
    assert profile.data["style_code"] == "LM"


def test_flat_profile_is_undifferentiated():
    profile = _resolve(_facets())
    assert profile.data["vector_length"] == 0.0
    assert profile.data["style_label"] == "undifferentiated"


def test_missing_octant_is_insufficient_data():
    facets = _facets()
    del facets["NO"]
    profile = _resolve(facets)
    assert profile.status == "insufficient_data"
    assert profile.data == {"missing_octants": ["NO"], "min_items": 3}


def test_octant_with_two_items_is_insufficient_data():
    facets = _facets()
    facets["HI"]["n"] = 2
    profile = _resolve(facets)
    assert profile.status == "insufficient_data"
    assert profile.data["missing_octants"] == ["HI"]


def test_three_of_four_items_is_enough():
    assert _resolve(_facets(n=3)).status == "complete"


@pytest.mark.parametrize("bad_mean", [None, "4.0", True])
def test_non_numeric_mean_is_rejected_at_boundary(bad_mean):
    facets = _facets()
    facets["PA"]["mean"] = bad_mean
    with pytest.raises(ValidationError):
        ProfileInputs(facet_scores=facets)


@pytest.mark.parametrize("bad_mean", [float("nan"), float("inf")])
def test_non_finite_mean_is_treated_as_missing(bad_mean):
    facets = _facets()
    facets["PA"]["mean"] = bad_mean
    profile = _resolve(facets)
    assert profile.status == "insufficient_data"
    assert profile.data["missing_octants"] == ["PA"]


def test_registry_dispatches_known_key():
    profile = resolve_profile("ipip_ipc_v1", ProfileInputs(facet_scores=_facets({"PA": 5.0})))
    assert profile is not None
    assert profile.data["style_code"] == "PA"


@pytest.mark.parametrize("key", [None, "", "   "])
def test_registry_returns_none_without_key(key):
    assert resolve_profile(key, ProfileInputs()) is None


def test_registry_unknown_key_logs_and_returns_none(caplog):
    with caplog.at_level("ERROR"):
        assert resolve_profile("bogus_v9", ProfileInputs()) is None
    assert "profile_resolver_unknown" in caplog.text


def test_output_survives_json_round_trip():
    profile = _resolve(_facets({"NO": 5.0}))
    dumped = json.dumps(profile.model_dump(mode="json"))
    assert DerivedProfile.model_validate(json.loads(dumped)) == profile
