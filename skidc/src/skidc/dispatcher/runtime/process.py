"""Compatibility exports for the shared Docker exec implementation."""
from skidc.execution.process import ManagedProcess, ProcessResult, EXEC_KILL_JOIN_TIMEOUT_SECONDS

__all__ = ['ManagedProcess', 'ProcessResult', 'EXEC_KILL_JOIN_TIMEOUT_SECONDS']
