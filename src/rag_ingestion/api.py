from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from fastapi import FastAPI, HTTPException, Query

from rag_ingestion.qa_service import ask_question

from rag_ingestion.qa_service import ask_question

# uv run uvicorn rag_ingestion.api:app --host 0.0.0.0 --port 8000
app = FastAPI(title="知识库问答")


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)


@app.post("/ask")
def ask(request: AskRequest):
    question = request.question.strip()
    if not question:
        raise HTTPException(status_code=422, detail="问题不能为空")

    return ask_question(question)

@app.get("/ask")
def ask(question: str = Query(..., min_length=1, max_length=4000)):
    question = question.strip()
    if not question:
        raise HTTPException(status_code=422, detail="问题不能为空")

    return ask_question(question)