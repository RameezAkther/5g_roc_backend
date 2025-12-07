import os
from bson import ObjectId
from datetime import datetime

from db.database import db
from rag.text_extractor import extract_text_from_file
from rag.chunker import chunk_text
from rag.vector_store import collection, embed_texts
from routes.resources_routes import compute_file_hash

documents = db["documents"]

BASE_COMMON_DIR = "./resources/common"


async def embed_common_docs_on_startup():
    if not os.path.exists(BASE_COMMON_DIR):
        os.makedirs(BASE_COMMON_DIR, exist_ok=True)
        print("📁 Created common resources directory")
        return

    for filename in os.listdir(BASE_COMMON_DIR):
        path = os.path.join(BASE_COMMON_DIR, filename)

        if not os.path.isfile(path):
            continue

        file_hash = compute_file_hash(path)

        existing = await documents.find_one({
            "doc_type": "common",
            "file_hash": file_hash
        })

        if existing:
            continue  # ✅ Already embedded

        print(f"📥 Embedding common doc: {filename}")

        text = extract_text_from_file(path)
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
                    "user_id": "COMMON",
                    "doc_type": "common"
                }
                for _ in range(len(chunks))
            ]
        )

        await documents.insert_one({
            "_id": ObjectId(doc_id),
            "filename": filename,
            "doc_type": "common",
            "owner_user_id": None,
            "path": path,
            "size_kb": round(os.path.getsize(path) / 1024, 1),
            "file_hash": file_hash,
            "uploaded_at": datetime.utcnow().isoformat()
        })

        print(f"✅ Embedded & stored: {filename}")
