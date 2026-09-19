"""独立 RAG 问答接口；业务实现保留在迁入的 rag_ingestion 包中。"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from rag_ingestion.qa_service import ask_question

router = APIRouter(prefix="/rag", tags=["rag"])


class RagAskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)


@router.post("/ask")
def ask(request: RagAskRequest) -> dict:
    question = request.question.strip()
    if not question:
        raise HTTPException(status_code=422, detail="问题不能为空")
    return ask_question(question)
