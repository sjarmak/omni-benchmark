from hypothesis import example, given, strategies as st
import pytest

from omni_benchmark.json_nesting import validate_json_nesting


@given(st.lists(st.booleans(), min_size=0, max_size=80), st.text())
@example([True] * 65, "[]{}")
def test_nesting_limit_depends_on_containers_not_string_contents(
    wrappers: list[bool], leaf: str
) -> None:
    value = leaf
    for use_object in wrappers:
        value = {"value": value} if use_object else [value]
    if len(wrappers) > 64:
        with pytest.raises(RecursionError, match="nesting"):
            validate_json_nesting(value)
    else:
        validate_json_nesting(value)


@pytest.mark.parametrize("depth", [64, 65, 2_000])
def test_nesting_boundary(depth: int) -> None:
    value = 0
    for _ in range(depth):
        value = [value]
    if depth > 64:
        with pytest.raises(RecursionError, match="nesting"):
            validate_json_nesting(value)
    else:
        validate_json_nesting(value)
