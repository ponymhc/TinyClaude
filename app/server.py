"""
Tiny Claude Web Server - FastAPI 后端

提供 REST API 和 SSE 流式接口，支持会话管理和流式对话。
"""

import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config.config import create_session_manager


session_manager = None
is_streaming = False
cancel_event: Optional[asyncio.Event] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    global session_manager
    session_manager = create_session_manager()
    yield
    if session_manager:
        await session_manager.close()


app = FastAPI(title="Tiny Claude Web", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# 挂载静态文件目录
# =============================================================================

# 静态文件根目录（app/static/）
STATIC_DIR = Path(__file__).parent / "static"

# 挂载 CSS 目录
css_dir = STATIC_DIR / "css"
if css_dir.exists():
    app.mount("/css", StaticFiles(directory=str(css_dir)), name="css")
else:
    print(f"Warning: CSS directory not found at {css_dir}")

# 挂载 JS 目录
js_dir = STATIC_DIR / "js"
if js_dir.exists():
    app.mount("/js", StaticFiles(directory=str(js_dir)), name="js")
else:
    print(f"Warning: JS directory not found at {js_dir}")

# 注意：/ 路由会在下面通过 serve_index 返回 app/static/index.html


# =============================================================================
# 请求/响应模型
# =============================================================================

class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None


class CreateSessionRequest(BaseModel):
    title: Optional[str] = None


# =============================================================================
# 会话管理 API
# =============================================================================

@app.get("/api/sessions")
async def list_sessions():
    """列出所有会话"""
    if not session_manager or not session_manager.storage:
        return {"sessions": [], "current": None}
    sessions = await session_manager.storage.list_sessions()
    current_id = session_manager.get_session_id()
    return {
        "sessions": [
            {
                "session_id": s.session_id,
                "title": s.title,
                "created_at": s.created_at.isoformat(),
                "updated_at": s.updated_at.isoformat(),
                "turn_count": s.turn_count,
            }
            for s in sessions
        ],
        "current": current_id,
    }


@app.post("/api/sessions")
async def create_session(req: CreateSessionRequest = None):
    """创建新会话"""
    global is_streaming
    if is_streaming:
        raise HTTPException(status_code=409, detail="AI 正在生成中，请等待完成")
    title = req.title if req else None
    session_id = await session_manager.create_session(title)
    return {"session_id": session_id, "title": title or f"会话 {session_id[:8]}"}


@app.post("/api/sessions/{session_id}/load")
async def load_session(session_id: str):
    """加载（切换到）指定会话"""
    global is_streaming
    if is_streaming:
        raise HTTPException(status_code=409, detail="AI 正在生成中，请等待完成")
    success = await session_manager.load_session(session_id)
    if not success:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"status": "ok", "session_id": session_id}


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    """删除指定会话"""
    global is_streaming
    if is_streaming:
        raise HTTPException(status_code=409, detail="AI 正在生成中，请等待完成")
    if session_manager.storage:
        await session_manager.storage.delete_session(session_id)
    # 如果删除的是当前会话，重置状态
    if session_manager.get_session_id() == session_id:
        session_manager.state = None
    return {"status": "ok"}


@app.get("/api/sessions/{session_id}/messages")
async def get_messages(session_id: str):
    """获取指定会话的消息历史"""
    result_messages = []

    if session_manager.storage:
        messages = await session_manager.storage.get_messages(session_id)
        for m in messages:
            result_messages.append({
                "type": m.type,
                "content": m.content,
                "turn_id": m.turn_id,
                "tool_calls": m.tool_calls,
                "tool_call_id": m.tool_call_id,
                "additional_kwargs": m.additional_kwargs,
            })

    return {"messages": result_messages}


@app.get("/api/status")
async def get_status():
    """获取当前状态（是否在流式生成中）"""
    return {
        "streaming": is_streaming,
        "session_id": session_manager.get_session_id() if session_manager else None,
    }


# =============================================================================
# 流式对话 API (SSE)
# =============================================================================

