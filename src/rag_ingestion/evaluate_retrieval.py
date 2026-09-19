import json
import math
from pathlib import Path
import os
import requests

from dotenv import load_dotenv

from rag_ingestion.qa_service import get_embedding, cosine_similarity

project_root = Path(__file__).resolve().parents[2]

load_dotenv(project_root / ".rag.env")

api_key = os.getenv("EMBED_API_KEY")
base_url = os.getenv("EMBED_BASE_URL")
model_name = os.getenv("EMBED_MODEL_NAME")

if not all([api_key, base_url, model_name]):
    raise ValueError("Embedding 配置不完整")


evaluation_path = (
    Path(__file__).resolve().parent
    / "data"
    / "evaluation"
    / "rag_eval_cases.json"
)

with evaluation_path.open("r", encoding="utf-8") as file:
    evaluation_cases = json.load(file)

print("评测问题数量：", len(evaluation_cases))

for case in evaluation_cases:
    print()
    print("ID：", case["id"])
    print("类型：", case["category"])
    print("问题：", case["question"])
    print("参考分块：", case["reference_chunk_ids"])
    print("是否应该拒答：", case["should_refuse"])

vector_path = (
    Path(__file__).resolve().parent
    / "data"
    / "output"
    / "embedding_progit.vectors.json"
)

with vector_path.open("r", encoding="utf-8") as file:
    vector_data = json.load(file)

documents = vector_data["documents"]

print("向量模型：", vector_data["model"])
print("向量维度：", vector_data["dimensions"])
print("向量文档数量：", len(documents))




if model_name != vector_data["model"]:
    raise ValueError(
        "查询使用的模型与文档向量模型不同"
    )

first_question = evaluation_cases[0]["question"]
first_question_vector = get_embedding(first_question)

print("测试问题：", first_question)
print("问题向量维度：", len(first_question_vector))

if len(first_question_vector) != vector_data["dimensions"]:
    raise ValueError("问题向量维度与文档向量维度不同")



results = []

for document in documents:
    score = cosine_similarity(
        first_question_vector,
        document["vector"],
    )

    results.append({
        "id": document["id"],
        "score": score,
    })

ranked_results = sorted(
    results,
    key=lambda item: item["score"],
    reverse=True,
)

top_k = 5
top_results = ranked_results[:top_k]

print("\nTop 5 检索结果：")

for rank, item in enumerate(top_results, start=1):
    print(
        f"第 {rank} 名：{item['id']}"
        f" | 相似度：{item['score']:.4f}"
    )

reference_ids = set(
    evaluation_cases[0]["reference_chunk_ids"]
)

retrieved_ids = {
    item["id"]
    for item in top_results
}

hit_ids = reference_ids & retrieved_ids
missing_ids = reference_ids - retrieved_ids

recall_at_k = (
    len(hit_ids) / len(reference_ids)
    if reference_ids
    else None
)

print("\n参考分块：", sorted(reference_ids))
print("命中分块：", sorted(hit_ids))
print("遗漏分块：", sorted(missing_ids))

if recall_at_k is not None:
    print(f"Recall@{top_k}：{recall_at_k:.2%}")
