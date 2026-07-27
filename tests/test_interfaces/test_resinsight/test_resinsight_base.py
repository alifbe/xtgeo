"""Unit tests for the shared ResInsight read/write base helpers."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from xtgeo.interfaces.resinsight._resinsight_base import _BaseResInsightDataRW


def test_resolve_case_returns_case_object_unchanged():
    base = _BaseResInsightDataRW(instance_or_port=None)
    case = SimpleNamespace(name="KEEP")
    assert base.resolve_case(case) is case


@pytest.mark.parametrize("bad", [123, object(), None, SimpleNamespace(name=42)])
def test_resolve_case_rejects_invalid_argument(bad):
    base = _BaseResInsightDataRW(instance_or_port=None)
    with pytest.raises(TypeError, match="case must be a case name"):
        base.resolve_case(bad)
