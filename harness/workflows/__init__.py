"""Bundled workflow YAML files — package data for installed distributions.

When the harness is installed via ``uv tool install .`` or ``pip install .``,
the workflow YAMLs in this directory are accessible via
``importlib.resources.files("harness.workflows")``. The CLI falls back to
this path when neither ``--workflows-dir`` nor ``$HARNESS_WORKFLOWS_DIR`` is
provided and no local ``./workflows/`` directory exists in the CWD.

**Maintenance note:** These files are intentional copies of the top-level
``workflows/`` directory. Both must be updated in tandem when a workflow
changes — edit ``workflows/<name>.yaml`` *and* ``harness/workflows/<name>.yaml``
together. The test ``tests/unit/test_workflows_dir_resolution.py::
TestPackageMirror`` asserts content equivalence and will fail on CI if the
copies drift apart.

Do **not** import from this package directly — use
``harness.cli.run._resolve_workflows_dir`` for path resolution.
"""
