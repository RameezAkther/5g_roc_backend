from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routes.auth_routes import router as auth_router
from routes.data_routes import router as data_router
from routes.resources_routes import router as resources_router
from rag.startup_common_embedder import embed_common_docs_on_startup
from routes.chat_routes import router as chat_router

from dotenv import load_dotenv
load_dotenv()

app = FastAPI(title="5G Network RAG Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten in production
    allow_methods=["*"],
    allow_headers=["*"],
)

# ✅ Register routers
app.include_router(auth_router)
app.include_router(data_router)
app.include_router(resources_router)
app.include_router(chat_router)

@app.get("/")
def root():
    return {"status": "5G Network RAG Backend is running"}

@app.on_event("startup")
async def on_startup():
    await embed_common_docs_on_startup()
