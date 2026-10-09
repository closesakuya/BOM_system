from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from .models import User


pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def create_access_token(user: User) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user.id),
        "username": user.username,
        "role": user.role,
        "iat": now,
        "exp": now + timedelta(minutes=settings.token_expire_minutes),
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="登录已失效，请重新登录",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
        user_id = int(payload.get("sub", 0))
    except (jwt.PyJWTError, ValueError, TypeError):
        raise credentials_error
    user = db.get(User, user_id)
    if not user or not user.active:
        raise credentials_error
    return user


def require_roles(*roles: str):
    def dependency(user: Annotated[User, Depends(get_current_user)]) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="当前账户没有执行此操作的权限")
        return user

    return dependency


CurrentUser = Annotated[User, Depends(get_current_user)]
AdminUser = Annotated[User, Depends(require_roles("admin"))]
WriteUser = Annotated[User, Depends(require_roles("admin", "dev", "maintainer"))]
MaterialWriteUser = Annotated[User, Depends(require_roles("admin", "dev", "maintainer", "product"))]
ExportUser = Annotated[User, Depends(require_roles("admin", "dev", "maintainer", "product"))]


def require_bom_export(bom_type: str, user: Annotated[User, Depends(get_current_user)]) -> User:
    if user.role in {'admin', 'dev', 'maintainer', 'product'}:
        return user
    if user.role == 'finance' and bom_type in {'production', 'technical'}:
        return user
    raise HTTPException(403, '当前账户仅可导出已授权的 BOM 类型')


BOMExportUser = Annotated[User, Depends(require_bom_export)]


def check_material_write(user: User, item=None, payload=None) -> None:
    if user.role != 'product':
        return
    if item is not None and (item.item_type != 'material' or item.is_formally_imported or item.unofficial_status != 'pending'):
        raise HTTPException(403, '生产账号只能维护未封存的未正式原材料')
    if payload is not None:
        values = payload.model_dump(exclude_unset=True)
        if item is None and (payload.item_type != 'material' or payload.is_formally_imported):
            raise HTTPException(403, '生产账号只能新建未正式原材料')
        if values.get('components') or values.get('copy_source_id') or values.get('requires_assembly'):
            raise HTTPException(403, '生产账号不能编辑组成或复制组成配置')
