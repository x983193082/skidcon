"""
SkidCon 扫描结果缓存模块
缓存扫描结果以避免重复扫描同一目标
"""

import hashlib
import json
import time
from pathlib import Path
from typing import Dict, Optional
from config import DATA_DIR


class ScanCache:
    """扫描结果缓存"""
    
    def __init__(self, cache_dir: str = None):
        if cache_dir:
            self.cache_dir = Path(cache_dir)
        else:
            self.cache_dir = DATA_DIR / "cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
    
    def _get_cache_key(self, target: str, tool: str) -> str:
        """生成缓存键"""
        raw = f"{target}:{tool}"
        return hashlib.md5(raw.encode()).hexdigest()
    
    def _get_cache_file(self, target: str, tool: str) -> Path:
        """获取缓存文件路径"""
        key = self._get_cache_key(target, tool)
        return self.cache_dir / f"{key}.json"
    
    def get(self, target: str, tool: str, ttl: int = 86400) -> Optional[Dict]:
        """
        获取缓存结果
        
        Args:
            target: 扫描目标
            tool: 工具名称
            ttl: 缓存有效期（秒），默认 24 小时
        
        Returns:
            缓存结果，如果不存在或已过期则返回 None
        """
        cache_file = self._get_cache_file(target, tool)
        
        if not cache_file.exists():
            return None
        
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # 检查是否过期
            if time.time() - data.get("timestamp", 0) > ttl:
                # 缓存已过期，删除文件
                cache_file.unlink(missing_ok=True)
                return None
            
            return data.get("result")
        
        except (json.JSONDecodeError, KeyError, IOError):
            # 缓存文件损坏，删除
            cache_file.unlink(missing_ok=True)
            return None
    
    def set(self, target: str, tool: str, result: Dict, ttl: int = 86400):
        """
        缓存结果
        
        Args:
            target: 扫描目标
            tool: 工具名称
            result: 扫描结果
            ttl: 缓存有效期（秒），默认 24 小时
        """
        cache_file = self._get_cache_file(target, tool)
        
        data = {
            "target": target,
            "tool": tool,
            "result": result,
            "timestamp": time.time(),
            "ttl": ttl
        }
        
        try:
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except IOError as e:
            print(f"缓存写入失败: {e}")
    
    def clear(self, target: str = None):
        """
        清除缓存
        
        Args:
            target: 如果指定，只清除该目标的缓存；否则清除所有缓存
        """
        if target:
            # 清除指定目标的所有缓存
            for cache_file in self.cache_dir.glob("*.json"):
                try:
                    with open(cache_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    if data.get("target") == target:
                        cache_file.unlink(missing_ok=True)
                except:
                    cache_file.unlink(missing_ok=True)
        else:
            # 清除所有缓存
            for cache_file in self.cache_dir.glob("*.json"):
                cache_file.unlink(missing_ok=True)
    
    def get_stats(self) -> Dict:
        """获取缓存统计信息"""
        total = 0
        total_size = 0
        targets = set()
        tools = set()
        
        for cache_file in self.cache_dir.glob("*.json"):
            try:
                total += 1
                total_size += cache_file.stat().st_size
                
                with open(cache_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                targets.add(data.get("target", ""))
                tools.add(data.get("tool", ""))
            except:
                pass
        
        return {
            "total_entries": total,
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / 1024 / 1024, 2),
            "unique_targets": len(targets),
            "unique_tools": len(tools),
            "cache_dir": str(self.cache_dir)
        }


# 单例实例
scan_cache = ScanCache()
