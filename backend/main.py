import uuid
import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from db import (
    init_db, create_session, update_session, get_session_row,
    list_sessions, delete_session, save_message, get_messages,
)
from pipeline_agent import process
from agent.session import get_session, reset_session, serialize_state, restore_state


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="PixarGen API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class NewSessionRequest(BaseModel):
    name: str


@app.get("/api/sessions")
async def get_sessions():
    return await list_sessions()


@app.post("/api/sessions")
async def new_session(body: NewSessionRequest):
    session_id = str(uuid.uuid4())
    await create_session(session_id, body.name)
    return {"id": session_id, "name": body.name}


@app.get("/api/sessions/{session_id}")
async def get_session_info(session_id: str):
    row = await get_session_row(session_id)
    if not row:
        raise HTTPException(404, "Сессия не найдена")
    return row


@app.get("/api/sessions/{session_id}/download/md")
async def download_md(session_id: str):
    row = await get_session_row(session_id)
    if not row or not row.get("project_json"):
        raise HTTPException(404, "Нет данных")
    from agent.render import render_markdown
    from agent.session import restore_state, serialize_state
    import json as _json
    st = restore_state(f"dl_{session_id}", row["session_state_json"] or "{}")
    if not st.project:
        raise HTTPException(404, "Проект не найден")
    content = render_markdown(st.project)
    from agent.render import slugify
    filename = f"{slugify(st.project.title)}.md"
    return PlainTextResponse(
        content,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/sessions/{session_id}/download/json")
async def download_json(session_id: str):
    row = await get_session_row(session_id)
    if not row or not row.get("session_state_json"):
        raise HTTPException(404, "Нет данных")
    from agent.session import restore_state
    st = restore_state(f"dlj_{session_id}", row["session_state_json"])
    if not st.project:
        raise HTTPException(404, "Проект не найден")
    content = json.dumps(st.project.to_dict(), ensure_ascii=False, indent=2)
    from agent.render import slugify
    filename = f"{slugify(st.project.title)}.json"
    return PlainTextResponse(
        content,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.delete("/api/sessions/{session_id}")
async def remove_session(session_id: str):
    reset_session(session_id)
    await delete_session(session_id)
    return {"ok": True}


@app.get("/api/sessions/{session_id}/messages")
async def get_session_messages(session_id: str):
    return await get_messages(session_id)


@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    await websocket.accept()

    row = await get_session_row(session_id)
    if not row:
        await websocket.send_json({"type": "error", "text": "Сессия не найдена"})
        await websocket.close()
        return

    st = get_session(session_id)

    if st.stage == "naming" and row.get("session_state_json"):
        st = restore_state(session_id, row["session_state_json"])

    history = await get_messages(session_id)
    for m in history:
        await websocket.send_json({"type": "history", "role": m["role"], "text": m["text"]})

    if st.stage == "naming" and not history:
        greeting = (
            "👋 Привет! Меня зовут PixarGen.\n\n"
            "Как назовём наш мультфильм?\n"
            f"_(Ты уже ввёл название: *{row['name']}*)_"
        )
        await websocket.send_json({"type": "message", "role": "agent", "text": greeting})
        await save_message(session_id, "agent", greeting)

        responses = await process(session_id, row["name"])
        for r in responses:
            payload = {"type": "message", "role": "agent", "text": r["text"]}
            if r.get("buttons"):
                payload["buttons"] = r["buttons"]
            await websocket.send_json(payload)
            await save_message(session_id, "agent", r["text"])

        new_st = get_session(session_id)
        proj_json = json.dumps(new_st.project.to_dict()) if new_st.project else None
        await update_session(session_id, new_st.stage, proj_json)

    try:
        while True:
            data = await websocket.receive_json()
            user_text = str(data.get("text", "")).strip()
            if not user_text:
                continue

            await save_message(session_id, "user", user_text)
            await websocket.send_json({"type": "message", "role": "user", "text": user_text})

            await websocket.send_json({"type": "typing"})

            responses = await process(session_id, user_text)

            for r in responses:
                payload = {"type": "message", "role": "agent", "text": r["text"]}
                if r.get("buttons"):
                    payload["buttons"] = r["buttons"]
                await websocket.send_json(payload)
                await save_message(session_id, "agent", r["text"])

            new_st = get_session(session_id)
            proj_json = json.dumps(new_st.project.to_dict()) if new_st.project else None
            state_json = serialize_state(new_st)
            await update_session(session_id, new_st.stage, proj_json, state_json)

    except WebSocketDisconnect:
        pass
