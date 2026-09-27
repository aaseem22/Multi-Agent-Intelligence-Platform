"""`requires_runtime` skips a test until DepartmentAgent.run is implemented by the core runtime
(built in parallel during Phase 1). After the Phase 2 merge these tests run normally."""

import inspect

import pytest

from app.core.base_agent import DepartmentAgent

RUNTIME_READY = "NotImplementedError" not in inspect.getsource(DepartmentAgent.run)

requires_runtime = pytest.mark.skipif(
    not RUNTIME_READY, reason="DepartmentAgent.run not implemented yet (core runtime pending)"
)
