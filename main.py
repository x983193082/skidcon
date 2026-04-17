"""Main entry point for SkidCon."""

import os
import threading
from colorama import Fore, Style, init
from core.agent_runner import agent_runner
from dotenv import load_dotenv
import uvicorn

# Initialize colorama
init(autoreset=True)
load_dotenv(".env")


def start_web_server():
    """在后台线程中启动Web服务器"""
    try:
        import sys
        import os
        # 确保可以导入web模块
        current_dir = os.path.dirname(os.path.abspath(__file__))
        if current_dir not in sys.path:
            sys.path.insert(0, current_dir)
        # 获取端口，默认为8000
        port = int(os.getenv('PORT', '8000'))
        
        # 配置日志，完全禁用警告
        import logging
        logging.getLogger("uvicorn").setLevel(logging.ERROR)
        logging.getLogger("uvicorn.access").setLevel(logging.ERROR)
        logging.getLogger("uvicorn.error").setLevel(logging.ERROR)
        
        uvicorn.run(
            "web.app:app",
            host="0.0.0.0",
            port=port,
            log_level="error",  # 只显示错误，不显示警告
            access_log=False,
            use_colors=False  # 禁用颜色输出，减少输出
        )
    except Exception as e:
        print(f"{Fore.RED}Web服务器启动失败: {e}{Style.RESET_ALL}")
        import traceback
        traceback.print_exc()


def main():
    """Main function to run the agent system."""
    print(f"{Fore.CYAN}{'='*60}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}SkidCon - Three-Level Agent System (CrewAI){Style.RESET_ALL}")
    print(f"{Fore.CYAN}{'='*60}{Style.RESET_ALL}\n")
    
    # Check environment variables
    api_key = os.getenv('OPENROUTER_API_KEY')
    base_url = os.getenv('OPENROUTER_BASE_URL')
    
    if not api_key or not base_url:
        print(f"{Fore.RED}错误: 未设置 OPENROUTER_API_KEY 或 OPENROUTER_BASE_URL{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}请在 .env 文件中设置这些环境变量{Style.RESET_ALL}")
        return
    
    print(f"{Fore.GREEN}✓ API配置: {base_url}{Style.RESET_ALL}\n")
    
    # 启动Web服务器
    print(f"{Fore.YELLOW}正在启动Web界面...{Style.RESET_ALL}")
    web_thread = threading.Thread(target=start_web_server, daemon=True)
    web_thread.start()
    
    # 等待一下让服务器启动
    import time
    time.sleep(2)
    
    # 获取端口用于显示
    port = int(os.getenv('PORT', '8000'))
    print(f"{Fore.GREEN}✓ Web界面已启动: http://localhost:{port}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}你可以在浏览器中打开上述地址查看对话历史{Style.RESET_ALL}")
    print(f"{Fore.YELLOW}注意: Web界面会实时显示对话历史，无需手动刷新{Style.RESET_ALL}\n")
    
    # Interactive loop
    print(f"{Fore.YELLOW}输入你的任务（输入 'quit' 退出，'clear' 清空历史，'history' 查看历史）:{Style.RESET_ALL}\n")
    
    while True:
        try:
            query = input(f"{Fore.CYAN}> {Style.RESET_ALL}").strip()
            
            if not query:
                continue
            
            if query.lower() in ['quit', 'exit', 'q']:
                print(f"{Fore.YELLOW}退出程序...{Style.RESET_ALL}")
                break
            
            if query.lower() in ['clear', '清空']:
                agent_runner.clear_history()
                continue
            
            if query.lower() in ['history', '历史', 'h']:
                print(f"\n{Fore.CYAN}{agent_runner.get_history_summary()}{Style.RESET_ALL}\n")
                continue
            
            # Run the agent (同步调用)
            result = agent_runner.run_agent(query)
            
            if result:
                print(f"\n{Fore.GREEN}{'='*60}{Style.RESET_ALL}")
                print(f"{Fore.GREEN}执行完成！{Style.RESET_ALL}")
                print(f"{Fore.GREEN}{'='*60}{Style.RESET_ALL}\n")
            
        except KeyboardInterrupt:
            print(f"\n{Fore.YELLOW}程序被中断，退出...{Style.RESET_ALL}")
            break
        except Exception as e:
            print(f"{Fore.RED}发生错误: {e}{Style.RESET_ALL}")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    main()

