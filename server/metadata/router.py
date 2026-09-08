"""元数据查询与人工注释 API 路由。

路径约定：
  GET  /api/v1/metadata/tables               查询表列表（可按 datasource、domain 过滤）
  GET  /api/v1/metadata/tables/{id}           查询表详情（含列列表）
  PATCH /api/v1/metadata/tables/{id}          更新表的人工注释
  PATCH /api/v1/metadata/columns/{id}         更新列的人工注释

人工注释字段（manual_*）在增量同步时不会被覆盖，由本接口独立维护。
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from server.datasource.models import ColumnMetadata, TableMetadata

router = APIRouter(prefix="/api/v1/metadata", tags=["metadata"])


# ---------------------------------------------------------------------------
# 请求与响应 Schema
# ---------------------------------------------------------------------------


class ColumnResponse(BaseModel):
    id: int
    column_name: str
    ordinal_position: int
    data_type: str
    is_nullable: bool
    is_primary_key: bool
    foreign_key_ref: str | None
    raw_comment: str | None
    manual_business_name: str | None
    manual_description: str | None
    manual_sensitivity: str | None
    manual_aliases: str | None  # JSON 字符串数组
    sample_values: str | None  # JSON 字符串数组
    is_deleted: bool

    model_config = {"from_attributes": True}


class TableResponse(BaseModel):
    id: int
    datasource_id: int
    schema_name: str
    table_name: str
    table_type: str
    row_estimate: int | None
    raw_comment: str | None
    manual_business_name: str | None
    manual_description: str | None
    manual_domain: str | None
    manual_grain: str | None
    manual_authoritative_source: str | None
    manual_aliases: str | None  # JSON 字符串数组
    is_deleted: bool
    columns: list[ColumnResponse] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class TableAnnotationUpdate(BaseModel):
    """管理员手工补充的表级业务属性；只允许更新 manual_* 字段。"""

    manual_business_name: str | None = Field(default=None, max_length=256)
    manual_description: str | None = Field(default=None, max_length=4096)
    manual_domain: str | None = Field(default=None, max_length=32)
    manual_grain: str | None = Field(default=None, max_length=512)
    manual_authoritative_source: str | None = Field(default=None, max_length=64)
    manual_aliases: str | None = Field(default=None, max_length=1024)


class ColumnAnnotationUpdate(BaseModel):
    """管理员手工补充的列级业务属性。"""

    manual_business_name: str | None = Field(default=None, max_length=256)
    manual_description: str | None = Field(default=None, max_length=4096)
    manual_sensitivity: str | None = Field(default=None, max_length=32)
    manual_aliases: str | None = Field(default=None, max_length=1024)


# ---------------------------------------------------------------------------
# 依赖项（复用 datasource 模块的依赖）
# ---------------------------------------------------------------------------


async def get_db_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    session_factory = request.app.state.db_session_factory
    async with session_factory() as session:
        yield session


def require_admin(request: Request) -> None:
    """写操作要求管理员身份（复用 datasource 模块的简单令牌校验）。"""
    import os

    expected = os.environ.get("ATLAS_ADMIN_TOKEN")
    token = request.headers.get("x-admin-token")
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="admin token is not configured",
        )
    if token != expected:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="invalid or missing admin token",
        )


# ---------------------------------------------------------------------------
# 路由处理器
# ---------------------------------------------------------------------------


@router.get("/tables", response_model=list[TableResponse])
async def list_tables(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    datasource_id: int | None = None,
    domain: str | None = None,
    include_deleted: bool = False,
) -> list[TableResponse]:
    """查询表列表，可按数据源或业务域过滤。"""
    query = select(TableMetadata).options(selectinload(TableMetadata.columns))

    if datasource_id is not None:
        query = query.where(TableMetadata.datasource_id == datasource_id)
    if domain is not None:
        query = query.where(TableMetadata.manual_domain == domain)
    if not include_deleted:
        query = query.where(TableMetadata.is_deleted.is_(False))

    query = query.order_by(TableMetadata.datasource_id, TableMetadata.table_name)
    result = await session.execute(query)
    tables = result.scalars().all()
    return [TableResponse.model_validate(t) for t in tables]


@router.get("/tables/{table_id}", response_model=TableResponse)
async def get_table(
    table_id: int,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> TableResponse:
    """查询表详情，含所有列元数据。"""
    result = await session.execute(
        select(TableMetadata)
        .options(selectinload(TableMetadata.columns))
        .where(TableMetadata.id == table_id)
    )
    table = result.scalar_one_or_none()
    if table is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="table not found")
    return TableResponse.model_validate(table)


@router.patch("/tables/{table_id}", response_model=TableResponse)
async def annotate_table(
    table_id: int,
    body: TableAnnotationUpdate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    request: Request,
) -> TableResponse:
    """更新表的人工注释字段（不影响采集字段）。"""
    require_admin(request)

    result = await session.execute(
        select(TableMetadata)
        .options(selectinload(TableMetadata.columns))
        .where(TableMetadata.id == table_id)
    )
    table = result.scalar_one_or_none()
    if table is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="table not found")

    # 只更新 manual_* 字段，exclude_unset=True 保证未传的字段保持原值
    for field_name, value in body.model_dump(exclude_unset=True).items():
        setattr(table, field_name, value)

    await session.commit()
    await session.refresh(table)
    return TableResponse.model_validate(table)


@router.patch("/columns/{column_id}", response_model=ColumnResponse)
async def annotate_column(
    column_id: int,
    body: ColumnAnnotationUpdate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    request: Request,
) -> ColumnResponse:
    """更新列的人工注释字段（不影响采集字段）。"""
    require_admin(request)

    result = await session.execute(select(ColumnMetadata).where(ColumnMetadata.id == column_id))
    col = result.scalar_one_or_none()
    if col is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="column not found")

    for field_name, value in body.model_dump(exclude_unset=True).items():
        setattr(col, field_name, value)

    await session.commit()
    await session.refresh(col)
    return ColumnResponse.model_validate(col)
