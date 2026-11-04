"""
Action feedback helpers for the Streamlit UI.

Rule: every action (button, form submit, callback) ends with a visible
result — success, warning, or error — never silence and never a raw
traceback. Two mechanisms:

- flash(state, kind, message): queues a one-time message that is shown
  on the NEXT run (survives st.rerun) and then cleared. Use this in
  callbacks and before st.rerun() calls.
- render_flash(state): called once per run by app.py; displays and
  clears queued messages.
- action_guard(state, action_label): context manager for inline button
  handlers — exceptions become a friendly st.error with the reason and
  are recorded in state["last_action_error"] instead of crashing the page.
"""

import traceback
from contextlib import contextmanager
from typing import Any, Iterator, MutableMapping

_FLASH_KEY = "_flash_messages"


def flash(state: MutableMapping[str, Any], kind: str, message: str) -> None:
    """Queues a one-time message ('success' | 'info' | 'warning' | 'error')."""
    queue = list(state.get(_FLASH_KEY) or [])
    queue.append({"kind": kind, "message": message})
    state[_FLASH_KEY] = queue


def pop_flash(state: MutableMapping[str, Any]) -> list:
    """Returns and clears queued flash messages."""
    queue = list(state.get(_FLASH_KEY) or [])
    state[_FLASH_KEY] = []
    return queue


def render_flash(state: MutableMapping[str, Any], st_module: Any) -> None:
    """Displays queued flash messages via the given Streamlit module."""
    for entry in pop_flash(state):
        renderer = getattr(st_module, entry.get("kind") or "info", st_module.info)
        renderer(entry.get("message") or "")


@contextmanager
def action_guard(state: MutableMapping[str, Any], action_label: str, st_module: Any,
                 log_fn: Any = None) -> Iterator[None]:
    """Runs an action; on exception shows a related, actionable error.

    The full traceback goes to the server log / audit details, never to a
    raw Streamlit exception page. state["last_action_error"] records the
    failure so surrounding UI can react.
    """
    try:
        yield
    except Exception as exc:  # noqa: BLE001 - UI boundary: never crash the page
        detail = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
        state["last_action_error"] = {"action": action_label, "error": detail}
        st_module.error(
            f"**{action_label} failed.** {exc} "
            "Your case data is unchanged — correct the issue and try again. "
            "If this keeps happening, note the time and check the server log."
        )
        if log_fn is not None:
            try:
                log_fn("ui_action_failed", {"action": action_label, "error": detail,
                                            "message": f"{action_label} failed in the UI"})
            except Exception:
                pass
