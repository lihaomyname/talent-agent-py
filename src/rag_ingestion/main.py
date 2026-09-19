import argparse
import json
from pathlib import Path

from docling.document_converter import DocumentConverter
from docling.chunking import HybridChunker
from docling_core.transforms.chunker.hierarchical_chunker import (
    ChunkingDocSerializer,
    ChunkingSerializerProvider,
)
from docling_core.types.doc.document import DoclingDocument
from docling_core.types.doc.labels import DocItemLabel

from docling_core.transforms.chunker.tokenizer.huggingface import (
    HuggingFaceTokenizer,
)

from transformers import AutoTokenizer


# =========================================================
# 1. 基本配置
# =========================================================

parser = argparse.ArgumentParser(description="解析 PDF，并在分块前过滤目录元素")
parser.add_argument("--from-parsed", action="store_true", help="复用已有解析 JSON，仅重新分块")
args = parser.parse_args()

data_dir = Path(__file__).resolve().parent / "data"
source = data_dir / "input/progit.pdf"

output_dir = data_dir / "output"
output_dir.mkdir(
    parents=True,
    exist_ok=True
)


# =========================================================
# 2. PDF -> DoclingDocument
# =========================================================

parsed_path = output_dir / "progit.docling.json"
if args.from_parsed:
    if not parsed_path.is_file():
        parser.error(f"找不到已有解析结果：{parsed_path}")
    doc = DoclingDocument.load_from_json(parsed_path)
else:
    converter = DocumentConverter()
    result = converter.convert(source)
    doc = result.document


# =========================================================
# 3. 保存 Docling 原始解析结果
#
# 这个 JSON 可以很大。
# 它的作用是：
# - 保留完整文档结构
# - 后续重新 Chunk
# - 调试 PDF 解析问题
#
# 它不是直接拿去做向量检索的。
# =========================================================

if not args.from_parsed:
    doc.save_as_json(parsed_path, ensure_ascii=False)


# =========================================================
# 4. 配置 Chunk Tokenizer
#
# 这里先用 BGE-M3 作为后续 Embedding 模型的 tokenizer。
#
# 注意：
# tokenizer 最好与真正使用的 Embedding 模型保持一致。
# =========================================================

embedding_model_name = "BAAI/bge-m3"

hf_tokenizer = AutoTokenizer.from_pretrained(
    embedding_model_name
)

tokenizer = HuggingFaceTokenizer(
    tokenizer=hf_tokenizer,

    # 第一版先限制到 512 token。
    # 这个数字以后要通过 RAG Evaluation 调整，
    # 不是固定真理。
    max_tokens=512,
)


# =========================================================
# 5. 创建 HybridChunker
# =========================================================

class WithoutDirectorySerializerProvider(ChunkingSerializerProvider):
    """保留完整文档，仅在进入分块时排除目录元素。"""

    def get_serializer(self, doc):
        serializer = ChunkingDocSerializer(doc=doc)
        serializer.params = serializer.params.model_copy(update={
            "labels": serializer.params.labels - {DocItemLabel.DOCUMENT_INDEX},
        })
        return serializer


chunker = HybridChunker(
    tokenizer=tokenizer,
    serializer_provider=WithoutDirectorySerializerProvider(),

    # 相邻且属于相同上下文的小 Chunk，
    # Docling 可以尝试合并。
    merge_peers=True,
)


# =========================================================
# 6. DoclingDocument -> Chunks
# =========================================================

chunks = list(
    chunker.chunk(
        dl_doc=doc
    )
)

print(
    f"总共生成 Chunk 数量: {len(chunks)}"
)


# =========================================================
# 7. 保存成 JSONL
#
# 一行 = 一个 Chunk
#
# 后面非常适合：
#
# JSONL
#   ↓
# Embedding Batch
#   ↓
# Qdrant
#
# =========================================================

chunk_output = (
    output_dir
    / "progit.filtered.chunks.jsonl"
)

with chunk_output.open(
    "w",
    encoding="utf-8"
) as writer:

    for index, chunk in enumerate(chunks):

        # 原始 Chunk 内容
        content = chunk.text

        # 加入标题、章节等上下文后的内容
        #
        # 这个通常更适合拿去做 Embedding。
        embedding_content = (
            chunker.contextualize(chunk)
        )

        record = {
            "chunk_id": f"{source.stem}_{index}",

            "document_id": source.stem,

            "chunk_index": index,

            "source": {
                "file_name": source.name,
                "file_type": source.suffix.lower(),
                "file_path": str(source),
            },

            # 展示给用户/LLM时使用
            "content": content,

            # Embedding时使用
            "embedding_content":
                embedding_content,

            # 暂时完整保存 Docling metadata
            "metadata":
                chunk.meta.export_json_dict(),
        }

        writer.write(
            json.dumps(
                record,
                ensure_ascii=False
            )
            + "\n"
        )


print(
    f"Chunk 已保存到: {chunk_output}"
)
