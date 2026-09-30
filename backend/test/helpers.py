from unittest.mock import AsyncMock, MagicMock


def async_cm(value):
    """Async context manager yielding ``value``."""
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=value)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def scalar_result(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    result.scalar_one.return_value = value
    return result


def scalars_result(items):
    result = MagicMock()
    result.scalars.return_value.all.return_value = items
    return result
