"""Pydantic 数据模型"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict


class AnalyzeRequest(BaseModel):
    log: str = Field(..., min_length=1, description="用户输入的报错日志")
    session_id: Optional[str] = Field(None, description="会话 ID，用于追问上下文")


class AnalyzeResponse(BaseModel):
    id: int
    fault_type: str
    cause: str
    commands: List[Dict[str, str]]
    solution: str
    risk_level: str
    created_at: str


class HistoryItem(BaseModel):
    id: int
    log_input: str
    fault_type: str
    risk_level: str
    created_at: str


class HistoryResponse(BaseModel):
    total: int
    items: List[HistoryItem]
