"""Process-local settings dialog shared by normal and diagnostic actions."""

from __future__ import annotations

import wx

from ..configuration import get_session_config, update_session_config
from ..version import __version__


_HELP = {
    "minimum": (
        "Minimum copper length, in millimetres, that a candidate must save. "
        "Smaller values accept finer changes but can increase search work."),
    "total_budget": (
        "Maximum interactive planning and KiCad DRC budget in seconds. A plan "
        "is never applied if its required validation did not finish."),
    "native_drc": (
        "Run KiCad's native DRC for every selected scope, whether it contains "
        "one connection or multiple nets. Unchecking this option skips the "
        "final native gate; the internal geometric safety checks remain active."),
}


def _tooltip(control, text):
    control.SetToolTip(text)
    return control


def _double_control(parent, value, minimum, maximum, increment, digits):
    control = wx.SpinCtrlDouble(
        parent, min=minimum, max=maximum, initial=float(value),
        inc=increment, style=wx.SP_ARROW_KEYS)
    control.SetDigits(digits)
    return control


def show_session_settings(parent=None):
    """Edit session policy and return True only when Close applies it."""
    policy = get_session_config()
    dialog = wx.Dialog(
        parent,
        title="KiCad Track Gloss {} — Session Settings".format(__version__),
        size=(650, 430),
        style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
    outer = wx.BoxSizer(wx.VERTICAL)
    explanation = wx.StaticText(
        dialog,
        label=("No straight track segment is selected. Adjust the settings "
               "used by Track Gloss and its Diagnostic action, or Cancel and "
               "select at least one straight track segment."))
    explanation.Wrap(610)
    outer.Add(explanation, 0, wx.EXPAND | wx.ALL, 12)

    grid = wx.FlexGridSizer(cols=2, vgap=9, hgap=14)
    grid.AddGrowableCol(1, 1)

    def add_row(label_text, control, help_text):
        label = _tooltip(wx.StaticText(dialog, label=label_text), help_text)
        _tooltip(control, help_text)
        grid.Add(label, 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(control, 1, wx.EXPAND)

    minimum = _double_control(
        dialog, policy.gloss.minimum_saved_length_mm, 0.1, 100.0,
        0.1, 1)
    total_budget = _double_control(
        dialog, policy.timing.interactive_total_time_budget_seconds,
        0.5, 600.0, 0.5, 1)
    native_drc = wx.CheckBox(dialog, label="Use KiCad native DRC")
    native_drc.SetValue(policy.safety.use_kicad_native_drc)

    add_row("Native DRC", native_drc, _HELP["native_drc"])
    add_row("Minimum saved length (mm)", minimum, _HELP["minimum"])
    add_row("Total interactive budget (s)", total_budget,
            _HELP["total_budget"])
    outer.Add(grid, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)

    note = wx.StaticText(
        dialog,
        label=("Close applies these values only to the current KiCad session. "
               "Cancel discards every edit. Packaged defaults are not changed."))
    note.Wrap(610)
    outer.Add(note, 0, wx.EXPAND | wx.ALL, 12)

    buttons = wx.StdDialogButtonSizer()
    close_button = wx.Button(dialog, wx.ID_OK, label="Close")
    cancel_button = wx.Button(dialog, wx.ID_CANCEL, label="Cancel")
    buttons.AddButton(close_button)
    buttons.AddButton(cancel_button)
    buttons.Realize()
    outer.Add(buttons, 0, wx.ALIGN_RIGHT | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
    dialog.SetSizer(outer)
    dialog.CentreOnParent()

    def apply_and_close(_event):
        try:
            update_session_config(
                minimum_saved_length_mm=minimum.GetValue(),
                interactive_total_time_budget_seconds=total_budget.GetValue(),
                use_kicad_native_drc=native_drc.GetValue())
        except ValueError as error:
            warning = wx.MessageDialog(
                dialog, str(error), "Invalid Track Gloss setting",
                wx.OK | wx.ICON_WARNING)
            try:
                warning.ShowModal()
            finally:
                warning.Destroy()
            return
        dialog.EndModal(wx.ID_OK)

    close_button.Bind(wx.EVT_BUTTON, apply_and_close)
    try:
        close_button.SetDefault()
        return dialog.ShowModal() == wx.ID_OK
    finally:
        dialog.Destroy()
