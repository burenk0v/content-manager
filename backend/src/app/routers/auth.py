import os
import secrets
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from jose import jwt
from passlib.context import CryptContext
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.app.db import get_db
from src.app.models import User

router = APIRouter()

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))


def get_secret_key() -> str:
    configured = os.getenv("BACKEND_SECRET_KEY")
    environment = os.getenv("APP_ENV", "development").lower()
    if environment in {"production", "prod"} and not configured:
        raise RuntimeError("BACKEND_SECRET_KEY must be configured in production")
    return configured or secrets.token_urlsafe(48)


SECRET_KEY = get_secret_key()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class LoginIn(BaseModel):
    username: str
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password):
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


@router.post("/login", response_model=TokenOut)
def login(payload: LoginIn, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == payload.username).first()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token({"sub": user.username, "user_id": user.id})
    return {"access_token": token}


@router.post("/register")
def register(payload: LoginIn, db: Session = Depends(get_db)):
    registration_enabled = os.getenv("REGISTRATION_ENABLED", os.getenv("APP_ENV", "development").lower() not in {"production", "prod"})
    if str(registration_enabled).lower() not in {"1", "true", "yes", "on"}:
        raise HTTPException(status_code=403, detail="Public registration is disabled")
    existing = db.query(User).filter(User.username == payload.username).first()
    if existing:
        raise HTTPException(status_code=400, detail="User already exists")
    user = User(username=payload.username, hashed_password=get_password_hash(payload.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"id": user.id, "username": user.username}
