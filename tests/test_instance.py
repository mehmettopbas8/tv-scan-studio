import os
from tv_scan_studio.instance import desktop_instance
from uuid import uuid4
import pytest


@pytest.mark.skipif(os.name != "nt", reason="Windows named mutex davranışı")
def test_second_desktop_instance_is_rejected_until_first_exits():
    name = f"Local\\TVScanStudioTest{uuid4().hex}"
    with desktop_instance(name) as first:
        assert first
        with desktop_instance(name) as second:
            assert not second
    with desktop_instance(name) as next_launch:
        assert next_launch
