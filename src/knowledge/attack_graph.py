"""
Attack Graph - 攻击链图数据库
用于存储和查询攻击路径、漏洞依赖关系
"""
from typing import Dict, Any, List, Optional, Set
from dataclasses import dataclass, field
from enum import Enum


class NodeType(Enum):
    """攻击图节点类型"""
    HOST = "host"
    VULNERABILITY = "vulnerability"
    EXPLOIT = "exploit"
    PRIVILEGE = "privilege"
    CREDENTIAL = "credential"
    SERVICE = "service"
    NETWORK = "network"


class EdgeType(Enum):
    """攻击图边类型"""
    EXPLOITS = "exploits"
    REQUIRES = "requires"
    LEADS_TO = "leads_to"
    DEPENDS_ON = "depends_on"
    GRANTS = "grants"


@dataclass
class AttackNode:
    """攻击图节点"""
    id: str
    node_type: NodeType
    name: str
    properties: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.node_type.value,
            "name": self.name,
            "properties": self.properties
        }


@dataclass
class AttackEdge:
    """攻击图边"""
    id: str
    source_id: str
    target_id: str
    edge_type: EdgeType
    properties: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source_id,
            "target": self.target_id,
            "type": self.edge_type.value,
            "properties": self.properties
        }


@dataclass
class AttackPath:
    """攻击路径"""
    nodes: List[AttackNode]
    edges: List[AttackEdge]
    total_risk: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
            "total_risk": self.total_risk
        }


class AttackGraph:
    """
    攻击图数据库
    
    用于：
    - 存储攻击路径
    - 分析漏洞依赖关系
    - 规划攻击链
    - 记录渗透测试历史
    """
    
    def __init__(self, name: str = "attack_graph"):
        self.name = name
        self._nodes: Dict[str, AttackNode] = {}
        self._edges: Dict[str, AttackEdge] = {}
        self._adjacency: Dict[str, Set[str]] = {}  # 邻接表
    
    def add_node(self, node: AttackNode) -> bool:
        """添加节点"""
        if node.id in self._nodes:
            return False
        self._nodes[node.id] = node
        self._adjacency[node.id] = set()
        return True
    
    def add_edge(self, edge: AttackEdge) -> bool:
        """添加边"""
        if edge.id in self._edges:
            return False
        if edge.source_id not in self._nodes or edge.target_id not in self._nodes:
            return False
        
        self._edges[edge.id] = edge
        self._adjacency[edge.source_id].add(edge.target_id)
        return True
    
    def get_node(self, node_id: str) -> Optional[AttackNode]:
        """获取节点"""
        return self._nodes.get(node_id)
    
    def get_neighbors(self, node_id: str) -> List[AttackNode]:
        """获取相邻节点"""
        if node_id not in self._adjacency:
            return []
        return [self._nodes[nid] for nid in self._adjacency[node_id] if nid in self._nodes]
    
    def find_paths(
        self,
        start_id: str,
        end_id: str,
        max_depth: int = 10
    ) -> List[AttackPath]:
        """
        查找两个节点之间的所有路径
        
        Args:
            start_id: 起始节点ID
            end_id: 目标节点ID
            max_depth: 最大搜索深度
        
        Returns:
            攻击路径列表
        """
        # TODO: 实现BFS/DFS路径搜索
        raise NotImplementedError("Path finding algorithm pending")
    
    def find_shortest_path(
        self,
        start_id: str,
        end_id: str
    ) -> Optional[AttackPath]:
        """查找最短攻击路径"""
        # TODO: 实现Dijkstra或BFS最短路径
        raise NotImplementedError("Shortest path algorithm pending")
    
    def get_attack_surface(self, host_id: str) -> List[AttackNode]:
        """
        获取主机的攻击面
        
        Args:
            host_id: 主机节点ID
        
        Returns:
            可利用的节点列表
        """
        # TODO: 实现攻击面分析
        raise NotImplementedError("Attack surface analysis pending")
    
    def calculate_risk(self, path: AttackPath) -> float:
        """计算攻击路径的风险值"""
        # TODO: 实现风险计算
        raise NotImplementedError("Risk calculation pending")
    
    def export_graph(self) -> Dict[str, Any]:
        """导出图数据"""
        return {
            "nodes": [n.to_dict() for n in self._nodes.values()],
            "edges": [e.to_dict() for e in self._edges.values()]
        }
    
    def import_graph(self, data: Dict[str, Any]) -> bool:
        """导入图数据"""
        try:
            for node_data in data.get("nodes", []):
                node = AttackNode(
                    id=node_data["id"],
                    node_type=NodeType(node_data["type"]),
                    name=node_data["name"],
                    properties=node_data.get("properties", {})
                )
                self.add_node(node)
            
            for edge_data in data.get("edges", []):
                edge = AttackEdge(
                    id=edge_data["id"],
                    source_id=edge_data["source"],
                    target_id=edge_data["target"],
                    edge_type=EdgeType(edge_data["type"]),
                    properties=edge_data.get("properties", {})
                )
                self.add_edge(edge)
            
            return True
        except Exception:
            return False
    
    def clear(self) -> None:
        """清空图"""
        self._nodes.clear()
        self._edges.clear()
        self._adjacency.clear()
    
    def __len__(self) -> int:
        """返回节点数量"""
        return len(self._nodes)