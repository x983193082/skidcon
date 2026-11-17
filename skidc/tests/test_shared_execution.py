import subprocess
import sys


def test_ctf_can_import_shared_drivers_without_legacy_engine():
    result = subprocess.run([sys.executable, '-c',
        'from skidc.execution.codex import CodexDriver; from skidc.execution.claudecode import ClaudeCodeDriver; '
        'import sys; assert not any(x.startswith(("skidc.dispatcher", "skidc.server")) for x in sys.modules)'],
        capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_legacy_and_ctf_share_the_same_driver_implementation():
    from skidc.execution.codex import CodexDriver
    from skidc.execution.claudecode import ClaudeCodeDriver
    from skidc.execution.base import DriverResult, WorkerSettings
    from skidc.dispatcher.workers.adapters.codex import CodexDriver as OldCodex
    from skidc.dispatcher.workers.adapters.claudecode import ClaudeCodeDriver as OldClaude
    from skidc.dispatcher.workers.base import DriverResult as OldResult
    assert (CodexDriver, ClaudeCodeDriver, DriverResult) == (OldCodex, OldClaude, OldResult)
    worker = WorkerSettings(name='ctf', env={'CODEX_MODEL': 'model', 'CODEX_BASE_URL': 'https://model.invalid/v1'})
    command = CodexDriver().build_execute(worker, 'prompt', None)
    assert command.argv[:2] == ['codex', 'exec']
    session = ClaudeCodeDriver().prepare_session()
    assert ClaudeCodeDriver().build_conclude(worker, 'conclude', session)[1:3] == ['-r', session]
