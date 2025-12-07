from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from datetime import datetime
import os
import shutil
from bson import ObjectId
import hashlib

from db.database import db
from services.dependencies import get_current_user
from rag.vector_store import collection, embed_texts
from rag.text_extractor import extract_text_from_file
from rag.chunker import chunk_text

router = APIRouter(prefix="/resources", tags=["Resources"])

documents = db["documents"]
hidden_docs = db["user_hidden_docs"]

BASE_COMMON_DIR = "./resources/common"
BASE_USER_DIR = "./resources/users"
ALLOWED_EXTENSIONS = {".pdf", ".txt", ".md"}
MAX_FILE_SIZE_MB = 10

def validate_file(file: UploadFile):
    ext = os.path.splitext(file.filename)[1].lower()

    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail="Only PDF, TXT, and Markdown files are allowed"
        )

    # Size check (FastAPI stores in SpooledTemporaryFile)
    file.file.seek(0, os.SEEK_END)
    size_mb = file.file.tell() / (1024 * 1024)
    file.file.seek(0)

    if size_mb > MAX_FILE_SIZE_MB:
        raise HTTPException(
            status_code=400,
            detail="File exceeds 10MB limit"
        )

def compute_file_hash(path: str):
    sha256 = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(4096), b""):
            sha256.update(block)
    return sha256.hexdigest()

# ✅ GET ALL DOCS FOR USER
@router.get("/")
async def get_resources(current_user=Depends(get_current_user)):
    user_id = current_user.id

    hidden = await hidden_docs.find({"user_id": user_id}).to_list(1000)
    hidden_ids = [h["doc_id"] for h in hidden]

    docs = []

    async for doc in documents.find():
        if doc["doc_type"] == "common" and str(doc["_id"]) in hidden_ids:
            continue
        if doc["doc_type"] == "user" and doc["owner_user_id"] != user_id:
            continue

        docs.append({
            "id": str(doc["_id"]),
            "filename": doc["filename"],
            "doc_type": doc["doc_type"],
            "size_kb": doc.get("size_kb"),
            "uploaded_at": doc.get("uploaded_at")
        })

    return docs


# ✅ UPLOAD DOC
@router.post("/upload")
async def upload_resource(
    file: UploadFile = File(...),
    current_user=Depends(get_current_user)
):
    validate_file(file)
    user_id = current_user.id

    user_folder = os.path.join(BASE_USER_DIR, user_id)
    os.makedirs(user_folder, exist_ok=True)

    file_path = os.path.join(user_folder, file.filename)

    # ✅ 1. SAVE FILE FIRST
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # ✅ 2. NOW COMPUTE HASH (FILE EXISTS)
    file_hash = compute_file_hash(file_path)

    # ✅ 3. CHECK FOR DUPLICATES
    existing = await documents.find_one({
        "owner_user_id": user_id,
        "file_hash": file_hash
    })

    if existing:
        os.remove(file_path)   # ✅ Remove duplicate file
        raise HTTPException(400, "Duplicate document already uploaded")

    # ✅ 4. PROCESS FILE
    text = extract_text_from_file(file_path)
    chunks = chunk_text(text)
    embeddings = embed_texts(chunks)

    doc_id = str(ObjectId())

    collection.add(
        documents=chunks,
        embeddings=embeddings,
        ids=[f"{doc_id}_{i}" for i in range(len(chunks))],
        metadatas=[
            {
                "doc_id": doc_id,
                "user_id": str(user_id),  # ✅ Always string
                "doc_type": "user"
            }
            for _ in range(len(chunks))
        ]
    )

    # ✅ 5. SAVE METADATA IN MONGO
    await documents.insert_one({
        "_id": ObjectId(doc_id),
        "filename": file.filename,
        "doc_type": "user",
        "owner_user_id": user_id,
        "path": file_path,
        "size_kb": round(os.path.getsize(file_path) / 1024, 1),
        "file_hash": file_hash,
        "uploaded_at": datetime.utcnow().isoformat()
    })

    return {"message": "Document uploaded & indexed"}



# ✅ DELETE USER DOC
@router.delete("/{doc_id}")
async def delete_resource(
    doc_id: str,
    current_user=Depends(get_current_user)
):
    user_id = current_user.id
    doc = await documents.find_one({"_id": ObjectId(doc_id)})

    if not doc:
        raise HTTPException(404, "Document not found")

    if doc["doc_type"] == "common":
        raise HTTPException(403, "Common documents cannot be deleted")

    if doc["owner_user_id"] != user_id:
        raise HTTPException(403, "Not allowed")

    if os.path.exists(doc["path"]):
        os.remove(doc["path"])

    # ✅ Remove from vector DB
    collection.delete(where={"doc_id": doc_id})

    await documents.delete_one({"_id": ObjectId(doc_id)})

    return {"message": "Document deleted"}


# ✅ UNLINK COMMON DOC
@router.delete("/{doc_id}/unlink")
async def unlink_common_resource(
    doc_id: str,
    current_user=Depends(get_current_user)
):
    user_id = current_user.id
    doc = await documents.find_one({"_id": ObjectId(doc_id)})

    if not doc or doc["doc_type"] != "common":
        raise HTTPException(400, "Invalid document")

    await hidden_docs.insert_one({
        "user_id": user_id,
        "doc_id": doc_id,
        "hidden_at": datetime.utcnow().isoformat()
    })

    return {"message": "Document hidden for this user"}
