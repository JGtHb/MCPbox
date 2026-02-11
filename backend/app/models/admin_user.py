"""Admin user model for authentication."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class AdminUser(BaseModel):
    """Admin user for web UI authentication.

    Stores username and hashed password for JWT-based authentication.
    The password_version field is used to invalidate all tokens when
    the password is changed.
    """

    __tablename__ = "admin_users"

    username: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Increment on password change to invalidate all existing tokens
    password_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # Tracking
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<AdminUser {self.username}>"
