"""Admin authentication and user management use cases.

Sessions are server-side: the cookie carries a random token, only its SHA-256 digest is stored.
Every login issues a brand-new token (any previous one is destroyed), so a token planted before
login is worthless (no session fixation). A session dies at its absolute expiry or after the idle
timeout. Failure paths are uniform: an unknown username burns the same password verification as a
known one (against a dummy hash) and returns the same error, and unknown usernames are throttled
exactly like real ones, so neither the message, the status nor the timing tells them apart.
"""

import asyncio
import hashlib
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from conector_odoo.domain.auth import (
    AdminSession,
    AdminUser,
    Role,
    normalize_username,
    validate_password,
)
from conector_odoo.domain.client_ip import UNKNOWN_IP, client_ip_key
from conector_odoo.domain.errors import (
    AdminUserInvalid,
    AdminUserNotFound,
    AuthenticationFailed,
    CurrentPasswordInvalid,
    LastAdminError,
    LoginLocked,
    SessionInvalid,
)
from conector_odoo.domain.ports import (
    AdminUserRepository,
    IpLoginThrottle,
    KnownLoginIps,
    LoginThrottle,
    PasswordHasher,
    SessionStore,
)

Clock = Callable[[], datetime]
_MAX_KEY_LENGTH = 128
_AUTH_REQUIRED = "authentication required"  # same text for every invalid-session cause


@dataclass(frozen=True, slots=True)
class AuthConfig:
    session_ttl_seconds: int = 12 * 3600
    idle_timeout_seconds: int = 2 * 3600
    max_failures: int = 5
    lockout_seconds: int = 900
    # Per client address: this many failures inside the sliding window block the address.
    ip_max_failures: int = 20
    ip_window_seconds: int = 900
    # A username locked out by OTHER addresses can still be opened from an address it signed in
    # from within this many seconds (0 disables the bypass).
    known_ip_seconds: int = 30 * 24 * 3600


@dataclass(frozen=True, slots=True)
class LoginResult:
    user: AdminUser
    token: str  # the cookie value; never stored
    csrf_token: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class CurrentSession:
    user: AdminUser
    csrf_token: str
    expires_at: datetime


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _throttle_key(username: str) -> str:
    return username.strip().lower()[:_MAX_KEY_LENGTH]


class AuthService:
    def __init__(
        self,
        users: AdminUserRepository,
        sessions: SessionStore,
        throttle: LoginThrottle,
        hasher: PasswordHasher,
        clock: Clock,
        config: AuthConfig = AuthConfig(),  # noqa: B008 - frozen value object
        *,
        ip_throttle: IpLoginThrottle | None = None,
        known_ips: KnownLoginIps | None = None,
    ) -> None:
        self._users = users
        self._sessions = sessions
        self._throttle = throttle
        self._hasher = hasher
        self._clock = clock
        self._config = config
        self._ip_throttle = ip_throttle
        self._known_ips = known_ips
        self._dummy_hash: str | None = None

    async def login(
        self,
        username: str,
        password: str,
        previous_token: str | None = None,
        client_ip: str = UNKNOWN_IP,
    ) -> LoginResult:
        """Raises ``LoginLocked`` or ``AuthenticationFailed``. ``previous_token`` (the cookie the
        browser sent, if any) is destroyed: the session id is rotated on every login.
        ``client_ip`` feeds the per-address throttle (see ``_guard``)."""
        now = self._clock()
        key = _throttle_key(username)
        ip = client_ip_key(client_ip)
        await self._guard(key, ip, now)
        found = await self._users.get_credentials(username.strip())
        stored_hash = found[1] if found else await self._dummy()
        password_ok = await asyncio.to_thread(self._hasher.verify, stored_hash, password)
        if found is None or not password_ok:
            await self._record_failure(key, ip, now)
            raise AuthenticationFailed("invalid username or password")
        user = found[0]
        await self._throttle.reset(key)
        if self._known_ips is not None and self._config.known_ip_seconds > 0:
            await self._known_ips.remember(
                key, ip, now, max_age_seconds=self._config.known_ip_seconds
            )
        if previous_token:
            await self._sessions.delete(hash_token(previous_token))
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        expires_at = now + timedelta(seconds=self._config.session_ttl_seconds)
        await self._sessions.create(
            AdminSession(hash_token(token), user.id, csrf, now, expires_at, now)
        )
        await self._sessions.purge_expired(now)
        return LoginResult(user, token, csrf, expires_at)

    async def change_password(
        self,
        user: AdminUser,
        current_password: str,
        new_password: str,
        client_ip: str = UNKNOWN_IP,
    ) -> LoginResult:
        """Self-service password change for the signed-in ``user``, whatever their role.

        The current password is verified (argon2) and throttled exactly like a login, under the
        same per-username key. On success every session of the user is destroyed and a fresh one
        (new cookie token and CSRF token) is issued, so a stolen session dies with the old
        password. Raises ``LoginLocked``, ``CurrentPasswordInvalid`` or ``AdminUserInvalid``.
        """
        now = self._clock()
        key = _throttle_key(user.username)
        ip = client_ip_key(client_ip)
        # No known-address bypass here: an already-open session guessing the current password is
        # exactly what the username lockout protects against.
        await self._guard(key, ip, now, allow_known_ip=False)
        found = await self._users.get_credentials(user.username)
        stored_hash = found[1] if found else await self._dummy()
        password_ok = await asyncio.to_thread(self._hasher.verify, stored_hash, current_password)
        if found is None or not password_ok:
            await self._record_failure(key, ip, now)
            raise CurrentPasswordInvalid("the current password is incorrect")
        validate_password(new_password)
        if new_password == current_password:
            raise AdminUserInvalid("the new password must differ from the current one")
        new_hash = await asyncio.to_thread(self._hasher.hash, new_password)
        updated = await self._users.update(user.id, password_hash=new_hash)
        await self._throttle.reset(key)
        await self._sessions.delete_for_user(user.id)
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        expires_at = now + timedelta(seconds=self._config.session_ttl_seconds)
        await self._sessions.create(
            AdminSession(hash_token(token), user.id, csrf, now, expires_at, now)
        )
        return LoginResult(updated, token, csrf, expires_at)

    async def authenticate(self, token: str) -> CurrentSession:
        """Resolve the cookie token to its user. Raises ``SessionInvalid``."""
        if not token:
            raise SessionInvalid(_AUTH_REQUIRED)
        digest = hash_token(token)
        session = await self._sessions.get(digest)
        if session is None:
            raise SessionInvalid(_AUTH_REQUIRED)
        now = self._clock()
        idle = timedelta(seconds=self._config.idle_timeout_seconds)
        if now >= session.expires_at or now - session.last_seen_at > idle:
            await self._sessions.delete(digest)
            raise SessionInvalid(_AUTH_REQUIRED)
        user = await self._users.get(session.user_id)
        if user is None:
            await self._sessions.delete(digest)
            raise SessionInvalid(_AUTH_REQUIRED)
        await self._sessions.touch(digest, now)
        return CurrentSession(user, session.csrf_token, session.expires_at)

    async def logout(self, token: str) -> None:
        if token:
            await self._sessions.delete(hash_token(token))

    async def _guard(
        self, key: str, ip: str, now: datetime, *, allow_known_ip: bool = True
    ) -> None:
        """Refuse before any password work. Two independent brakes, one generic error:

        * the client address: too many failures from it (any usernames) inside the window blocks
          it outright, even with correct credentials;
        * the username: locked after repeated failures, EXCEPT for an address that username
          already signed in from. Otherwise anyone could keep a known admin locked out by failing
          on purpose; the owner's usual address still has to know the password and is still
          bounded by the address brake above. (``change_password`` never takes the bypass.)
        """
        if self._ip_throttle is not None:
            ip_wait = await self._ip_throttle.retry_after(
                ip,
                now,
                max_failures=self._config.ip_max_failures,
                window_seconds=self._config.ip_window_seconds,
            )
            if ip_wait > 0:
                raise LoginLocked(ip_wait)
        retry_after = await self._throttle.retry_after(key, now)
        if retry_after > 0 and not (allow_known_ip and await self._is_known_ip(key, ip, now)):
            raise LoginLocked(retry_after)

    async def _is_known_ip(self, key: str, ip: str, now: datetime) -> bool:
        if self._known_ips is None or self._config.known_ip_seconds <= 0:
            return False
        return await self._known_ips.is_known(
            key, ip, now, max_age_seconds=self._config.known_ip_seconds
        )

    async def _record_failure(self, key: str, ip: str, now: datetime) -> None:
        await self._throttle.record_failure(
            key, now, max_failures=self._config.max_failures,
            lock_seconds=self._config.lockout_seconds,
        )  # fmt: skip
        if self._ip_throttle is not None:
            await self._ip_throttle.record_failure(
                ip, now, window_seconds=self._config.ip_window_seconds
            )

    async def _dummy(self) -> str:
        if self._dummy_hash is None:
            self._dummy_hash = await asyncio.to_thread(self._hasher.hash, secrets.token_urlsafe(16))
        return self._dummy_hash


