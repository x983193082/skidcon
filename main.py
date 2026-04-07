"""PentestAI - 自动化渗透测试系统入口"""

import argparse
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from crew.pentest_crew import PentestCrew, run_pentest
from utils.config import (
    get_config, 
    get_logs_dir,
    get_results_dir,
    generate_session_id,
    get_log_file_path,
    get_result_file_path,
    save_log,
    save_result
)

__version__ = "1.0.0"
__author__ = "PentestAI"


def main():
    """主入口"""
    parser = argparse.ArgumentParser(
        description="PentestAI - 基于CrewAI的自动化渗透测试系统"
    )
    
    parser.add_argument(
        "--target", "-t",
        required=True,
        help="目标主机 (IP或域名)"
    )
    
    parser.add_argument(
        "--model", "-m",
        default="z-ai/glm-5",
        help="使用的LLM模型 (默认: z-ai/glm-5)"
    )
    
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="详细输出"
    )
    
    parser.add_argument(
        "--interactive", "-i",
        action="store_true",
        help="交互模式"
    )
    
    parser.add_argument(
        "--session", "-s",
        default=None,
        help="指定会话ID (用于恢复会话)"
    )
    
    args = parser.parse_args()
    
    config = get_config()
    api_key = config.openrouter_api_key
    
    if not api_key:
        print("错误: 请设置OPENROUTER_API_KEY环境变量")
        print("export OPENROUTER_API_KEY=your_api_key")
        sys.exit(1)
    
    session_id = args.session or generate_session_id()
    log_file = get_log_file_path(session_id)
    result_file = get_result_file_path(session_id)
    
    print(f"[*] 启动PentestAI自动化渗透测试")
    print(f"[*] 目标: {args.target}")
    print(f"[*] 模型: {args.model}")
    print(f"[*] 会话ID: {session_id}")
    print(f"[*] 日志文件: {log_file}")
    print(f"[*] 结果文件: {result_file}")
    print("-" * 50)
    
    save_log(session_id, f"启动渗透测试 - 目标: {args.target}")
    save_log(session_id, f"使用模型: {args.model}")
    
    try:
        result = run_pentest(target=args.target, model=args.model)
        
        result_data = {
            "session_id": session_id,
            "target": args.target,
            "model": args.model,
            "timestamp": datetime.now().isoformat(),
            "result": str(result),
            "status": "completed"
        }
        
        save_result(session_id, result_data)
        
        save_log(session_id, "渗透测试完成")
        
        print("-" * 50)
        print(f"[*] 渗透测试完成")
        print(f"[*] 会话ID: {session_id}")
        print(f"[*] 结果已保存至: {result_file}")
        
    except Exception as e:
        error_msg = f"错误: {str(e)}"
        print(error_msg)
        save_log(session_id, error_msg, "ERROR")
        
        result_data = {
            "session_id": session_id,
            "target": args.target,
            "model": args.model,
            "timestamp": datetime.now().isoformat(),
            "error": str(e),
            "status": "failed"
        }
        save_result(session_id, result_data)
        
        sys.exit(1)


if __name__ == "__main__":
    main()
