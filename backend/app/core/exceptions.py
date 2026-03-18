from __future__ import annotations


class AppError(Exception):
    """Base application error."""


class NotFoundError(AppError):
    pass


class UnauthorizedError(AppError):
    pass


class BadRequestError(AppError):
    pass

