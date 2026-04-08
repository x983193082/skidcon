"""
测试Agent接口
"""
import pytest
from src.core.agent_interface import BaseAgent, AgentRole, AgentState


class TestAgentInterface:
    """测试Agent接口"""
    
    def test_agent_role_enum(self):
        """测试Agent角色枚举"""
        assert AgentRole.RECON.value == "recon"
        assert AgentRole.EXPLOIT.value == "exploit"
        assert AgentRole.PRIVILEGE.value == "privilege"
        assert AgentRole.REPORT.value == "report"
    
    def test_agent_state_enum(self):
        """测试Agent状态枚举"""
        assert AgentState.IDLE.value == "idle"
        assert AgentState.RUNNING.value == "running"
        assert AgentState.COMPLETED.value == "completed"
        assert AgentState.FAILED.value == "failed"
    
    def test_base_agent_initialization(self):
        """测试BaseAgent初始化"""
        class MockAgent(BaseAgent):
            async def execute(self, target: str, context: dict = None):
                return {"success": True}
            
            def validate_result(self, result: dict) -> bool:
                return True
            
            def report(self) -> dict:
                return {}
        
        agent = MockAgent(
            name="TestAgent",
            role=AgentRole.RECON,
            description="Test agent"
        )
        
        assert agent.name == "TestAgent"
        assert agent.role == AgentRole.RECON
        assert agent.state == AgentState.IDLE
    
    def test_agent_state_update(self):
        """测试Agent状态更新"""
        class MockAgent(BaseAgent):
            async def execute(self, target: str, context: dict = None):
                return {"success": True}
            
            def validate_result(self, result: dict) -> bool:
                return True
            
            def report(self) -> dict:
                return {}
        
        agent = MockAgent(
            name="TestAgent",
            role=AgentRole.RECON,
            description="Test agent"
        )
        
        agent.update_state(AgentState.RUNNING)
        assert agent.state == AgentState.RUNNING