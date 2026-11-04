"""Tests: UI action feedback helpers (flash + action guard)."""

import unittest

from ui import feedback


class _FakeSt:
    def __init__(self):
        self.calls = []

    def success(self, msg):
        self.calls.append(("success", msg))

    def info(self, msg):
        self.calls.append(("info", msg))

    def warning(self, msg):
        self.calls.append(("warning", msg))

    def error(self, msg):
        self.calls.append(("error", msg))


class TestFeedback(unittest.TestCase):
    def test_flash_survives_and_clears(self):
        state = {}
        feedback.flash(state, "success", "Saved.")
        feedback.flash(state, "error", "Broke.")
        queued = feedback.pop_flash(state)
        self.assertEqual([q["kind"] for q in queued], ["success", "error"])
        self.assertEqual(feedback.pop_flash(state), [])

    def test_render_flash_uses_kind_renderers(self):
        state = {}
        feedback.flash(state, "warning", "Careful.")
        fake = _FakeSt()
        feedback.render_flash(state, fake)
        self.assertEqual(fake.calls, [("warning", "Careful.")])
        self.assertEqual(state["_flash_messages"], [])

    def test_action_guard_converts_exception_to_error(self):
        state = {}
        fake = _FakeSt()
        logged = []
        with feedback.action_guard(state, "Compile Packet", fake, log_fn=lambda a, d: logged.append(a)):
            raise RuntimeError("disk full")
        self.assertEqual(len(fake.calls), 1)
        kind, message = fake.calls[0]
        self.assertEqual(kind, "error")
        self.assertIn("Compile Packet failed", message)
        self.assertIn("disk full", message)
        self.assertEqual(state["last_action_error"]["action"], "Compile Packet")
        self.assertEqual(logged, ["ui_action_failed"])

    def test_action_guard_passes_through_success(self):
        state = {}
        fake = _FakeSt()
        with feedback.action_guard(state, "Fine Action", fake):
            state["done"] = True
        self.assertTrue(state["done"])
        self.assertEqual(fake.calls, [])
        self.assertNotIn("last_action_error", state)

    def test_blank_case_is_not_touched_until_action_or_data(self):
        from ui import state as ui_state

        state = {}
        ui_state.load_case(state, ui_state.empty_notice(), ui_state.empty_folio(), {})
        self.assertFalse(ui_state.has_case_data(state))
        self.assertFalse(ui_state.is_case_touched(state))

        # Explicit user action marks the case touched even if fields are still empty
        ui_state.mark_case_touched(state)
        self.assertTrue(ui_state.is_case_touched(state))

        # Loading a populated case starts in a touched state automatically
        state2 = {}
        ui_state.load_case(state2, {"case_id": "CB-100"}, ui_state.empty_folio(), {})
        self.assertTrue(ui_state.has_case_data(state2))
        self.assertTrue(ui_state.is_case_touched(state2))


if __name__ == "__main__":
    unittest.main()
