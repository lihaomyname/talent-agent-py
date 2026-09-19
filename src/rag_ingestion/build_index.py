import json
from pathlib import Path

import os
from pathlib import Path

from dotenv import load_dotenv
import requests
import math

# 从当前脚本的位置找到项目根目录
project_root = Path(__file__).resolve().parents[2]

# 读取项目根目录下的 .env 文件
load_dotenv(project_root / ".rag.env")

# 获取 Embedding 专用配置
api_key = os.getenv("EMBED_API_KEY")
base_url = os.getenv("EMBED_BASE_URL")
model_name = os.getenv("EMBED_MODEL_NAME")


def get_embedding(text):
    response = requests.post(
        base_url.rstrip("/") + "/embeddings",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model_name,
            "input": [text.strip()],
            "encoding_format": "float",
        },
        timeout=30,
    )

    if not response.ok:
        print("接口错误：", response.text)

    response.raise_for_status()
    # print("接口返回内容：", response.text)
    return response.json()["data"][0]["embedding"]


chunk_path = (
        Path(__file__).resolve().parent
        / "data"
        / "output"
        / "progit.cleaned.chunks.jsonl"
)

chunks = []

with chunk_path.open("r", encoding="utf-8") as file:
    for line in file:
        if line.strip():
            chunks.append(json.loads(line))

print("分块数量：", len(chunks))

# 展示一个正文块，确认读到了内容
chunk = chunks[3]

print("分块 ID：", chunk["chunk_id"])
print("待向量化文本：")
print(chunk["embedding_content"])

embedding_vectors = []

for chunk in chunks:
    chunk_id = chunk["chunk_id"]
    embedding_content = chunk["embedding_content"]
    embedding_vector = get_embedding(embedding_content)
    embedding_vectors.append({
        "id": chunk["chunk_id"],
        "content": chunk["content"],
        "embedding_content": embedding_content,
        "source": chunk["source"],
        "metadata": chunk["metadata"],
        "vector": embedding_vector,
    })

saved_data = {
    "model": model_name,
    "dimensions": len(embedding_vectors[0]["vector"]),
    "documents": embedding_vectors,
}

output_path = (
        Path(__file__).resolve().parent
        / "data"
        / "output"
        / "embedding_progit.vectors.json"
)

output_path.parent.mkdir(parents=True, exist_ok=True)

with output_path.open("w", encoding="utf-8") as file:
    json.dump(saved_data, file, ensure_ascii=False, indent=2)

print("正文向量已保存到：", output_path)
