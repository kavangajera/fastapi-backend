from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.enums import OwnershipTransferStatus
from database import Base


class OwnershipTransferRequest(Base):
    __tablename__ = "pharmacy_ownership_transfer"

    transfer_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, index=True, autoincrement=True
    )
    pharmacy_id: Mapped[int] = mapped_column(
        ForeignKey("pharmacy.pharmacy_id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
    )
    current_owner_id: Mapped[int] = mapped_column(
        ForeignKey("user.user_id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
    )
    new_owner_id: Mapped[int] = mapped_column(
        ForeignKey("user.user_id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
    )
    status: Mapped[OwnershipTransferStatus] = mapped_column(
        Enum(OwnershipTransferStatus, name="ownershiptransferstatus"),
        default=OwnershipTransferStatus.ACTIVE,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    rejected_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    pharmacy = relationship("Pharmacy", foreign_keys=[pharmacy_id])
    current_owner = relationship("User", foreign_keys=[current_owner_id])
    new_owner = relationship("User", foreign_keys=[new_owner_id])
