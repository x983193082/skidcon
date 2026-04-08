"""
Flow Controller - 状态机控制
管理渗透测试流程状态
"""
from typing import Dict, Any, Optional, List, Callable
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
import asyncio


class FlowState(Enum):
    """流程状态"""
    INIT = "init"
    RECON = "recon"
    SCANNING = "scanning"
    EXPLOITING = "exploiting"
    POST_EXPLOIT = "post_exploit"
    REPORTING = "reporting"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"


class TransitionType(Enum):
    """状态转换类型"""
    SUCCESS = "success"
    FAILURE = "failure"
    SKIP = "skip"
    MANUAL = "manual"


@dataclass
class StateTransition:
    """状态转换记录"""
    from_state: FlowState
    to_state: FlowState
    transition_type: TransitionType
    timestamp: datetime
    reason: str = ""
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FlowContext:
    """流程上下文"""
    target: str
    scope: List[str] = field(default_factory=list)
    current_state: FlowState = FlowState.INIT
    findings: List[Dict[str, Any]] = field(default_factory=list)
    artifacts: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


class FlowController:
    """
    流程控制器
    
    使用状态机管理渗透测试流程：
    INIT -> RECON -> SCANNING -> EXPLOITING -> POST_EXPLOIT -> REPORTING -> COMPLETED
    """
    
    # 定义允许的状态转换
    ALLOWED_TRANSITIONS: Dict[FlowState, List[FlowState]] = {
        FlowState.INIT: [FlowState.RECON, FlowState.FAILED],
        FlowState.RECON: [FlowState.SCANNING, FlowState.FAILED, FlowState.PAUSED],
        FlowState.SCANNING: [FlowState.EXPLOITING, FlowState.REPORTING, FlowState.FAILED, FlowState.PAUSED],
        FlowState.EXPLOITING: [FlowState.POST_EXPLOIT, FlowState.SCANNING, FlowState.REPORTING, FlowState.FAILED, FlowState.PAUSED],
        FlowState.POST_EXPLOIT: [FlowState.EXPLOITING, FlowState.REPORTING, FlowState.FAILED, FlowState.PAUSED],
        FlowState.REPORTING: [FlowState.COMPLETED, FlowState.FAILED],
        FlowState.PAUSED: [FlowState.RECON, FlowState.SCANNING, FlowState.EXPLOITING, FlowState.POST_EXPLOIT, FlowState.FAILED],
        FlowState.FAILED: [FlowState.INIT],
        FlowState.COMPLETED: []
    }
    
    def __init__(self):
        self._context: Optional[FlowContext] = None
        self._transition_history: List[StateTransition] = []
        self._state_handlers: Dict[FlowState, Callable] = {}
        self._on_transition_callbacks: List[Callable] = []
    
    def initialize(self, target: str, scope: List[str] = None) -> FlowContext:
        """
        初始化流程
        
        Args:
            target: 目标地址
            scope: 测试范围
        
        Returns:
            流程上下文
        """
        self._context = FlowContext(
            target=target,
            scope=scope or [],
            current_state=FlowState.INIT
        )
        self._transition_history = []
        return self._context
    
    def get_current_state(self) -> Optional[FlowState]:
        """获取当前状态"""
        return self._context.current_state if self._context else None
    
    def can_transition_to(self, target_state: FlowState) -> bool:
        """检查是否可以转换到目标状态"""
        current = self.get_current_state()
        if current is None:
            return False
        return target_state in self.ALLOWED_TRANSITIONS.get(current, [])
    
    def transition(
        self,
        target_state: FlowState,
        transition_type: TransitionType = TransitionType.SUCCESS,
        reason: str = "",
        data: Dict[str, Any] = None
    ) -> bool:
        """
        执行状态转换
        
        Args:
            target_state: 目标状态
            transition_type: 转换类型
            reason: 转换原因
            data: 附加数据
        
        Returns:
            转换是否成功
        """
        if not self.can_transition_to(target_state):
            return False
        
        current_state = self._context.current_state
        transition = StateTransition(
            from_state=current_state,
            to_state=target_state,
            transition_type=transition_type,
            timestamp=datetime.now(),
            reason=reason,
            data=data or {}
        )
        
        self._transition_history.append(transition)
        self._context.current_state = target_state
        
        # 触发回调
        for callback in self._on_transition_callbacks:
            callback(transition)
        
        return True
    
    def register_state_handler(self, state: FlowState, handler: Callable) -> None:
        """注册状态处理器"""
        self._state_handlers[state] = handler
    
    def on_transition(self, callback: Callable) -> None:
        """注册状态转换回调"""
        self._on_transition_callbacks.append(callback)
    
    async def execute_state(self) -> Any:
        """执行当前状态的处理器"""
        current_state = self.get_current_state()
        if current_state and current_state in self._state_handlers:
            handler = self._state_handlers[current_state]
            if asyncio.iscoroutinefunction(handler):
                return await handler(self._context)
            return handler(self._context)
        return None
    
    def add_finding(self, finding: Dict[str, Any]) -> None:
        """添加发现"""
        if self._context:
            self._context.findings.append(finding)
    
    def add_artifact(self, key: str, value: Any) -> None:
        """添加工件"""
        if self._context:
            self._context.artifacts[key] = value
    
    def get_findings(self) -> List[Dict[str, Any]]:
        """获取所有发现"""
        return self._context.findings if self._context else []
    
    def get_transition_history(self) -> List[StateTransition]:
        """获取状态转换历史"""
        return self._transition_history.copy()
    
    def pause(self, reason: str = "") -> bool:
        """暂停流程"""
        return self.transition(
            FlowState.PAUSED,
            TransitionType.MANUAL,
            reason
        )
    
    def resume(self) -> bool:
        """恢复流程"""
        if not self._transition_history:
            return False
        last_transition = self._transition_history[-1]
        if last_transition.to_state == FlowState.PAUSED:
            return self.transition(
                last_transition.from_state,
                TransitionType.MANUAL,
                "Resuming from pause"
            )
        return False
    
    def fail(self, reason: str = "") -> bool:
        """标记流程失败"""
        return self.transition(
            FlowState.FAILED,
            TransitionType.FAILURE,
            reason
        )
    
    def complete(self) -> bool:
        """完成流程"""
        return self.transition(
            FlowState.COMPLETED,
            TransitionType.SUCCESS,
            "Flow completed successfully"
        )
    
    def get_context_summary(self) -> Dict[str, Any]:
        """获取上下文摘要"""
        if not self._context:
            return {}
        
        return {
            "target": self._context.target,
            "scope": self._context.scope,
            "current_state": self._context.current_state.value,
            "findings_count": len(self._context.findings),
            "artifacts_keys": list(self._context.artifacts.keys()),
            "transitions_count": len(self._transition_history)
        }