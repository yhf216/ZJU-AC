import math

import pytest

from zju_ac.errors import ProtocolError
from zju_ac.gps import PROBES, Coordinates, estimate_location, valid_distance


def oracle_distance(first, second, radius=6371000.0):
    """Independent vector/atan2 oracle, rather than the production haversine."""

    def unit(point):
        lat, lon = math.radians(point.latitude), math.radians(point.longitude)
        return math.cos(lat) * math.cos(lon), math.cos(lat) * math.sin(lon), math.sin(lat)

    a, b = unit(first), unit(second)
    cross = (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])
    angle = math.atan2(
        math.sqrt(sum(v * v for v in cross)), sum(x * y for x, y in zip(a, b, strict=False))
    )
    return radius * angle


@pytest.mark.parametrize("radius", [6371000.0, 6372999.26])
@pytest.mark.parametrize(
    "target",
    [
        Coordinates(30.30, 120.09),
        Coordinates(30.26, 120.12),
        Coordinates(30.19, 120.12),
        Coordinates(30.53, 120.73),
        Coordinates(29.99, 122.20),
        Coordinates(30.30, 120.10),  # Near the first two probes' line.
    ],
)
def test_three_distances_recover_location_despite_metre_rounding(radius, target):
    measurements = [round(oracle_distance(p, target, radius)) for p in PROBES]
    result = estimate_location(measurements)
    assert oracle_distance(result, target) < 5


@pytest.mark.parametrize("transform", [lambda d: d / 1000, lambda d: d - 500])
def test_incompatible_units_or_range_remainder_are_not_used_as_coordinates(transform):
    target = Coordinates(30.30, 120.09)
    measurements = [transform(oracle_distance(p, target)) for p in PROBES]
    with pytest.raises(ProtocolError):
        estimate_location(measurements)


def test_inconsistent_third_measurement_prevents_submission_candidate():
    measurements = [oracle_distance(p, Coordinates(30.30, 120.09)) for p in PROBES]
    measurements[-1] += 2000
    with pytest.raises(ProtocolError):
        estimate_location(measurements)


@pytest.mark.parametrize("values", [[], [100], [100, 200], [100, 200, 300, 400]])
def test_missing_or_extra_measurements_rejected(values):
    with pytest.raises(ProtocolError):
        estimate_location(values)


@pytest.mark.parametrize(
    "value", [None, True, "100", 0, -1, float("nan"), float("inf"), 21_000_000, 10**400]
)
def test_distance_validation_rejects_unknown_or_nonphysical_values(value):
    with pytest.raises(ProtocolError):
        valid_distance(value)


@pytest.mark.parametrize("lat,lon", [(91, 0), (0, 181), (float("nan"), 0), (True, 0), (10**400, 0)])
def test_coordinates_validated_before_any_network_request(lat, lon):
    with pytest.raises(ProtocolError):
        Coordinates(lat, lon)


def test_default_repr_does_not_expose_estimated_coordinates():
    assert "120.09" not in repr(Coordinates(30.30, 120.09))
