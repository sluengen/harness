"""Linear webhook intake — sibling process to the harness.

Lives outside the ``harness`` Python package (SPEC §2, §17.4): receives
Linear webhook events and shells out to ``harness run`` via the CLI.
"""
