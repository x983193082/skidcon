"""
Pentest Crew - 启动验证脚本
验证所有依赖和配置是否正确
"""
import sys
import os
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

def check_imports():
    """检查所有关键依赖是否已安装"""
    print("=" * 60)
    print("检查依赖包...")
    print("=" * 60)
    
    required_packages = {
        "crewai": "CrewAI 框架",
        "crewai_tools": "CrewAI 工具",
        "fastapi": "FastAPI Web框架",
        "uvicorn": "Uvicorn ASGI服务器",
        "pydantic": "Pydantic 数据验证",
        "pydantic_settings": "Pydantic 设置管理",
        "litellm": "LiteLLM 多模型支持",
        "langchain": "LangChain 框架",
        "langchain_openai": "LangChain OpenAI集成",
        "chromadb": "Chroma 向量数据库",
        "redis": "Redis 客户端",
        "sqlalchemy": "SQLAlchemy ORM",
        "loguru": "Loguru 日志",
        "aiohttp": "AioHTTP 异步HTTP",
        "jinja2": "Jinja2 模板引擎",
        "sentence_transformers": "Sentence Transformers 向量嵌入",
    }
    
    missing = []
    for package, description in required_packages.items():
        try:
            __import__(package)
            print(f"  ✅ {description} ({package})")
        except ImportError:
            print(f"  ❌ {description} ({package}) - 未安装")
            missing.append(package)
    
    if missing:
        print(f"\n⚠️  缺少 {len(missing)} 个依赖包，请运行: pip install -r requirements.txt")
        return False
    else:
        print("\n✅ 所有依赖包已安装")
        return True


def check_env():
    """检查环境变量配置"""
    print("\n" + "=" * 60)
    print("检查环境变量...")
    print("=" * 60)
    
    from dotenv import load_dotenv
    load_dotenv()
    
    from src.core.settings import get_settings
    settings = get_settings()
    
    checks = {
        "LLM Provider": settings.llm_provider,
        "Redis URL": settings.redis_url,
        "Database URL": settings.database_url,
        "Vector DB Type": settings.vector_db_type,
    }
    
    for name, value in checks.items():
        print(f"  ✅ {name}: {value}")
    
    # 检查 API Key
    if settings.llm_provider == "openrouter":
        if settings.openrouter_api_key:
            print(f"  ✅ OpenRouter API Key: 已配置")
        else:
            print(f"  ⚠️  OpenRouter API Key: 未配置 (设置 OPENROUTER_API_KEY 环境变量)")
    elif settings.llm_provider == "openai":
        if settings.openai_api_key:
            print(f"  ✅ OpenAI API Key: 已配置")
        else:
            print(f"  ⚠️  OpenAI API Key: 未配置 (设置 OPENAI_API_KEY 环境变量)")
    
    return True


def check_tools():
    """检查安全工具是否可用"""
    print("\n" + "=" * 60)
    print("检查安全工具...")
    print("=" * 60)
    
    import shutil
    
    tools = {
        "nmap": "网络扫描工具",
        "sqlmap": "SQL注入检测工具",
    }
    
    for tool, description in tools.items():
        if shutil.which(tool):
            print(f"  ✅ {description} ({tool})")
        else:
            print(f"  ⚠️  {description} ({tool}) - 未找到，请安装")
    
    return True


def check_database():
    """检查数据库连接"""
    print("\n" + "=" * 60)
    print("检查数据库...")
    print("=" * 60)
    
    try:
        from src.database import Database
        db = Database.get_instance()
        db.create_tables()
        print("  ✅ SQLite 数据库连接成功")
        return True
    except Exception as e:
        print(f"  ❌ 数据库连接失败: {e}")
        return False


def check_redis():
    """检查 Redis 连接"""
    print("\n" + "=" * 60)
    print("检查 Redis...")
    print("=" * 60)
    
    try:
        from src.core.queue import get_task_queue
        queue = get_task_queue()
        queue._ensure_connection()
        queue.client.ping()
        print("  ✅ Redis 连接成功")
        return True
    except Exception as e:
        print(f"  ⚠️  Redis 连接失败: {e}")
        print("  💡 如果不需要任务队列功能，可以忽略此警告")
        return False


def main():
    """主验证流程"""
    print("\n" + "🔍" * 30)
    print("Pentest Crew - 启动验证")
    print("🔍" * 30 + "\n")
    
    results = []
    
    results.append(("依赖包", check_imports()))
    results.append(("环境变量", check_env()))
    results.append(("安全工具", check_tools()))
    results.append(("数据库", check_database()))
    results.append(("Redis", check_redis()))
    
    print("\n" + "=" * 60)
    print("验证结果汇总")
    print("=" * 60)
    
    all_passed = True
    for name, passed in results:
        status = "✅ 通过" if passed else "❌ 失败"
        print(f"  {status} - {name}")
        if not passed:
            all_passed = False
    
    print("\n" + "=" * 60)
    if all_passed:
        print("✅ 所有检查通过！项目已准备好运行。")
        print("\n启动命令:")
        print("  python -m src.api.main")
        print("  或")
        print("  uvicorn src.api.main:app --host 0.0.0.0 --port 8000")
    else:
        print("⚠️  部分检查未通过，请根据上述提示进行修复。")
    print("=" * 60 + "\n")
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
