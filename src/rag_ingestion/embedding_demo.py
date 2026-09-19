embedding_content_1 = """
将 sds 代替 C 默认的 char* 类型
因为 char* 类型的功能单一，抽象层次低，并且不能高效地支持一些 Redis 常用的操作（比 如追加操作和长度计算操作） ，所以在 Redis 程序内部，绝大部分情况下都会使用 sds 而不是 char* 来表示字符串。
性能问题在稍后介绍 sds 定义的时候就会说到，因为我们还没有了解过 Redis 的其他功能模 块，所以也没办法详细地举例说那里用到了 sds ，不过在后面的章节中，我们会经常看到其他 模块（几乎每一个）都用到了 sds 类型值。
目前来说，只要记住这样一个事实即可：在 Redis 中，客户端传入服务器的协议内容、 aof 缓 存、返回给客户端的回复，等等，这些重要的内容都是由都是由 sds 类型来保存的。
"""



embedding_content_2 = r"""
1.1.2 Redis 中的字符串
在 C 语言中，字符串可以用一个 \0 结尾的 char 数组来表示。
比如说， hello world 在 C 语言中就可以表示为 "hello world\0" 。
这种简单的字符串表示在大多数情况下都能满足要求，但是，它并不能高效地支持长度计算和 追加（ append ）这两种操作：
- 每次计算字符串长度（ strlen(s) ）的复杂度为 θ ( N ) 。
- 对字符串进行 N 次追加，必定需要对字符串进行 N 次内存重分配（ realloc ） 。
在 Redis 内部，字符串的追加和长度计算并不少见，而 APPEND 和 STRLEN 更是这两种操 作在 Redis 命令中的直接映射，这两个简单的操作不应该成为性能的瓶颈。
另外， Redis 除了处理 C 字符串之外，还需要处理单纯的字节数组，以及服务器协议等内容， 所以为了方便起见， Redis 的字符串表示还应该是二进制安全的：程序不应对字符串里面保存 的数据做任何假设，数据可以是以 \0 结尾的 C 字符串，也可以是单纯的字节数组，或者其他 格式的数据。
考虑到这两个原因， Redis 使用 sds 类型替换了 C 语言的默认字符串表示： sds 既可以高效地 实现追加和长度计算，并且它还是二进制安全的。
"""


embedding_content_3 = r"""
sds 的实现
在前面的内容中，我们一直将 sds 作为一种抽象数据结构来说明，实际上，它的实现由以下两 部分组成：
```
typedef char *sds; struct sdshdr { // buf 已占用长度 int len; // buf 剩余可用长度 int free; // 实际保存字符串数据的地方 char buf[]; };
```
其中，类型 sds 是 char * 的别名 (alias) ，而结构 sdshdr 则保存了 len 、 free 和 buf 三个 属性。
作为例子，以下是新创建的，同样保存 hello world 字符串的 sdshdr 结构：
```
struct sdshdr { len = 11; free = 0; buf = "hello world \0 "; // buf 的实际长度为 len + 1 };
```
通过 len 属性， sdshdr 可以实现复杂度为 θ (1) 的长度计算操作。
另一方面，通过对 buf 分配一些额外的空间，并使用 free 记录未使用空间的大小， sdshdr 可 以让执行追加操作所需的内存重分配次数大大减少，下一节我们就会来详细讨论这一点。
当然， sds 也对操作的正确实现提出了要求--所有处理 sdshdr 的函数，都必须正确地更新 len 和 free 属性，否则就会造成 bug 。
"""


embedding_content_4 = """
4. Rehash 完毕
在 rehash 的最后阶段，程序会执行以下工作：
1. 释放 ht[0] 的空间；
2. 用 ht[1] 来代替 ht[0] ，使原来的 ht[1] 成为新的 ht[0] ；
3. 创建一个新的空哈希表，并将它设置为 ht[1] ；
4. 将字典的 rehashidx 属性设置为 -1 ，标识 rehash 已停止；
以下是字典 rehash 完毕之后的样子：
对比字典 rehash 之前和 rehash 之后，新的 ht[0] 空间更大，并且字典原有的键值对也没有被 修改或者删除。
"""



