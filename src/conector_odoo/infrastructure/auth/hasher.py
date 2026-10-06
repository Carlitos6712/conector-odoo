"""Argon2id password hashing (``argon2-cffi``); parameters follow the library defaults."""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError


class Argon2PasswordHasher:
    def __init__(
        self,
        *,
        time_cost: int = 3,
        memory_cost: int = 64 * 1024,
        parallelism: int = 4,
    ) -> None:
        self._hasher = PasswordHasher(
            time_cost=time_cost, memory_cost=memory_cost, parallelism=parallelism
        )

    def hash(self, password: str) -> str:
        return self._hasher.hash(password)

    def verify(self, password_hash: str, password: str) -> bool:
        try:
            return self._hasher.verify(password_hash, password)
        except (VerificationError, InvalidHashError):
            return False
