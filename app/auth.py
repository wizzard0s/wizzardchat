"""Authentication & authorization utilities."""

from datetime import datetime, timedelta, timezone
from typing import Optional, Callable
import bcrypt
from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import get_settings
from app.database import get_db
from app.models import User, CustomRole

settings = get_settings()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")
oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=settings.access_token_expire_minutes))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise credentials_exception
    return user


async def optional_current_user(
    token: Optional[str] = Depends(oauth2_scheme_optional),
    db: AsyncSession = Depends(get_db),
) -> Optional[User]:
    """Like get_current_user but returns None instead of raising 401 when no token is provided."""
    if not token:
        return None
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        user_id: str = payload.get("sub")
        if user_id is None:
            return None
    except JWTError:
        return None
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    return user if (user and user.is_active) else None


async def _get_user_permissions(user: User, db: AsyncSession) -> dict:
    """Load the permissions dict for the given user's role from CustomRole table."""
    role_row = (await db.execute(
        select(CustomRole).where(CustomRole.name == user.role.value)
    )).scalar_one_or_none()
    return role_row.permissions if role_row else {}


def require_permission(perm: str) -> Callable:
    """FastAPI dependency factory — raises 403 if the current user lacks *perm*."""
    async def _check(
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        perms = await _get_user_permissions(user, db)
        if not perms.get(perm):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied: requires '{perm}'",
            )
        return user
    return _check
