import os
from pathlib import Path
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI



# 加载 .env 文件中的环境变量
project_root = Path(__file__).resolve().parents[2]
load_dotenv(project_root / ".rag.env")

# 初始化模型
# 我们将使用这个 llm 实例来驱动所有节点的智能
llm = ChatOpenAI(model="deepseek-v4-flash")
