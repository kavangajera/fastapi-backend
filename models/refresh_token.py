from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.async_db import AuditMixin, Base


class RefreshToken(AuditMixin, Base):
    __tablename__ = "refresh_tokens"

    refresh_token_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, index=True, autoincrement=True
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("user.user_id", ondelete="CASCADE", onupdate="CASCADE"), nullable=False
    )

    token: Mapped[str] = mapped_column(String(255))

    revoked: Mapped[bool] = mapped_column(Boolean, default=False)

    # Relationship
    user = relationship("User", back_populates="refresh_tokens")
