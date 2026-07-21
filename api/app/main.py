from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import cache
from app.config import settings
from app.routers import auth, composers, games, search, tags, users


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await cache.close()


app = FastAPI(title="GameMusic API", version="0.1.0", lifespan=lifespan)

_allow_origins = list({settings.frontend_url, "http://localhost:3000"})

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(search.router,    prefix="/search",    tags=["search"])
app.include_router(games.router,     prefix="/games",     tags=["games"])
app.include_router(composers.router, prefix="/composers", tags=["composers"])
app.include_router(tags.router,      prefix="/tags",      tags=["tags"])
app.include_router(users.router,     prefix="/users",     tags=["users"])
app.include_router(auth.router,      prefix="/auth",      tags=["auth"])


@app.get("/health")
def health():
    return {"status": "ok"}
