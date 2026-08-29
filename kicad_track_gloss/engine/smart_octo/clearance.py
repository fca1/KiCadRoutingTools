"""One authoritative clearance value per Smart Octo object."""


def effective_clearance(model, item):
    """Return KiCad's evaluated item clearance or its netclass floor."""
    if item.clearance >= 0.0:
        return max(float(model.minimum_clearance), float(item.clearance))
    return max(float(model.minimum_clearance),
               float(model.net_clearances.get(item.net_id, 0.0)))


__all__ = ("effective_clearance",)
