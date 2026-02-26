from sqlalchemy import String, Integer, Boolean, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from database import Base


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
        autoincrement=True
    )

    owner_id: Mapped[int] = mapped_column(
        ForeignKey(
            "pharmacy_owner.owner_id",
            ondelete="CASCADE",
            onupdate="CASCADE"
        ),
        nullable=False
    )

    token: Mapped[str] = mapped_column(String(255))

    revoked: Mapped[bool] = mapped_column(Boolean, default=False)

    # Relationship
    pharmacy_owner = relationship(
        "Pharmacy_Owner",
        back_populates="refresh_tokens"
    )