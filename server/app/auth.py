import secrets
import string
import bcrypt

_ALPHABET = string.ascii_letters + string.digits


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def generate_password() -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(32))
