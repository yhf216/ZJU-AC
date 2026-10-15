import pytest

from zju_ac.errors import ProtocolError
from zju_ac.gps import Coordinates


@pytest.mark.parametrize("lat,lon", [(91, 0), (0, 181), (float("nan"), 0), (True, 0), (10**400, 0)])
def test_coordinates_validated_before_any_network_request(lat, lon):
    with pytest.raises(ProtocolError):
        Coordinates(lat, lon)


def test_default_repr_does_not_expose_estimated_coordinates():
    assert "120.09" not in repr(Coordinates(30.30, 120.09))
