from types import SimpleNamespace

from kicad_track_gloss.kicad.reader import (
    _analytic_pad_regions, _via_obstacles)


class _Layers:
    def __init__(self, values):
        self.values = values

    def Seq(self):
        return self.values


class _Board:
    def GetEnabledLayers(self):
        return _Layers((0, 2))


class _Adapter:
    pcbnew = SimpleNamespace(IsCopperLayer=lambda _layer: True)

    @staticmethod
    def point_mm(point):
        return point.x, point.y

    @staticmethod
    def to_mm(value):
        return float(value)


class _Item:
    def GetPosition(self):
        return SimpleNamespace(x=10.0, y=20.0)

    def GetLayerSet(self):
        return _Layers((0, 2))

    def GetWidth(self, layer):
        return {0: 0.4, 2: 0.6}[layer]

    def GetOwnClearance(self, layer):
        return {0: 0.1, 2: 0.2}[layer]

    def GetNetCode(self):
        return 7

    def GetSize(self):
        return SimpleNamespace(x=1.0, y=2.0)

    def GetOrientationDegrees(self):
        return 45.0

    def GetRoundRectCornerRadius(self):
        return 0.25


def test_via_padstack_keeps_resolved_rule_and_diameter_per_layer():
    obstacles = _via_obstacles(_Adapter(), _Board(), _Item())

    assert [(item.layers, item.radius, item.clearance)
            for item in obstacles] == [
                ((0,), 0.2, 0.1),
                ((2,), 0.3, 0.2),
            ]


def test_analytic_pad_keeps_resolved_rule_per_layer():
    regions = _analytic_pad_regions(
        _Adapter(), _Item(), (0, 2), 7, "roundrect")

    assert [(item.layers, item.clearance) for item in regions] == [
        ((0,), 0.1),
        ((2,), 0.2),
    ]
