import pytest

from conector_odoo.infrastructure.odoo.retry import is_idempotent, run_with_retry


@pytest.mark.parametrize(
    "method",
    ["search", "search_read", "read", "search_count", "fields_get", "name_search", "version"],
)
def test_read_methods_are_idempotent(method: str) -> None:
    assert is_idempotent(method)


@pytest.mark.parametrize(
    "method", ["create", "write", "unlink", "copy", "action_confirm", "something_new"]
)
def test_other_methods_are_not_idempotent(method: str) -> None:
    assert not is_idempotent(method)


async def test_run_with_retry_uses_exponential_backoff() -> None:
    sleeps: list[float] = []
    attempts = 0

    async def sleep(delay: float) -> None:
        sleeps.append(delay)

    async def flaky() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise ConnectionError("down")
        return "ok"

    result = await run_with_retry(
        flaky,
        idempotent=True,
        max_retries=3,
        retry_on=(ConnectionError,),
        sleep=sleep,
        base_delay=0.5,
        description="search_read",
    )
    assert result == "ok"
    assert sleeps == [0.5, 1.0]


async def test_run_with_retry_never_retries_non_idempotent() -> None:
    attempts = 0

    async def sleep(delay: float) -> None:
        raise AssertionError("must not sleep")

    async def failing() -> None:
        nonlocal attempts
        attempts += 1
        raise ConnectionError("down")

    with pytest.raises(ConnectionError):
        await run_with_retry(
            failing,
            idempotent=False,
            max_retries=3,
            retry_on=(ConnectionError,),
            sleep=sleep,
            base_delay=0.1,
            description="create",
        )
    assert attempts == 1
