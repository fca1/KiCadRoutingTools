"""Optional board graphics explaining Smart Octo obstacle geometry."""

from __future__ import annotations

from ..engine.smart_octo import collect_diagnostic_polygons


GROUP_NAME = "TrackGloss Smart Octo Overlay"
LAYER_NAME = "TrackGloss Obstacles"
ROLE_WIDTH_MM = {"moving": 0.05, "obstacle": 0.08, "effective": 0.15}


def _existing_group(board):
    return next((group for group in board.Groups()
                 if str(group.GetName()) == GROUP_NAME), None)


def remove_overlay(board):
    group = _existing_group(board)
    if group is None:
        return 0
    items = list(group.GetItems())
    for item in items:
        group.RemoveItem(item)
        board.RemoveNative(item)
    board.RemoveNative(group)
    return len(items)


def _information_layer(pcbnew, board):
    count = max(1, int(board.GetUserDefinedLayerCount()))
    candidates = [getattr(pcbnew, "User_{}".format(index))
                  for index in range(1, count + 1)
                  if hasattr(pcbnew, "User_{}".format(index))]
    for layer in candidates:
        if str(board.GetLayerName(layer)) == LAYER_NAME:
            return layer
    used = {int(item.GetLayer()) for item in board.GetDrawings()}
    for layer in reversed(candidates):
        name = str(board.GetLayerName(layer))
        if int(layer) not in used and name in (
                "User.{}".format(candidates.index(layer) + 1), ""):
            if not board.SetLayerName(layer, LAYER_NAME):
                raise RuntimeError("KiCad could not name the information layer")
            return layer
    raise RuntimeError(
        "No unused User.* layer is available for the Smart Octo overlay")


def create_overlay(adapter, board, snapshot, limit=600):
    """Create one grouped, removable, non-copper diagnostic overlay."""
    pcbnew = adapter.pcbnew
    polygons = collect_diagnostic_polygons(
        snapshot.model, snapshot.eligible_keys, limit=limit)
    if not polygons:
        return 0, ""
    layer = _information_layer(pcbnew, board)
    group = pcbnew.PCB_GROUP(board)
    group.SetName(GROUP_NAME)
    board.Add(group)
    created = []
    try:
        for polygon in polygons:
            width = adapter.from_mm(ROLE_WIDTH_MM[polygon.role])
            for start, end in zip(
                    polygon.points, polygon.points[1:] + polygon.points[:1]):
                shape = pcbnew.PCB_SHAPE(board)
                shape.SetShape(pcbnew.SHAPE_T_SEGMENT)
                shape.SetStart(adapter.vector(start))
                shape.SetEnd(adapter.vector(end))
                shape.SetWidth(width)
                shape.SetLayer(layer)
                shape.SetLocked(True)
                board.Add(shape)
                group.AddItem(shape)
                created.append(shape)
        group.SetLocked(True)
        return len(polygons), str(board.GetLayerName(layer))
    except Exception:
        for item in created:
            try:
                board.RemoveNative(item)
            except Exception:
                pass
        try:
            board.RemoveNative(group)
        except Exception:
            pass
        raise


def toggle_overlay(adapter, board, snapshot):
    removed = remove_overlay(board)
    if removed:
        return False, removed, LAYER_NAME
    count, layer = create_overlay(adapter, board, snapshot)
    return True, count, layer


__all__ = ("GROUP_NAME", "LAYER_NAME", "create_overlay", "remove_overlay",
           "toggle_overlay")
