import hashlib
import hmac
import os
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import User


def hash_password(password: str) -> str:
    if not password:
        raise ValueError("La contraseña no puede estar vacía.")

    iterations = 100_000
    salt = os.urandom(16)
    pwd_hash = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
    )
    return f"pbkdf2_sha256${iterations}${salt.hex()}${pwd_hash.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations_str, salt_hex, hash_hex = stored_hash.split("$")
        if algorithm != "pbkdf2_sha256":
            return False

        iterations = int(iterations_str)
        salt = bytes.fromhex(salt_hex)
        expected_hash = bytes.fromhex(hash_hex)

        test_hash = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            iterations,
        )
        return hmac.compare_digest(test_hash, expected_hash)
    except Exception:
        return False


def get_user_by_username(db: Session, username: str) -> Optional[User]:
    stmt = select(User).where(User.username == username)
    return db.scalar(stmt)


def get_all_users(db: Session) -> list[User]:
    stmt = select(User).order_by(User.username)
    return list(db.scalars(stmt).all())


def create_user(
    db: Session,
    username: str,
    full_name: str,
    temporary_password: str,
    role: str = "user",
    is_active: bool = True,
) -> User:
    existing = get_user_by_username(db, username)
    if existing:
        raise ValueError("Ya existe un usuario con ese nombre.")

    user = User(
        username=username.strip(),
        full_name=full_name.strip(),
        password_hash=hash_password(temporary_password),
        role=role.strip(),
        is_active=is_active,
        must_change_password=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def update_user(
    db: Session,
    username: str,
    full_name: str,
    role: str,
    is_active: bool,
) -> User:
    user = get_user_by_username(db, username)
    if not user:
        raise ValueError("Usuario no encontrado.")

    user.full_name = full_name.strip()
    user.role = role.strip()
    user.is_active = is_active
    db.commit()
    db.refresh(user)
    return user


def reset_user_password(
    db: Session,
    username: str,
    temporary_password: str,
) -> User:
    user = get_user_by_username(db, username)
    if not user:
        raise ValueError("Usuario no encontrado.")

    user.password_hash = hash_password(temporary_password)
    user.must_change_password = True
    db.commit()
    db.refresh(user)
    return user


def delete_user(db: Session, username: str) -> None:
    user = get_user_by_username(db, username)
    if not user:
        raise ValueError("Usuario no encontrado.")

    db.delete(user)
    db.commit()


def authenticate_user(db: Session, username: str, password: str) -> Optional[User]:
    user = get_user_by_username(db, username)
    if not user:
        return None
    if not user.is_active:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


def change_password_first_login(
    db: Session,
    username: str,
    new_password: str,
) -> User:
    user = get_user_by_username(db, username)
    if not user:
        raise ValueError("Usuario no encontrado.")

    user.password_hash = hash_password(new_password)
    user.must_change_password = False
    db.commit()
    db.refresh(user)
    return user
