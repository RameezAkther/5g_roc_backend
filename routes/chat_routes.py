from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime
from bson import ObjectId
from pydantic import BaseModel
from typing import List

from db.database import db
from services.dependencies import get_current_user
from services.chat_llm import llm, build_system_prompt
from rag.rag_retriever import retrieve_docs_for_user
from services.analyst_context import build_network_summary
from utils.message_utils import compress_message
from langchain_core.messages import HumanMessage, SystemMessage 
from fastapi.responses import StreamingResponse

router = APIRouter(prefix="/chat", tags=["Chat"])

chat_sessions = db["chat_sessions"]
chat_messages = db["chat_messages"]


# --------------------------
# Helpers
# --------------------------

def safe_object_id(id_str: str) -> ObjectId:
    """Validate and convert string to ObjectId, or raise 400."""
    try:
        return ObjectId(id_str)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid session ID")


# --------------------------
# Models
# --------------------------

class SessionCreate(BaseModel):
    type: str  # "knowledge" or "analyst"
    title: str | None = None


class ChatRequest(BaseModel):
    message: str


class MemoryUpdate(BaseModel):
    included_message_ids: List[str]


# --------------------------
# List sessions
# --------------------------

@router.get("/sessions")
async def list_sessions(current_user=Depends(get_current_user)):
    user_id = current_user.id
    sessions: list[dict] = []

    async for s in chat_sessions.find({"user_id": user_id}).sort("updated_at", -1):
        sessions.append({
            "id": str(s["_id"]),
            "title": s.get("title") or "Untitled chat",
            "type": s["type"],
            "created_at": s["created_at"],
            "updated_at": s["updated_at"],
        })

    return sessions


# --------------------------
# Create new session
# --------------------------

@router.post("/sessions")
async def create_session(
    payload: SessionCreate,
    current_user=Depends(get_current_user)
):
    if payload.type not in ("knowledge", "analyst"):
        raise HTTPException(status_code=400, detail="Invalid session type")

    doc = {
        "user_id": current_user.id,
        "type": payload.type,
        "title": payload.title or (
            "5G Knowledge Chat" if payload.type == "knowledge" else "5G Analyst Chat"
        ),
        "selected_docs": [],   # ✅ PER SESSION DOC FILTER
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
    }


    result = await chat_sessions.insert_one(doc)

    # ✅ Return JSON-friendly data (no raw ObjectId)
    return {
        "id": str(result.inserted_id),
        "title": doc["title"],
        "type": doc["type"],
        "created_at": doc["created_at"],
        "updated_at": doc["updated_at"],
    }


# --------------------------
# Get messages for a session
# --------------------------

@router.get("/sessions/{session_id}/messages")
async def get_session_messages(
    session_id: str,
    current_user=Depends(get_current_user)
):
    oid = safe_object_id(session_id)

    session = await chat_sessions.find_one({"_id": oid})
    if not session or session["user_id"] != current_user.id:
        raise HTTPException(status_code=404, detail="Session not found")

    msgs: list[dict] = []
    async for m in chat_messages.find({"session_id": session_id}).sort("created_at", 1):
        msgs.append({
            "id": str(m["_id"]),
            "role": m["role"],
            "content": m["content"],
            "short_content": m.get("short_content"),
            "included_in_context": m.get("included_in_context", True),
            "created_at": m["created_at"],
            "sources": m.get("sources", [])   # ✅✅✅ REQUIRED FOR TOOLTIP
        })

    return msgs



# --------------------------
# Update memory selection for a session
# --------------------------

@router.patch("/sessions/{session_id}/memory")
async def update_memory(
    session_id: str,
    payload: MemoryUpdate,
    current_user=Depends(get_current_user),
):
    oid = safe_object_id(session_id)

    session = await chat_sessions.find_one({"_id": oid})
    if not session or session["user_id"] != current_user.id:
        raise HTTPException(status_code=404, detail="Session not found")

    include_set = set(payload.included_message_ids)

    async for m in chat_messages.find({"session_id": session_id}):
        flag = str(m["_id"]) in include_set
        await chat_messages.update_one(
            {"_id": m["_id"]},
            {"$set": {"included_in_context": flag}}
        )

    return {"message": "Memory selection updated"}


# --------------------------
# Send message (core RAG + Analyst logic)
# --------------------------

