"""Coordinates for configured GPS submissions; no distance inference."""

from dataclasses import dataclass

from .errors import ProtocolError


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
