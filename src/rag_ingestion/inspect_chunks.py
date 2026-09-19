"""读取已有分块文件，展示正文和来源；不会重新解析 PDF。"""

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=int, default=186, help="查看的分块序号，从 0 开始")
    parser.add_argument("--filtered", action="store_true", help="查看过滤目录后重新生成的分块")
    args = parser.parse_args()

    file_name = "redis设计与实现.filtered.chunks.jsonl" if args.filtered else "redis规范.chunks.jsonl"
    chunk_file = Path(__file__).parent / "data/output" / file_name
    if not chunk_file.is_file():
        parser.error(f"找不到已有分块文件：{chunk_file}")
    with chunk_file.open(encoding="utf-8") as reader:
        chunks = [json.loads(line) for line in reader if line.strip()]

    if not 0 <= args.index < len(chunks):
        parser.error(f"序号必须在 0 到 {len(chunks) - 1} 之间，共 {len(chunks)} 个分块")

    chunk = chunks[args.index]
    metadata = chunk.get("metadata", {})
    pages = sorted({
        provenance["page_no"]
        for item in metadata.get("doc_items", [])
        for provenance in item.get("prov", [])
        if provenance.get("page_no") is not None
    })

    print(f"分块文件：{chunk_file.name}")
    print(f"共 {len(chunks)} 个分块，当前序号：{args.index}（从 0 开始）")
    print(f"来源：{chunk['source']['file_name']}")
    print("PDF 页码：" + (", ".join(map(str, pages)) or "未记录"))
    print("标题：" + (" > ".join(metadata.get("headings") or []) or "未记录"))
    items = metadata.get("doc_items", [])
    label_names = {
        "document_index": "目录",
        "text": "普通文本",
        "list_item": "列表项",
        "code": "代码",
        "table": "表格",
        "caption": "图表说明",
        "formula": "公式",
        "section_header": "章节标题",
        "picture": "图片",
        "page_header": "页眉",
        "page_footer": "页脚",
    }
    labels = {item.get("label") for item in items}
    if not items:
        directory_status = "未记录元素类型，无法判断"
    elif labels == {"document_index"}:
        directory_status = "全部元素标记为目录"
    elif "document_index" in labels:
        directory_status = "目录与其他元素混合，需要检查"
    else:
        directory_status = "未发现目录标签"
    print("目录检查（依据解析标签）：" + directory_status)
    print("\n元素类型（metadata.doc_items 中的 label）：")
    if not items:
        print("  未记录")
    for number, item in enumerate(items, start=1):
        label = item.get("label")
        item_pages = sorted({
            p["page_no"] for p in item.get("prov", [])
            if p.get("page_no") is not None
        })
        page_text = ", ".join(map(str, item_pages)) or "未记录"
        print(
            f"  {number}. {label or '未记录'}（{label_names.get(label, '未映射类型')}）"
            f" | PDF 页码：{page_text} | 元素引用：{item.get('self_ref', '未记录')}"
        )
    print("\n正文：\n" + chunk["content"])
    print("\n用于后续向量化的文本（现在仍是文字）：\n" + chunk["embedding_content"])


if __name__ == "__main__":
    main()
