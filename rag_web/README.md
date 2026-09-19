# 知识库对话页面

采用第一张设计稿：左侧 Markdown 对话，右侧子问题和引用原文。首屏内容为标注的示例，发送问题后使用真实结果。每次请求独立，不传递对话历史。

开发运行：在项目根目录运行 `.venv/bin/python -m uvicorn rag_ingestion.api:app --host 127.0.0.1 --port 8000`；在 web 目录运行 `npm install` 和 `npm run dev -- --port 4173`。页面地址 http://127.0.0.1:4173 。

Vite 将同源 `/ask` 代理到本机 8000 端口，使用 POST JSON `{ "question": "问题" }`。后端返回 `queries: string[]`、`answer: string` 和 `sources` 数组，来源包含 `reference`、`file_name`、`pages`、`chunk_id`、`content`。

支持 Markdown、表格、代码、JSON 检视、原文换行、复制、资料定位、历史轮次选择、取消与错误提示。Enter 发送，Shift+Enter 换行。取消中止浏览器等待，不保证中止服务器端模型推理。

`npm run build` 验证生产构建。部署静态产物时仍需配置 `/ask` 到问答后端的同源代理，Vite 开发代理不包含在产物内。
