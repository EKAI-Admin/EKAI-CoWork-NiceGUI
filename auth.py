import bcrypt
from nicegui import app


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def get_current_user() -> dict | None:
    return app.storage.user.get("user")


def set_current_user(user: dict):
    app.storage.user["user"] = user


def logout():
    app.storage.user.clear()


def is_authenticated() -> bool:
    return get_current_user() is not None
