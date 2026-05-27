"""FastAPI 主应用"""

import json
from datetime import datetime, timezone, timedelta

from fastapi import FastAPI, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse

from database import get_db, init_db
from models import AnalyzeRequest, AnalyzeResponse, HistoryItem, HistoryResponse
from ai_service import analyze_log

__version__ = "0.1.0"

# 北京时间
CST = timezone(timedelta(hours=8))

app = FastAPI(title="AI Ops Assistant", version=__version__)

# 启动时初始化数据库
init_db()

# 挂载静态文件（前端）
app.mount("/static", StaticFiles(directory="static"), name="static")


# ─── API ──────────────────────────────────────────────────────────

@app.post("/api/analyze", response_model=AnalyzeResponse)
async def analyze(req: AnalyzeRequest):
    """分析报错日志"""
    log_input = req.log.strip()
    if not log_input:
        raise HTTPException(status_code=400, detail="日志内容不能为空")

    # AI 分析
    result = analyze_log(log_input)

    now = datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")
    commands_json = json.dumps(result.get("commands", []), ensure_ascii=False)
    raw_response = json.dumps(result, ensure_ascii=False)

    with get_db() as conn:
        cur = conn.execute(
            """INSERT INTO fault_records
               (log_input, fault_type, cause, commands, solution, risk_level, raw_response, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                log_input,
                result.get("fault_type", ""),
                result.get("cause", ""),
                commands_json,
                result.get("solution", ""),
                result.get("risk_level", "info"),
                raw_response,
                now,
            ),
        )
        record_id = cur.lastrowid

    return AnalyzeResponse(
        id=record_id,
        fault_type=result.get("fault_type", ""),
        cause=result.get("cause", ""),
        commands=result.get("commands", []),
        solution=result.get("solution", ""),
        risk_level=result.get("risk_level", "info"),
        created_at=now,
    )


@app.get("/api/history", response_model=HistoryResponse)
async def get_history(page: int = 1, size: int = 20):
    """获取历史分析记录（分页）"""
    offset = max(0, (page - 1) * size)
    limit = min(max(1, size), 100)

    with get_db() as conn:
        total = conn.execute("SELECT COUNT(*) FROM fault_records").fetchone()[0]
        rows = conn.execute(
            "SELECT id, log_input, fault_type, risk_level, created_at "
            "FROM fault_records ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()

    items = [
        HistoryItem(
            id=r["id"],
            log_input=r["log_input"][:120] + ("…" if len(r["log_input"]) > 120 else ""),
            fault_type=r["fault_type"],
            risk_level=r["risk_level"],
            created_at=r["created_at"],
        )
        for r in rows
    ]
    return HistoryResponse(total=total, items=items)


@app.get("/api/history/{record_id}", response_model=AnalyzeResponse)
async def get_record(record_id: int):
    """获取单条历史分析记录详情"""
    with get_db() as conn:
        r = conn.execute(
            "SELECT * FROM fault_records WHERE id = ?", (record_id,)
        ).fetchone()

    if not r:
        raise HTTPException(status_code=404, detail="记录不存在")

    commands = json.loads(r["commands"]) if r["commands"] else []

    return AnalyzeResponse(
        id=r["id"],
        fault_type=r["fault_type"],
        cause=r["cause"],
        commands=commands,
        solution=r["solution"],
        risk_level=r["risk_level"],
        created_at=r["created_at"],
    )


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": __version__}


# ─── 首页 ─────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    with open("static/index.html", encoding="utf-8") as f:
        return HTMLResponse(f.read())
