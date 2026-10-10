"""隔离HTTP验收装配：真实认证和路由，只替换数据库地址。"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from server.routers.collaborator_router import collaborators
from server.routers.delegation_router import delegations
from server.utils.auth_middleware import get_db


@asynccontextmanager
async def lifespan(app):
    """每个HTTP进程只连接本卡隔离schema。"""
    engine = create_async_engine(
        os.environ["POSTGRES_URL"], connect_args={"server_settings": {"search_path": os.environ["C1_TEST_SCHEMA"]}}
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def database():
        """依赖仅改变数据库来源，认证和用例保持真实。"""
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db] = database
    yield
    await engine.dispose()


app = FastAPI(lifespan=lifespan)
app.include_router(collaborators, prefix="/api")
app.include_router(delegations, prefix="/api")
