"""Contract tests for the clean-room Real Spirit engine."""

import pytest

from kicad_track_gloss.engine.model import AddedSegment, BoardModel, GlossResult, Segment
from kicad_track_gloss.engine.real_spirit import (build_topology, extract_chains,
                                                  localized_drc_remainder,
                                                  plan_selected_copper)
from kicad_track_gloss.engine.real_spirit.obstacles import (
    octolinear_disk, segment_penetrates, track_envelope)


def segment(a, b, key, *, net=1, layer=0):
    return Segment(
        a[0], a[1], b[0], b[1], 0.2, layer, net, key,
        net_name="N", clearance=0.2)


def model(*segments):
    return BoardModel(list(segments), minimum_clearance=0.2)


def terminal_at(chains, location):
    for chain in chains:
        if chain.start.point == location:
            return chain.start
        if chain.end.point == location:
            return chain.end
    raise AssertionError("terminal was not found")


def test_three_way_collinear_junction_has_one_sliding_branch():
    board = model(
        segment((-2, 0), (0, 0), "left"),
        segment((0, 0), (2, 0), "right"),
        segment((0, 0), (0, 2), "branch"),
    )
    topology = build_topology(board)
    junction = topology.junctions[(1, 0, (0.0, 0.0))]

    assert len(junction.rails) == 1
    assert junction.sliding_rails("branch") == junction.rails
    assert junction.sliding_rails("left") == ()
    assert junction.sliding_rails("right") == ()

    chains = extract_chains(board, {"left", "right", "branch"})
    branch = next(chain for chain in chains if "branch" in chain.keys)
    assert terminal_at((branch,), (0.0, 0.0)).kind == "rail"
    rails = next(terminal for terminal in (branch.start, branch.end)
                 if terminal.point == (0.0, 0.0)).rails
    assert rails[0].start == (-2.0, 0.0)
    assert rails[0].end == (2.0, 0.0)


def test_three_way_non_collinear_junction_is_a_fixed_node():
    board = model(
        segment((0, 0), (2, 0), "east"),
        segment((0, 0), (-1, -2), "northwest"),
        segment((0, 0), (-1, 2), "southwest"),
    )
    topology = build_topology(board)
    junction = topology.junctions[(1, 0, (0.0, 0.0))]
    assert junction.rails == ()

    chains = extract_chains(
        board, {"east", "northwest", "southwest"})
    assert all(terminal_at((chain,), (0.0, 0.0)).kind == "node"
               for chain in chains)


def test_four_way_crossing_decomposes_into_four_t_interpretations():
    board = model(
        segment((-2, 0), (0, 0), "left"),
        segment((0, 0), (2, 0), "right"),
        segment((0, -2), (0, 0), "top"),
        segment((0, 0), (0, 2), "bottom"),
    )
    junction = build_topology(board).junctions[(1, 0, (0.0, 0.0))]
    assert len(junction.rails) == 2

    interpretations = {
        (branch, rail.first_key, rail.second_key)
        for branch in junction.incident_keys
        for rail in junction.sliding_rails(branch)
    }
    assert len(interpretations) == 4
    assert {branch for branch, _first, _second in interpretations} == {
        "left", "right", "top", "bottom"}


def test_unselected_collinear_copper_is_a_fixed_sliding_rail():
    board = model(
        segment((-2, 0), (0, 0), "left"),
        segment((0, 0), (2, 0), "right"),
        segment((0, 0), (0, 2), "branch"),
    )
    chains = extract_chains(board, {"branch"})
    assert len(chains) == 1
    assert chains[0].keys == ("branch",)
    sliding = terminal_at(chains, (0.0, 0.0))
    assert sliding.kind == "rail"
    assert sliding.rails[0].start == (-2.0, 0.0)
    assert sliding.rails[0].end == (2.0, 0.0)


def test_unobstructed_connection_contracts_to_its_straight_cord():
    board = model(
        segment((0, 0), (0, 2), "a"),
        segment((0, 2), (3, 2), "b"),
        segment((3, 2), (3, 0), "c"),
    )
    result = plan_selected_copper(board, {"a", "b", "c"}, min_gain=0.2)

    assert result.changed
    assert result.saved_mm == 4.0
    assert len(result.additions) == 1
    assert {result.additions[0].start, result.additions[0].end} == {
        (0.0, 0.0), (3.0, 0.0)}


def test_selected_t_branch_slides_while_its_unselected_rail_stays_unchanged():
    board = model(
        segment((-2, 0), (0, 0), "left"),
        segment((0, 0), (2, 0), "right"),
        segment((0, 0), (2, 2), "branch"),
    )
    result = plan_selected_copper(board, {"branch"}, min_gain=0.2)

    assert result.changed
    assert result.remove_keys == ["branch"]
    assert len(result.additions) == 1
    assert {result.additions[0].start, result.additions[0].end} == {
        (2.0, 0.0), (2.0, 2.0)}


def test_internal_segment_translation_stops_at_physical_clearance():
    selected = [
        segment((0, 0), (1, 1), "a"),
        segment((1, 1), (4, 1), "b"),
        segment((4, 1), (5, 0), "c"),
    ]
    blocker = segment((1, 0), (4, 0), "blocker", net=2)
    board = model(*(selected + [blocker]))

    result = plan_selected_copper(board, {"a", "b", "c"}, min_gain=0.2)

    assert result.changed
    assert result.saved_mm > 0.49
    assert result.fixed_point


def test_round_clearance_is_one_clean_octolinear_polygon():
    polygon = octolinear_disk((0, 0), 1.0)
    assert len(polygon) == 8
    for start, end in zip(polygon, polygon[1:] + polygon[:1]):
        dx, dy = abs(end[0] - start[0]), abs(end[1] - start[1])
        assert dx == pytest.approx(0.0, abs=1e-12) or \
            dy == pytest.approx(0.0, abs=1e-12) or \
            dx == pytest.approx(dy, abs=1e-12)
    assert not segment_penetrates((-2, 1), (2, 1), polygon)
    assert segment_penetrates((-2, 0), (2, 0), polygon)


def test_round_track_ends_are_integrated_in_one_clean_polygon():
    moving = segment((0, 3), (4, 3), "moving")
    foreign = segment((0, 0), (4, 0), "foreign", net=2)
    polygon = track_envelope(model(moving, foreign), moving, foreign)

    assert len(polygon) <= 10
    for start, end in zip(polygon, polygon[1:] + polygon[:1]):
        dx, dy = abs(end[0] - start[0]), abs(end[1] - start[1])
        assert dx == pytest.approx(0.0, abs=1e-12) or \
            dy == pytest.approx(0.0, abs=1e-12) or \
            dx == pytest.approx(dy, abs=1e-12)


def test_one_drc_localization_drops_the_nearest_modified_net_only():
    first = segment((0, 0), (2, 0), "first", net=1)
    second = segment((0, 10), (2, 10), "second", net=2)
    board = model(first, second)
    plan = GlossResult(
        remove_keys=["first", "second"],
        additions=[
            AddedSegment((0, 0), (2, 0), 0.2, 0, 1, 0.2),
            AddedSegment((0, 10), (2, 10), 0.2, 0, 2, 0.2),
        ])

    remainder = localized_drc_remainder(
        board, {"first", "second"}, plan, ((1.0, 9.9),))

    assert remainder.remove_keys == ["first"]
    assert [addition.net_id for addition in remainder.additions] == [1]
