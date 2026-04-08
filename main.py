import os
import litellm
from dotenv import load_dotenv
from crewai import Crew, Process, Task
from src.tools.nmap_tool import NmapScanTool
from src.agents.pentest_agent import create_pentest_agent

load_dotenv()

# 统一配置 API 和模型
api_key = os.getenv("OPENROUTER_API_KEY")
model = os.getenv("OPENROUTER_MODEL", "deepseek/deepseek-v3.2")

# 设置环境变量供 CrewAI 使用
os.environ["OPENAI_API_KEY"] = api_key
os.environ["OPENAI_API_BASE"] = "https://openrouter.ai/api/v1"
os.environ["OPENAI_MODEL_NAME"] = model  # CrewAI 会读取这个

# 验证配置
if not api_key:
    raise ValueError("请在 .env 中设置 OPENROUTER_API_KEY")

print(f"使用模型: {model}")

def main():
    # 初始化工具
    nmap_tool = NmapScanTool()
    tools = [nmap_tool]

    # 创建Agent
    pentest_agent = create_pentest_agent(tools)

    # 创建Task
    scan_task = Task(
        description="""对目标 {target} 执行端口扫描。
                      使用 Nmap 工具进行快速端口扫描，识别所有开放端口
                      以及运行的服务版本信息。""",
        expected_output="""一份完整的 Nmap 扫描报告，包括：
                          1. 开放的端口列表
                          2. 每个端口对应的服务名称和版本
                          3. 如果有常见漏洞，给出初步建议""",
        agent=pentest_agent
    )
    
    # 创建 Crew
    pen_test_crew = Crew(
        agents=[pentest_agent],
        tasks=[scan_task],
        process=Process.sequential,  # 顺序执行任务
        verbose=True
    )

    # 执行
    target = input("请输入目标 IP 或域名: ").strip()
    if not target:
        target = "scanme.nmap.org"  # 示例目标
    
    result = pen_test_crew.kickoff(inputs={"target": target})
    print("\n" + "="*50)
    print("扫描结果:")
    print(result)

if __name__ == "__main__":
    main()