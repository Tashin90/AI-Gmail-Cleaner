"""Streamlit wrapper for the local drag-select review table component."""
from pathlib import Path

import streamlit.components.v1 as components


_COMPONENT_PATH = Path(__file__).resolve().parent / 'drag_select_component'
_drag_select_component = components.declare_component(
    'gmail_drag_select_table',
    path=str(_COMPONENT_PATH),
)


def drag_select_table(rows, selected_ids, selection_epoch, key):
    """Render the email table and return selected Gmail Message IDs."""
    return _drag_select_component(
        rows=rows,
        selected_ids=list(selected_ids),
        selection_epoch=selection_epoch,
        default=list(selected_ids),
        key=key,
    )