@router.post("/sessions/{session_id}/messages")
async def send_message(
    session_id: str,
    payload: ChatRequest,
    current_user=Depends(get_current_user)
):
    oid = safe_object_id(session_id)

    session = await chat_sessions.find_one({"_id": oid})
    if not session or session["user_id"] != current_user.id:
        raise HTTPException(status_code=404, detail="Session not found")

    user_id = current_user.id
    mode = session["type"]

    # 1️⃣ Save user message
    user_msg_doc = {
        "session_id": session_id,
        "user_id": user_id,
        "role": "user",
        "content": payload.message,
        "short_content": compress_message(payload.message),
        "included_in_context": True,
        "created_at": datetime.utcnow().isoformat(),
    }
    await chat_messages.insert_one(user_msg_doc)

    # ✅ AUTO-TITLE ONLY ON FIRST USER MESSAGE
    msg_count = await chat_messages.count_documents({"session_id": session_id})

    if msg_count == 1:
        auto_title = compress_message(payload.message)[:50]
        await chat_sessions.update_one(
            {"_id": oid},
            {"$set": {"title": auto_title}}
        )

    # 2️⃣ Build context (history + RAG / Analyst data)
    # 2a. Get selected messages, limit to last N for context window
    history_records: list[dict] = []
    async for m in chat_messages.find(
        {"session_id": session_id, "included_in_context": True}
    ).sort("created_at", -1).limit(12):   # last 12 messages
        history_records.append(m)

    # We fetched newest first; reverse to oldest→newest order
    history_records.reverse()

    # Build a plain-text history with roles (better for the model)
    history_text_lines = []
    for m in history_records:
        prefix = "User" if m["role"] == "user" else "Assistant"
        history_text_lines.append(f"{prefix}: {m['content']}")
    history_text = "\n".join(history_text_lines) if history_text_lines else "No prior messages."

    # 2b. Build extra context (docs or network data)
    extra_context = ""
    if mode == "knowledge":
        try:
            docs = await retrieve_docs_for_user(
                    user_id=user_id,
                    session_id=oid,
                    query=payload.message,
                    k=5
                )
            docs_text = "\n\n".join([d["text"] for d in docs]) if docs else "No relevant documents found."
            extra_context = f"Relevant documents:\n{docs_text}"
        except Exception as e:
            # Don't break the chat if retrieval fails; just log context failure
            extra_context = f"(Warning: document retrieval failed: {str(e)})"
    else:  # "analyst"
        try:
            network_summary = build_network_summary()
            extra_context = f"Current network summary:\n{network_summary}"
        except Exception as e:
            extra_context = f"(Warning: network summary failed: {str(e)})"

    system_prompt = build_system_prompt(mode)
    system_msg = SystemMessage(system_prompt)

    # 3️⃣ Call Gemini via LangChain
    final_prompt = [
        system_msg,
        HumanMessage(
            content=(
                "Here is prior conversation context:\n"
                + history_text
                + "\n\nAdditional context:\n"
                + extra_context
                + "\n\nUser question:\n"
                + payload.message
            )
        ),
    ]

    try:
        # ✅ freeze docs BEFORE streaming to avoid closure bug
        docs_for_tooltip = docs if mode == "knowledge" else []

        async def token_stream():
            full_answer = ""

            for chunk in llm.stream(final_prompt):
                if chunk.content:
                    full_answer += chunk.content
                    yield chunk.content

            # ✅ Save assistant message after streaming completes
            await chat_messages.insert_one({
                "session_id": session_id,
                "user_id": user_id,
                "role": "assistant",
                "content": full_answer,
                "short_content": compress_message(full_answer),
                "included_in_context": True,
                "created_at": datetime.utcnow().isoformat(),
                "sources": docs_for_tooltip
            })

            await chat_sessions.update_one(
                {"_id": oid},
                {"$set": {"updated_at": datetime.utcnow().isoformat()}}
            )

        return StreamingResponse(token_stream(), media_type="text/plain")

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM error: {str(e)}")


# --------------------------
# Delete a chat session (and its messages)
# --------------------------

@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str,
    current_user=Depends(get_current_user)
):
    oid = safe_object_id(session_id)

    # 1️⃣ Verify session belongs to this user
    session = await chat_sessions.find_one({"_id": oid})
    if not session or session["user_id"] != current_user.id:
        raise HTTPException(status_code=404, detail="Session not found")

    # 2️⃣ Delete all messages linked to this session
    await chat_messages.delete_many({"session_id": session_id})

    # 3️⃣ Delete the session itself
    await chat_sessions.delete_one({"_id": oid})

    return {"message": "Chat session deleted successfully"}

class RenameSessionRequest(BaseModel):
    title: str


@router.patch("/sessions/{session_id}/rename")
async def rename_session(
    session_id: str,
    payload: RenameSessionRequest,
    current_user=Depends(get_current_user)
):
    oid = ObjectId(session_id)
    session = await chat_sessions.find_one({"_id": oid})

    if not session or session["user_id"] != current_user.id:
        raise HTTPException(404, "Session not found")

    await chat_sessions.update_one(
        {"_id": oid},
        {"$set": {
            "title": payload.title,
            "updated_at": datetime.utcnow().isoformat()
        }}
    )

    return {"message": "Session renamed"}


class DocSelectionUpdate(BaseModel):
    selected_doc_ids: List[str]


@router.patch("/sessions/{session_id}/documents")
async def update_session_documents(
    session_id: str,
    payload: DocSelectionUpdate,
    current_user=Depends(get_current_user),
):
    oid = safe_object_id(session_id)

    session = await chat_sessions.find_one({"_id": oid})
    if not session or session["user_id"] != current_user.id:
        raise HTTPException(status_code=404, detail="Session not found")

    await chat_sessions.update_one(
        {"_id": oid},
        {"$set": {
            "selected_docs": payload.selected_doc_ids,
            "updated_at": datetime.utcnow().isoformat()
        }}
    )

    return {"message": "Session document filter updated"}