class UserAdmin:
    """Admin-only user management. Password and role changes revoke the user's sessions."""

    def __init__(
        self,
        users: AdminUserRepository,
        sessions: SessionStore,
        hasher: PasswordHasher,
        clock: Clock,
    ) -> None:
        self._users = users
        self._sessions = sessions
        self._hasher = hasher
        self._clock = clock

    async def create(self, username: str, password: str, role: Role) -> AdminUser:
        """Raises ``AdminUserInvalid`` or ``AdminUsernameTaken``."""
        name = normalize_username(username)
        validate_password(password)
        password_hash = await asyncio.to_thread(self._hasher.hash, password)
        return await self._users.add(name, password_hash, role, self._clock())

    async def bootstrap(self, username: str, password: str) -> bool:
        """Create the first admin, only when no user exists. ``True`` when it was created."""
        if await self._users.count() > 0:
            return False
        await self.create(username, password, Role.ADMIN)
        return True

    async def list(self) -> list[AdminUser]:
        return await self._users.list()

    async def update(
        self, user_id: int, *, role: Role | None = None, password: str | None = None
    ) -> AdminUser:
        """Raises ``AdminUserNotFound``, ``AdminUserInvalid`` or ``LastAdminError``."""
        user = await self._users.get(user_id)
        if user is None:
            raise AdminUserNotFound(f"admin user {user_id} not found")
        demoting = role is not None and role is not Role.ADMIN and user.role is Role.ADMIN
        if demoting and await self._users.count_admins() <= 1:
            raise LastAdminError("the last administrator cannot be demoted")
        password_hash = None
        if password is not None:
            validate_password(password)
            password_hash = await asyncio.to_thread(self._hasher.hash, password)
        updated = await self._users.update(user_id, role=role, password_hash=password_hash)
        if password_hash is not None or (role is not None and role is not user.role):
            await self._sessions.delete_for_user(user_id)
        return updated

    async def delete(self, user_id: int, *, acting_user_id: int) -> None:
        user = await self._users.get(user_id)
        if user is None:
            raise AdminUserNotFound(f"admin user {user_id} not found")
        if user_id == acting_user_id:
            raise AdminUserInvalid("you cannot delete your own account")
        if user.role is Role.ADMIN and await self._users.count_admins() <= 1:
            raise LastAdminError("the last administrator cannot be deleted")
        await self._users.delete(user_id)
