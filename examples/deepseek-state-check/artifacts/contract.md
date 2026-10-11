Implement can_transition(src: str, dst: str) -> bool for the RMS.
Known states: draft, reviewing, approved, implemented, verified, deprecated.
Allow same-state updates, forward draft->reviewing->approved->implemented->verified,
and any known state->deprecated. Reject all other or unknown states.
Pure Python, no imports, no I/O, no classes. Module only constants and functions.
Return JSON {"files":{"state_policy.py":"complete Python source"}}.