"""
CVE Fetcher - CVE漏洞信息获取
从NVD等数据源获取CVE信息
"""
import asyncio
import re
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from datetime import datetime
from dateutil import parser as date_parser

import aiohttp
from loguru import logger


@dataclass
class CVEInfo:
    """CVE信息结构"""
    cve_id: str
    description: str
    cvss_score: float = 0.0
    severity: str = "UNKNOWN"
    published_date: datetime = field(default_factory=datetime.now)
    modified_date: datetime = field(default_factory=datetime.now)
    references: List[str] = field(default_factory=list)
    affected_products: List[str] = field(default_factory=list)
    cwe_ids: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cve_id": self.cve_id,
            "description": self.description,
            "cvss_score": self.cvss_score,
            "severity": self.severity,
            "published_date": self.published_date.isoformat(),
            "modified_date": self.modified_date.isoformat(),
            "references": self.references,
            "affected_products": self.affected_products,
            "cwe_ids": self.cwe_ids
        }


class CVEFetcher:
    """
    CVE信息获取器

    支持从多个数据源获取CVE信息：
    - NVD (National Vulnerability Database)
    - Exploit-DB (通过pyxploitdb)
    - 本地缓存
    """

    NVD_API_BASE = "https://services.nvd.nist.gov/rest/json/cves/2.0"

    def __init__(self, api_key: Optional[str] = None, cache_enabled: bool = True):
        self.api_key = api_key
        self.cache_enabled = cache_enabled
        self._cache: Dict[str, List[CVEInfo]] = {}  # 缓存统一为列表
        self._single_cache: Dict[str, CVEInfo] = {}  # 精确ID缓存
        self._rate_limit_delay = 0.6 if api_key else 6.0
        self._lock = asyncio.Lock()
        self._last_request_time = 0.0

        # 尝试导入 exploit-db 支持
        self._exploitdb_available = False
        try:
            import pyxploitdb
            self._exploitdb = pyxploitdb
            self._exploitdb_available = True
        except ImportError:
            logger.debug("pyxploitdb not installed, exploit search disabled")

    async def _rate_limit(self):
        """线程安全的速率限制"""
        async with self._lock:
            now = asyncio.get_event_loop().time()
            elapsed = now - self._last_request_time
            if elapsed < self._rate_limit_delay:
                await asyncio.sleep(self._rate_limit_delay - elapsed)
            self._last_request_time = asyncio.get_event_loop().time()

    async def _request_with_retry(self, url: str, params: Dict, headers: Dict, retries: int = 3) -> Optional[Dict]:
        """带重试的HTTP请求"""
        for attempt in range(retries):
            try:
                await self._rate_limit()
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        url,
                        params=params,
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=30)
                    ) as response:
                        if response.status == 200:
                            return await response.json()
                        elif response.status == 403:
                            logger.warning("NVD API rate limit exceeded, waiting...")
                            await asyncio.sleep(30)
                        else:
                            logger.warning(f"NVD API returned {response.status}")
            except Exception as e:
                logger.warning(f"NVD request attempt {attempt+1} failed: {e}")
                await asyncio.sleep(2 ** attempt)
        return None

    def _parse_nvd_cve_item(self, cve_item: Dict) -> Optional[CVEInfo]:
        """解析单个CVE条目"""
        try:
            cve_id = cve_item.get("id", "")
            descriptions = cve_item.get("descriptions", [])
            description = ""
            for desc in descriptions:
                if desc.get("lang") == "en":
                    description = desc.get("value", "")
                    break

            # 解析CVSS评分
            metrics = cve_item.get("metrics", {})
            cvss_data = (
                metrics.get("cvssMetricV31", []) or
                metrics.get("cvssMetricV30", []) or
                metrics.get("cvssMetricV2", [])
            )
            cvss_score = 0.0
            severity = "UNKNOWN"
            if cvss_data:
                cvss = cvss_data[0].get("cvssData", {})
                cvss_score = cvss.get("baseScore", 0.0)
                severity = cvss.get("baseSeverity", "UNKNOWN")

            # 提取受影响产品CPE
            products = []
            for config in cve_item.get("configurations", []):
                for node in config.get("nodes", []):
                    for match in node.get("cpeMatch", []):
                        cpe = match.get("criteria", "")
                        if cpe:
                            products.append(cpe)

            # 解析日期
            published = cve_item.get("published", "")
            modified = cve_item.get("lastModified", "")
            try:
                pub_date = date_parser.isoparse(published) if published else datetime.now()
                mod_date = date_parser.isoparse(modified) if modified else datetime.now()
            except Exception:
                pub_date = datetime.now()
                mod_date = datetime.now()

            # 提取CWE IDs
            cwe_ids = []
            for weakness in cve_item.get("weaknesses", []):
                for desc in weakness.get("description", []):
                    if desc.get("lang") == "en":
                        cwe_ids.append(desc.get("value", ""))

            return CVEInfo(
                cve_id=cve_id,
                description=description[:1000],
                cvss_score=cvss_score,
                severity=severity,
                published_date=pub_date,
                modified_date=mod_date,
                affected_products=list(set(products))[:20],
                cwe_ids=cwe_ids
            )
        except Exception as e:
            logger.debug(f"Failed to parse CVE item: {e}")
            return None

    async def fetch(self, cve_id: str) -> Optional[CVEInfo]:
        """
        获取单个CVE信息（精确匹配）

        Args:
            cve_id: CVE编号 (如 CVE-2024-1234)

        Returns:
            CVEInfo对象或None
        """
        if self.cache_enabled and cve_id in self._single_cache:
            return self._single_cache[cve_id]

        # 使用cveId参数精确查询
        params = {"cveId": cve_id}
        headers = {}
        if self.api_key:
            headers["apiKey"] = self.api_key

        data = await self._request_with_retry(self.NVD_API_BASE, params, headers)
        if not data:
            return None

        vulns = data.get("vulnerabilities", [])
        if not vulns:
            return None

        cve_info = self._parse_nvd_cve_item(vulns[0].get("cve", {}))
        if cve_info and self.cache_enabled:
            self._single_cache[cve_id] = cve_info
        return cve_info

    async def search_by_keyword(self, keyword: str, limit: int = 10) -> List[CVEInfo]:
        """
        根据关键词搜索CVE

        Args:
            keyword: 搜索关键词
            limit: 返回数量限制

        Returns:
            CVE信息列表
        """
        cache_key = f"kw:{keyword}"
        if self.cache_enabled and cache_key in self._cache:
            return self._cache[cache_key][:limit]

        # 使用keywordSearch参数进行全文搜索
        params = {"keywordSearch": keyword, "resultsPerPage": min(limit, 50)}
        headers = {}
        if self.api_key:
            headers["apiKey"] = self.api_key

        data = await self._request_with_retry(self.NVD_API_BASE, params, headers)
        if not data:
            return []

        results = []
        for vuln in data.get("vulnerabilities", []):
            cve_info = self._parse_nvd_cve_item(vuln.get("cve", {}))
            if cve_info:
                results.append(cve_info)
                if len(results) >= limit:
                    break

        if self.cache_enabled:
            self._cache[cache_key] = results
        return results

    async def search_by_product(self, product: str, version: Optional[str] = None) -> List[CVEInfo]:
        """
        根据产品搜索相关CVE

        Args:
            product: 产品名称 (如 'apache', 'nginx')
            version: 产品版本（可选）

        Returns:
            相关CVE列表
        """
        cache_key = f"prod:{product}:{version or ''}"
        if self.cache_enabled and cache_key in self._cache:
            return self._cache[cache_key]

        # 构造CPE格式搜索词
        cpe_keyword = f"cpe:2.3:*:*:{product}"
        if version:
            cpe_keyword += f":{version}"
        cpe_keyword += ":*"

        # 先尝试用CPE搜索
        results = await self.search_by_keyword(cpe_keyword, limit=20)

        # 若结果不足，再用产品名直接搜索
        if len(results) < 5:
            extra = await self.search_by_keyword(product, limit=20)
            # 合并去重
            seen = {c.cve_id for c in results}
            for c in extra:
                if c.cve_id not in seen:
                    results.append(c)
                    seen.add(c.cve_id)

        # 根据版本过滤CPE
        if version:
            filtered = []
            for cve in results:
                for cpe in cve.affected_products:
                    if version in cpe:
                        filtered.append(cve)
                        break
            if filtered:
                results = filtered

        if self.cache_enabled:
            self._cache[cache_key] = results
        return results[:20]

    async def get_exploits(self, cve_id: str) -> List[Dict[str, Any]]:
        """
        获取CVE相关的公开漏洞利用

        Args:
            cve_id: CVE编号

        Returns:
            漏洞利用信息列表
        """
        if not self._exploitdb_available:
            logger.warning("pyxploitdb not available")
            return []

        try:
            # 在线程池中执行同步库调用，避免阻塞事件循环
            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(
                None, self._exploitdb.PyxploitDb().searchCVE, cve_id
            )

            exploits = []
            for result in results:
                exploits.append({
                    "edb_id": result.id,
                    "description": result.description,
                    "type": result.type,
                    "platform": result.platform,
                    "date_published": result.date_published,
                    "author": result.author,
                    "verified": result.verified,
                    "port": result.port,
                    "link": result.link
                })

            logger.info(f"Found {len(exploits)} exploits for {cve_id}")
            return exploits

        except Exception as e:
            logger.warning(f"Failed to fetch exploits for {cve_id}: {e}")
            return []

    def clear_cache(self) -> None:
        """清空缓存"""
        self._cache.clear()
        self._single_cache.clear()