@app.post("/api/chat")
async def chat(req: ChatRequest):
    """流式对话接口，返回 SSE 事件流"""
    global is_streaming, cancel_event

    if is_streaming:
        raise HTTPException(status_code=409, detail="AI 正在生成中，请等待完成")

    is_streaming = True
    cancel_event = asyncio.Event()

    async def event_stream():
        global is_streaming, cancel_event
        try:
            async for event in session_manager.chat(req.message, req.session_id):
                if cancel_event.is_set():
                    yield f"data: {json.dumps({'type': 'cancelled'})}\n\n"
                    break
                try:
                    yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
                except (TypeError, ValueError):
                    # Skip events that can't be serialized
                    pass
        except asyncio.CancelledError:
            yield f"data: {json.dumps({'type': 'cancelled'})}\n\n"
        except Exception as e:
            import traceback
            print(f"[chat] Error: {e}\n{traceback.format_exc()}", flush=True)
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"
        finally:
            is_streaming = False
            cancel_event = None

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/chat/cancel")
async def cancel_chat():
    """取消当前流式生成"""
    global cancel_event
    if cancel_event:
        cancel_event.set()
    return {"status": "ok"}


# =============================================================================
# 工作区文件管理 API
# =============================================================================

def _get_workspace_root() -> Path:
    """获取工作区根目录"""
    from config.config import get_session_config, _get_base_dir
    agent_config = get_session_config().agent
    return Path(_get_base_dir()) / agent_config.dirname


# 可预览的文件扩展名
PREVIEWABLE_EXTENSIONS = {
    '.py', '.js', '.ts', '.tsx', '.jsx', '.json', '.yaml', '.yml', '.toml',
    '.md', '.txt', '.csv', '.html', '.css', '.sh', '.bash', '.zsh',
    '.env', '.gitignore', '.dockerignore', '.cfg', '.ini', '.conf',
    '.rs', '.go', '.java', '.c', '.cpp', '.h', '.hpp',
    '.xml', '.sql', '.log', '.rb', '.php', '.swift', '.kt',
    '.lua', '.vim', '.el', '.clj', '.hs', '.scala', '.r',
}


@app.get("/api/files")
async def list_directory(path: str = ""):
    """列出工作区目录内容"""
    root = _get_workspace_root().resolve()

    # 安全校验：防止路径穿越
    target = (root / path).resolve()
    if not str(target).startswith(str(root)):
        raise HTTPException(status_code=403, detail="不允许访问工作区之外的路径")

    if not target.exists():
        raise HTTPException(status_code=404, detail="路径不存在")
    if not target.is_dir():
        raise HTTPException(status_code=400, detail="不是目录")

    items = []
    try:
        for entry in sorted(target.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())):
            # 跳过隐藏文件和 __pycache__
            if entry.name.startswith('.') or entry.name == '__pycache__':
                continue
            rel_path = str(entry.relative_to(root))
            items.append({
                "name": entry.name,
                "path": rel_path,
                "is_dir": entry.is_dir(),
                "size": entry.stat().st_size if entry.is_file() else 0,
                "previewable": entry.is_file() and entry.suffix.lower() in PREVIEWABLE_EXTENSIONS,
            })
    except PermissionError:
        raise HTTPException(status_code=403, detail="没有权限访问该目录")

    # 计算导航信息
    rel_to_root = target.relative_to(root)
    parent_path = str(rel_to_root.parent) if str(rel_to_root) != '.' else ''

    return {
        "current_path": path,
        "parent_path": parent_path if str(rel_to_root) != '.' else None,
        "items": items,
    }


@app.get("/api/files/content")
async def read_file(path: str):
    """读取文件内容用于预览"""
    root = _get_workspace_root().resolve()

    target = (root / path).resolve()
    if not str(target).startswith(str(root)):
        raise HTTPException(status_code=403, detail="不允许访问工作区之外的路径")

    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")

    if target.suffix.lower() not in PREVIEWABLE_EXTENSIONS:
        raise HTTPException(status_code=400, detail="该文件类型不支持预览")

    # 限制文件大小（500KB）
    size = target.stat().st_size
    if size > 500 * 1024:
        raise HTTPException(status_code=413, detail=f"文件过大 ({size // 1024}KB)，最大支持 500KB")

    try:
        content = target.read_text(encoding='utf-8')
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="无法解码该文件（非文本文件）")

    return {
        "path": path,
        "name": target.name,
        "size": size,
        "content": content,
    }


@app.get("/")
async def serve_index():
    """返回前端主页面"""
    return FileResponse("app/static/index.html")


# =============================================================================
# 启动入口
# =============================================================================

def run():
    """启动 Web 服务"""
    uvicorn.run(
        "app.server:app",
        host="0.0.0.0",
        port=8765,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    run()