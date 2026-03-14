"""Auth endpoints: login, register, me."""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User, UserRole
from app.schemas import LoginRequest, TokenResponse, UserCreate, UserOut
from app.auth import hash_password, verify_password, create_access_token, get_current_user

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(form: OAuth2PasswordRequestForm = Depends(), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.username == form.username))
    user = result.scalar_one_or_none()
    if not user or not verify_password(form.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled")

    token = create_access_token({"sub": str(user.id), "role": user.role.value})
    return TokenResponse(
        access_token=token,
        user=UserOut.model_validate(user),
    )


@router.post("/register", response_model=UserOut, status_code=201)
async def register(
    body: UserCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Only admins can create new users
    if current_user.role not in (UserRole.ADMIN, UserRole.SUPER_ADMIN):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin privileges required")
    # Check uniqueness
    exists = await db.execute(
        select(User).where((User.email == body.email) | (User.username == body.username))
    )
    if exists.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email or username already taken")

    user = User(
        email=body.email,
        username=body.username,
        hashed_password=hash_password(body.password),
        full_name=body.full_name,
        role=body.role,
        is_system_account=False,  # never allow system accounts via register
        max_concurrent_chats=body.max_concurrent_chats,
        phone_number=body.phone_number,
        auth_type=body.auth_type,
        languages=body.languages or [],
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return UserOut.model_validate(user)


@router.get("/me", response_model=UserOut)
async def me(current_user: User = Depends(get_current_user)):
    try:
        return UserOut.model_validate(current_user)
    except Exception as exc:
        import traceback, logging
        logging.getLogger("auth").error("GET /me serialization error: %s\n%s", exc, traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Profile serialization error: {exc}")
