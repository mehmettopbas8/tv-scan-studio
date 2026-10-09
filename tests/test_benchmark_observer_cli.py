import json
from pathlib import Path
import sqlite3
import subprocess
import sys

from test_benchmark_baseline import old_database


SCRIPT = Path(__file__).resolve().parents[1] / 'tools' / 'observe_baseline_benchmark.py'


def test_ready_handshake_precedes_timeout_without_publishing_manifest(tmp_path):
    database = tmp_path / 'old.db'
    source = old_database()
    source.commit()
    with sqlite3.connect(database) as target:
        source.backup(target)
    source.close()
    output = tmp_path / 'manifest.json'
    result = subprocess.run([sys.executable, str(SCRIPT), '--database', str(database),
        '--project', '1', '--tasks', '1,2', '--output', str(output), '--timeout', '.1'],
        capture_output=True, text=True, timeout=15)
    assert result.returncode != 0
    ready = json.loads(result.stdout.splitlines()[0])
    assert ready['status'] == 'ready' and ready['task_ids'] == [1, 2]
    assert 'timed out' in result.stderr
    assert not output.exists()


def test_nonfinite_timeout_rejected_before_database_open(tmp_path):
    result = subprocess.run([sys.executable, str(SCRIPT), '--database', str(tmp_path / 'missing.db'),
        '--project', '1', '--tasks', '1', '--output', str(tmp_path / 'manifest.json'),
        '--timeout', 'nan'], capture_output=True, text=True, timeout=15)
    assert result.returncode != 0 and 'positive timeout' in result.stderr
    assert result.stdout == ''
