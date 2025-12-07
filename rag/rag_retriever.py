from rag.vector_store import collection, embed_texts
from db.database import db

documents = db["documents"]


async def retrieve_docs_for_user(
    user_id: str,
    session_id: str,
    query: str,
    k: int = 5,
):
    """
    ✅ Retrieves only the documents selected for THIS SESSION
    ✅ Always respects ownership + COMMON docs
    ✅ Returns filename + text for tooltip display
    """

    # 1️⃣ Get session to know which docs are allowed
    from db.database import db
    chat_sessions = db["chat_sessions"]
    session = await chat_sessions.find_one({"_id": session_id})


    if not session:
        return []

    allowed_doc_ids = session.get("selected_docs", [])

    # ✅ If user selected nothing → fallback to all visible docs
    doc_filter = (
        {"doc_id": {"$in": allowed_doc_ids}}
        if allowed_doc_ids
        else {"user_id": {"$in": [user_id, "COMMON"]}}
    )

    # 2️⃣ Embed the query
    query_emb = embed_texts([query])[0]

    # 3️⃣ Chroma Search
    results = collection.query(
        query_embeddings=[query_emb],
        n_results=k,
        where=doc_filter,
    )

    if not results["documents"]:
        return []

    docs = []

    for i in range(len(results["documents"][0])):
        metadata = results["metadatas"][0][i]
        doc_id = metadata.get("doc_id")

        # ✅ Fetch filename for UI tooltip
        doc_meta = await documents.find_one({"_id": doc_id})
        filename = doc_meta["filename"] if doc_meta else "Unknown"

        docs.append({
            "text": results["documents"][0][i],
            "doc_id": doc_id,
            "filename": filename,
            "score": results["distances"][0][i] if "distances" in results else None
        })

    return docs

