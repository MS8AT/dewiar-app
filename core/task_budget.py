"""Чистый резерв запросов на итог; не меняет квоту и не запускает модель."""


def reserve(review=False, learning=False):
    return 1 + int(bool(review)) + int(bool(learning))


def actions(allowed, remaining, reserved):
    """В зарезервированных шагах доступны только завершение или вопрос."""
    if remaining <= reserved:
        return {name: fields for name, fields in allowed.items() if name in {"finish", "pause"}}
    return dict(allowed)
