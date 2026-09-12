from uuid import uuid4

import pytest
from ppe_domain import ProcessGraphError, calculate_critical_path


def test_calculate_critical_path_supports_parallel_branches() -> None:
    start = uuid4()
    long_branch = uuid4()
    short_branch = uuid4()
    finish = uuid4()
    result = calculate_critical_path(
        {
            start: (2, []),
            long_branch: (5, [start]),
            short_branch: (1, [start]),
            finish: (3, [long_branch, short_branch]),
        }
    )

    assert result.step_ids == (start, long_branch, finish)
    assert result.cycle_time_seconds == 10


def test_calculate_critical_path_rejects_unknown_predecessor() -> None:
    with pytest.raises(ProcessGraphError, match="Unknown process step"):
        calculate_critical_path({uuid4(): (1, [uuid4()])})
