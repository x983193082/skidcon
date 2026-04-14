"""
Base Repository - 基础 Repository 类
提供通用的增删改查方法
"""
from typing import TypeVar, Generic, Type, Optional, List, Any, Dict
from sqlalchemy.orm import Session
from ..db_models import Base

ModelType = TypeVar("ModelType", bound=Base)

class BaseRepository(Generic[ModelType]):
    """基础 Repository（同步版本）"""

    def __init__(self, model: Type[ModelType], session: Session):
        self.model = model
        self.session = session

    def create(self, **kwargs) -> ModelType:
        """
        创建新记录，仅 flush 不提交事务
        注意：事务提交应由调用方通过 session.commit() 完成
        """
        obj = self.model(**kwargs)
        self.session.add(obj)
        self.session.flush()
        return obj

    def get(self, id: str) -> Optional[ModelType]:
        """通过主键 ID 获取（主键列名假定为 'id'）"""
        return self.session.get(self.model, id)

    def get_by_field(self, field: str, value: Any) -> Optional[ModelType]:
        """通过指定字段获取单条记录"""
        return self.session.query(self.model).filter(
            getattr(self.model, field) == value
        ).first()

    def find_by(self, **filters: Any) -> List[ModelType]:
        """通过多个字段等值过滤查询（AND 条件）"""
        query = self.session.query(self.model)
        for field, value in filters.items():
            query = query.filter(getattr(self.model, field) == value)
        return query.all()

    def all(self, limit: Optional[int] = None, offset: int = 0) -> List[ModelType]:
        """
        获取所有记录，支持分页
        - limit: 返回记录数上限，None 表示不限制
        - offset: 偏移量
        """
        query = self.session.query(self.model).offset(offset)
        if limit is not None:
            query = query.limit(limit)
        return query.all()

    def update(self, id: str, **kwargs) -> Optional[ModelType]:
        """更新记录（按主键），传入的字段名必须存在于模型中"""
        obj = self.session.get(self.model, id)
        if obj:
            for key, value in kwargs.items():
                setattr(obj, key, value)
            self.session.flush()
        return obj

    def delete(self, id: str) -> bool:
        """删除记录（按主键）"""
        obj = self.session.get(self.model, id)
        if obj:
            self.session.delete(obj)
            self.session.flush()
            return True
        return False

    def count(self) -> int:
        """统计总记录数"""
        return self.session.query(self.model).count()

    def exists(self, field: str, value: Any) -> bool:
        """检查指定字段值是否存在"""
        return self.session.query(self.model).filter(
            getattr(self.model, field) == value
        ).first() is not None