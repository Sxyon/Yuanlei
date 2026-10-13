"""隔离证据服务：装配真实路由、认证、PG和文件域，不替代产品宿主。"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from server.routers import router
from yuxi.storage.postgres.manager import pg_manager

pg_manager.initialize()
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_headers=["*"],
    allow_methods=["*"],
)
app.include_router(router, prefix="/api")
