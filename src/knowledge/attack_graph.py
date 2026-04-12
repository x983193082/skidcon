"""
Attack Graph - 攻击链图数据库
用于存储和查询攻击路径、漏洞依赖关系
支持 Neo4j 后端（主）+ 内存 fallback
"""

from typing import Dict, Any, List, Optional, Set
from dataclasses import dataclass, field
from enum import Enum
from collections import deque
import copy

from loguru import logger


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
            "properties": self.properties,
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
            "properties": self.properties,
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
            "total_risk": self.total_risk,
        }


class AttackGraph:
    """
    攻击图数据库

    支持：
    - Neo4j 后端（默认，持久化）
    - 内存模式（fallback）
    - 图遍历和路径搜索
    - 攻击面分析
    - 风险评分
    """

    EDGE_TYPE_MAPPING = {
        EdgeType.EXPLOITS: "EXPLOITS",
        EdgeType.REQUIRES: "REQUIRES",
        EdgeType.LEADS_TO: "LEADS_TO",
        EdgeType.DEPENDS_ON: "DEPENDS_ON",
        EdgeType.GRANTS: "GRANTS",
    }

    def __init__(
        self,
        name: str = "attack_graph",
        neo4j_uri: str = "bolt://localhost:7687",
        neo4j_user: str = "neo4j",
        neo4j_password: str = "pentest123",
        use_neo4j: bool = True,
    ):
        self.name = name
        self.neo4j_uri = neo4j_uri
        self.neo4j_user = neo4j_user
        self.neo4j_password = neo4j_password
        self.use_neo4j = use_neo4j
        self._driver = None

        self._nodes: Dict[str, AttackNode] = {}
        self._edges: Dict[str, AttackEdge] = {}
        self._adjacency: Dict[str, Set[str]] = {}

    def initialize(self) -> bool:
        """初始化 Neo4j 连接（同步方法）"""
        if not self.use_neo4j:
            logger.info("Using in-memory graph mode")
            return True

        try:
            from neo4j import GraphDatabase

            self._driver = GraphDatabase.driver(
                self.neo4j_uri, auth=(self.neo4j_user, self.neo4j_password)
            )

            with self._driver.session() as session:
                result = session.run("RETURN 1")
                result.single()

            self._create_indexes()
            logger.info(f"Neo4j connected: {self.name}")
            return True

        except Exception as e:
            logger.warning(f"Neo4j connection failed, using in-memory mode: {e}")
            self.use_neo4j = False
            return True

    def _create_indexes(self):
        """创建索引（兼容 Neo4j 4.x+）"""
        with self._driver.session() as session:
            try:
                session.run(
                    "CREATE CONSTRAINT IF NOT EXISTS FOR (n:AttackNode) REQUIRE n.id IS UNIQUE"
                )
            except Exception:
                try:
                    session.run("CREATE INDEX ON :AttackNode(id)")
                except Exception:
                    pass

    def close(self):
        """关闭连接"""
        if self._driver:
            self._driver.close()
            self._driver = None

    def add_node(self, node: AttackNode) -> bool:
        """添加节点"""
        if node.id in self._nodes:
            return False

        self._nodes[node.id] = node
        self._adjacency[node.id] = set()

        if self.use_neo4j and self._driver:
            self._save_node_to_neo4j(node)

        return True

    def _save_node_to_neo4j(self, node: AttackNode):
        """保存节点到 Neo4j"""
        try:
            with self._driver.session() as session:
                session.run(
                    """
                    MERGE (n:AttackNode {id: $id})
                    SET n.node_type = $node_type,
                        n.name = $name,
                        n += $properties
                    """,
                    id=node.id,
                    node_type=node.node_type.value,
                    name=node.name,
                    properties=node.properties,
                )
        except Exception as e:
            logger.warning(f"Failed to save node to Neo4j: {e}")

    def get_node(self, node_id: str) -> Optional[AttackNode]:
        """获取节点"""
        return self._nodes.get(node_id)

    def get_neighbors(self, node_id: str) -> List[AttackNode]:
        """获取相邻节点"""
        if node_id not in self._adjacency:
            return []
        return [
            self._nodes[nid] for nid in self._adjacency[node_id] if nid in self._nodes
        ]

    def add_edge(self, edge: AttackEdge) -> bool:
        """添加边"""
        if edge.id in self._edges:
            return False
        if edge.source_id not in self._nodes or edge.target_id not in self._nodes:
            return False

        self._edges[edge.id] = edge
        self._adjacency[edge.source_id].add(edge.target_id)

        if self.use_neo4j and self._driver:
            self._save_edge_to_neo4j(edge)

        return True

    def _save_edge_to_neo4j(self, edge: AttackEdge):
        """保存边到 Neo4j"""
        try:
            rel_type = self.EDGE_TYPE_MAPPING.get(edge.edge_type, "ATTACK")
            query = f"""
                MATCH (s:AttackNode {{id: $source_id}})
                MATCH (t:AttackNode {{id: $target_id}})
                MERGE (s)-[r:{rel_type}]->(t)
                SET r.id = $id,
                    r += $properties
            """
            with self._driver.session() as session:
                session.run(
                    query,
                    source_id=edge.source_id,
                    target_id=edge.target_id,
                    id=edge.id,
                    properties=edge.properties,
                )
        except Exception as e:
            logger.warning(f"Failed to save edge to Neo4j: {e}")

    def find_paths(
        self, start_id: str, end_id: str, max_depth: int = 10
    ) -> List[AttackPath]:
        """BFS 查找所有路径"""
        paths = []
        queue = deque([(start_id, [start_id])])

        while queue:
            current, path = queue.popleft()

            if len(path) > max_depth:
                continue

            if current == end_id:
                paths.append(self._build_attack_path(path))
                continue

            path_set = set(path)
            for neighbor in self._adjacency.get(current, []):
                if neighbor not in path_set:
                    queue.append((neighbor, path + [neighbor]))

        return paths

    def find_shortest_path(self, start_id: str, end_id: str) -> Optional[AttackPath]:
        """BFS 查找最短路径"""
        queue = deque([(start_id, [start_id])])
        visited = {start_id}

        while queue:
            current, path = queue.popleft()

            if current == end_id:
                return self._build_attack_path(path)

            for neighbor in self._adjacency.get(current, []):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, path + [neighbor]))

        return None

    def _build_attack_path(self, node_ids: List[str]) -> AttackPath:
        """从节点ID列表构建 AttackPath"""
        nodes = [self._nodes[nid] for nid in node_ids if nid in self._nodes]
        edges = []

        for i in range(len(node_ids) - 1):
            src = node_ids[i]
            tgt = node_ids[i + 1]
            for edge in self._edges.values():
                if edge.source_id == src and edge.target_id == tgt:
                    edges.append(edge)
                    break

        total_risk = self.calculate_risk(AttackPath(nodes=nodes, edges=edges))

        return AttackPath(nodes=nodes, edges=edges, total_risk=total_risk)

    def get_attack_surface(self, host_id: str, max_hops: int = 2) -> List[AttackNode]:
        """获取主机的攻击面"""
        attack_surface = []
        visited = {host_id}
        queue = deque([(host_id, 0)])

        while queue:
            node_id, distance = queue.popleft()

            if distance >= max_hops:
                continue

            for neighbor_id in self._adjacency.get(node_id, []):
                if neighbor_id not in visited:
                    visited.add(neighbor_id)
                    neighbor = self._nodes.get(neighbor_id)
                    if neighbor:
                        neighbor_copy = copy.copy(neighbor)
                        neighbor_copy.properties = neighbor.properties.copy()
                        neighbor_copy.properties["attack_distance"] = distance + 1
                        neighbor_copy.properties["risk_score"] = (
                            self._calculate_node_risk(neighbor)
                        )
                        attack_surface.append(neighbor_copy)
                    queue.append((neighbor_id, distance + 1))

        return attack_surface

    def _calculate_node_risk(self, node: AttackNode) -> float:
        """计算单个节点的风险值"""
        base_scores = {
            NodeType.VULNERABILITY: 8.0,
            NodeType.EXPLOIT: 9.0,
            NodeType.CREDENTIAL: 7.0,
            NodeType.PRIVILEGE: 6.0,
            NodeType.SERVICE: 3.0,
            NodeType.HOST: 2.0,
            NodeType.NETWORK: 1.0,
        }

        base = base_scores.get(node.node_type, 1.0)

        cvss = node.properties.get("cvss_score", 0.0)
        if cvss >= 9.0:
            base += 2.0
        elif cvss >= 7.0:
            base += 1.0
        elif cvss >= 4.0:
            base += 0.5

        return base

    def calculate_risk(self, path: AttackPath) -> float:
        """计算攻击路径的风险评分"""
        if not path.nodes:
            return 0.0

        node_risk_sum = sum(self._calculate_node_risk(n) for n in path.nodes)

        distance_penalty = 1.0 / len(path.nodes)

        exploit_count = sum(1 for e in path.edges if e.edge_type == EdgeType.EXPLOITS)
        exploit_bonus = 1.0 + (exploit_count * 0.1)

        total_risk = node_risk_sum * distance_penalty * exploit_bonus

        return min(10.0, total_risk)

    def export_graph(self) -> Dict[str, Any]:
        """导出图数据"""
        return {
            "nodes": [n.to_dict() for n in self._nodes.values()],
            "edges": [e.to_dict() for e in self._edges.values()],
        }

    def import_graph(self, data: Dict[str, Any]) -> bool:
        """导入图数据"""
        try:
            for node_data in data.get("nodes", []):
                node = AttackNode(
                    id=node_data["id"],
                    node_type=NodeType(node_data["type"]),
                    name=node_data["name"],
                    properties=node_data.get("properties", {}),
                )
                self.add_node(node)

            for edge_data in data.get("edges", []):
                edge = AttackEdge(
                    id=edge_data["id"],
                    source_id=edge_data["source"],
                    target_id=edge_data["target"],
                    edge_type=EdgeType(edge_data["type"]),
                    properties=edge_data.get("properties", {}),
                )
                self.add_edge(edge)

            return True
        except Exception as e:
            logger.error(f"Failed to import graph: {e}")
            return False

    def clear(self) -> None:
        """清空图"""
        self._nodes.clear()
        self._edges.clear()
        self._adjacency.clear()

        if self.use_neo4j and self._driver:
            try:
                with self._driver.session() as session:
                    session.run("MATCH (n:AttackNode) DETACH DELETE n")
            except Exception as e:
                logger.warning(f"Failed to clear Neo4j: {e}")

    def __len__(self) -> int:
        """返回节点数量"""
        return len(self._nodes)
