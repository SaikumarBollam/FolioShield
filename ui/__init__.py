"""
Streamlit UI support package (Phase 3 P2 extraction from app.py).

app.py remains the single Streamlit entry point; this package holds the
testable, non-rendering logic that used to live inline in the script:

- ui.state          session-state primitives (factories, actor/log, case loading)
- ui.evidence_actions  evidence callbacks (collect, ZIP import, remove, vision)
- ui.persistence    exhibit/case store accessors and durable case persistence

Dependency rule: ui/* may import core/* and embedded/*; app.py imports
ui/*; nothing imports app. Callbacks receive their collaborators
(session-state mapping, actor/log callables, store accessors, persist
hook, vision engine) as parameters so they can be unit-tested with fakes
— app.py binds the real Streamlit session state via thin wrappers that
keep the historical names and signatures.
"""
