import json
from pathlib import Path
import re


def clean_text(text):
    # 删除中文字符之间的空格，但保留换行
    text = re.sub(
        r"(?<=[\u3400-\u4dbf\u4e00-\u9fff])[ \t]+(?=[\u3400-\u4dbf\u4e00-\u9fff])",
        "",
        text,
    )

    # 删除中文字符与后方中文标点之间的空格
    text = re.sub(
        r"(?<=[\u3400-\u4dbf\u4e00-\u9fff])[ \t]+(?=[，。！？；：、）》】」』])",
        "",
        text,
    )

    # 删除中文标点与后方中文字符之间的空格
    text = re.sub(
        r"(?<=[，。！？；：、（《【「『])[ \t]+(?=[\u3400-\u4dbf\u4e00-\u9fff])",
        "",
        text,
    )

    return text


data_dir = Path(__file__).resolve().parent / "data" / "output"

input_path = data_dir / "progit.filtered.chunks.jsonl"
output_path = data_dir / "progit.cleaned.chunks.jsonl"

chunk_count = 0
changed_count = 0

with (
    input_path.open("r", encoding="utf-8") as reader,
    output_path.open("w", encoding="utf-8") as writer,
):
    for line_number, line in enumerate(reader, start=1):
        if not line.strip():
            continue

        record = json.loads(line)

        original_content = record["content"]
        original_embedding_content = record["embedding_content"]

        record["content"] = clean_text(original_content)
        record["embedding_content"] = clean_text(
            original_embedding_content
        )

        if (
                record["content"] != original_content
                or record["embedding_content"] != original_embedding_content
        ):
            changed_count += 1

        writer.write(
            json.dumps(record, ensure_ascii=False) + "\n"
        )

        chunk_count += 1

print("处理分块数量：", chunk_count)
print("发生变化的分块数量：", changed_count)
print("清洗结果已保存到：", output_path)