import os
from pathlib import Path

from dotenv import load_dotenv
import requests
import math
import json


# 从当前脚本的位置找到项目根目录
project_root = Path(__file__).resolve().parents[2]

# 读取项目根目录下的 .env 文件
load_dotenv(project_root / ".env")

# 获取 Embedding 专用配置
api_key = os.getenv("EMBED_API_KEY")
base_url = os.getenv("EMBED_BASE_URL")
model_name = os.getenv("EMBED_MODEL_NAME")

if not all([api_key, base_url, model_name]):
    raise ValueError("请检查 .env 中的 Embedding 配置是否完整")

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




question_1 = "Redis 为什么使用 SDS，而不是 C 的 char*？"





document_1_vector = get_embedding(embedding_content_1)
document_2_vector = get_embedding(embedding_content_2)
document_3_vector = get_embedding(embedding_content_3)
document_4_vector = get_embedding(embedding_content_4)

question_1_vector = get_embedding(question_1)


# print("正文向量维度：", len(document_vector))
# print("相关问题向量维度：", len(related_vector))



def cosine_similarity(vector_a, vector_b):
    if len(vector_a) != len(vector_b):
        raise ValueError("两组向量的维度必须相同")

    # 对应位置相乘，再求和
    dot_product = sum(a * b for a, b in zip(vector_a, vector_b))

    # 计算两组向量各自的长度
    norm_a = math.sqrt(sum(a * a for a in vector_a))
    norm_b = math.sqrt(sum(b * b for b in vector_b))

    if norm_a == 0 or norm_b == 0:
        raise ValueError("不能计算零向量的余弦相似度")

    return dot_product / (norm_a * norm_b)


document_1_score = cosine_similarity(question_1_vector, document_1_vector)
document_2_score = cosine_similarity(question_1_vector, document_2_vector)
document_3_score = cosine_similarity(question_1_vector, document_3_vector)
document_4_score = cosine_similarity(question_1_vector, document_4_vector)


print("正文1与相关问题的相似度：", document_1_score)
print("正文2与相关问题的相似度：", document_2_score)
print("正文3与相关问题的相似度：", document_3_score)
print("正文4与相关问题的相似度：", document_4_score)


results = [
    {"id": 1, "score": document_1_score, "content": embedding_content_1},
    {"id": 2, "score": document_2_score, "content": embedding_content_2},
    {"id": 3, "score": document_3_score, "content": embedding_content_3},
    {"id": 4, "score": document_4_score, "content": embedding_content_4},
]

# 根据 score 从高到低排序
ranked_results = sorted(
    results,
    key=lambda item: item["score"],
    reverse=True,
)

# 取排名前 3 的结果
top_k = 3
top_results = ranked_results[:top_k]

for rank, item in enumerate(top_results, start=1):
    print(f"\n第 {rank} 名：正文 {item['id']}")
    print(f"相似度：{item['score']:.4f}")
    print(item["content"].strip())




documents = [
    {"id": 1, "content": embedding_content_1, "vector": document_1_vector},
    {"id": 2, "content": embedding_content_2, "vector": document_2_vector},
    {"id": 3, "content": embedding_content_3, "vector": document_3_vector},
    {"id": 4, "content": embedding_content_4, "vector": document_4_vector},
]

saved_data = {
    "model": model_name,
    "dimensions": len(document_1_vector),
    "documents": documents,
}

output_path = (
    Path(__file__).resolve().parent
    / "data"
    / "output"
    / "embedding_demo.vectors.json"
)

output_path.parent.mkdir(parents=True, exist_ok=True)

with output_path.open("w", encoding="utf-8") as file:
    json.dump(saved_data, file, ensure_ascii=False, indent=2)

print("正文向量已保存到：", output_path)