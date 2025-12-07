import os
import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer

VECTOR_DIR = "./vector_store/chroma_db"

# ✅ Persistent Chroma Client (NEW API)
chroma_client = chromadb.PersistentClient(path=VECTOR_DIR)

# ✅ Collection
collection = chroma_client.get_or_create_collection(
    name="knowledge_chunks"
)

# ✅ Load Local Embedding Model (FAST + ACCURATE)
embedding_model = SentenceTransformer("all-MiniLM-L6-v2")

# ✅ Local Embedding Function
def embed_texts(texts: list[str]):
    if not texts:
        return []

    embeddings = embedding_model.encode(
        texts,
        convert_to_numpy=True,
        show_progress_bar=False
    )

    return embeddings.tolist()