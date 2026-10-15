"""Bounded spherical distance fitting, independent of HTTP and terminal input."""

import math
from dataclasses import dataclass

from .errors import ProtocolError

EARTH_RADII = (6371000.0, 6372999.26)
MAX_RESIDUAL_METRES = 10.0


@dataclass(frozen=True, repr=False)
class Coordinates:
    latitude: float
    longitude: float

    def __post_init__(self) -> None:
        for value, limit in ((self.latitude, 90), (self.longitude, 180)):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not -limit <= value <= limit
            ):
                raise ProtocolError("GPS 坐标无效，已停止本次尝试。")


# Synthetic, non-collinear reference points; these are not the user's location.
PROBES = (Coordinates(30.2, 120.0), Coordinates(30.4, 120.2), Coordinates(30.2, 120.2))


def distance_metres(first: Coordinates, second: Coordinates, radius: float) -> float:
    lat1, lat2 = math.radians(first.latitude), math.radians(second.latitude)
    dlat = lat2 - lat1
    dlon = math.radians(second.longitude - first.longitude)
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(min(1, max(0, h))))


def valid_distance(value: object) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not 0 < value <= math.pi * max(EARTH_RADII)
    ):
        raise ProtocolError("GPS 接口未返回有效的米制距离，已停止本次尝试。")
    return float(value)


def estimate_location(distances: list[float]) -> Coordinates:
    """Fit all three distances; reject inconsistent measurements instead of guessing."""
    if len(distances) != len(PROBES):
        raise ProtocolError("GPS 距离样本不足，已停止本次尝试。")
    distances = [valid_distance(value) for value in distances]
    fits = []
    for radius in EARTH_RADII:
        try:
            fits.append(_fit(distances, radius))
        except ProtocolError:
            continue
    if not fits:
        raise ProtocolError("GPS 距离无法拟合有效坐标，已停止本次尝试。")
    residual, location = min(fits, key=lambda fit: fit[0])
    if residual > MAX_RESIDUAL_METRES:
        raise ProtocolError("GPS 距离不符合球面米制距离模型，已停止本次尝试。")
    return location


def _fit(distances: list[float], radius: float) -> tuple[float, Coordinates]:
    lat0 = sum(point.latitude for point in PROBES) / len(PROBES)
    lon0 = sum(point.longitude for point in PROBES) / len(PROBES)
    scale_x = radius * math.cos(math.radians(lat0))

    def coordinates(x: float, y: float) -> Coordinates:
        return Coordinates(lat0 + math.degrees(y / radius), lon0 + math.degrees(x / scale_x))

    # Flat squared-distance equations provide an initial guess only. Refinement
    # and the acceptance check both use great-circle distances, not flat circles.
    anchors = [
        (math.radians(p.longitude - lon0) * scale_x, math.radians(p.latitude - lat0) * radius)
        for p in PROBES
    ]
    x0, y0 = anchors[0]
    rows = [
        (
            2 * (px - x0),
            2 * (py - y0),
            distances[0] ** 2 - d**2 + px**2 + py**2 - x0**2 - y0**2,
        )
        for (px, py), d in zip(anchors[1:], distances[1:], strict=True)
    ]
    a, b, c = rows[0]
    d, e, f = rows[1]
    determinant = a * e - b * d
    x, y = (c * e - b * f) / determinant, (a * f - c * d) / determinant
    for _ in range(25):
        expected = [distance_metres(coordinates(x, y), p, radius) for p in PROBES]
        gx = [
            distance_metres(coordinates(x + 1, y), p, radius) - v
            for p, v in zip(PROBES, expected, strict=True)
        ]
        gy = [
            distance_metres(coordinates(x, y + 1), p, radius) - v
            for p, v in zip(PROBES, expected, strict=True)
        ]
        residuals = [d - v for d, v in zip(distances, expected, strict=True)]
        a, c = sum(v * v for v in gx), sum(v * v for v in gy)
        b = sum(u * v for u, v in zip(gx, gy, strict=True))
        d = sum(g * r for g, r in zip(gx, residuals, strict=True))
        e = sum(g * r for g, r in zip(gy, residuals, strict=True))
        determinant = a * c - b * b
        if abs(determinant) < 1e-12:
            raise ProtocolError("GPS 距离几何条件不足，已停止本次尝试。")
        dx, dy = (d * c - b * e) / determinant, (a * e - b * d) / determinant
        x, y = x + dx, y + dy
        if math.hypot(dx, dy) < 0.001:
            break
    location = coordinates(x, y)
    error = max(
        abs(distance_metres(location, p, radius) - d)
        for p, d in zip(PROBES, distances, strict=True)
    )
    return error, location
