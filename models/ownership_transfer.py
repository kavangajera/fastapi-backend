from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.async_db import AuditMixin, Base
from core.enums import OwnershipTransferStatus


class OwnershipTransferRequest(AuditMixin, Base):
    """A pending hand-over of one pharmacy from its owner to another user.

    The request is created by the current owner (OTP-confirmed) and can only
    be actioned by `new_owner_id`, who must also confirm with an OTP. The
    ownership move itself is a single field change — `Pharmacy.user_id` —
    applied atomically on accept, guarded by a re-check that the pharmacy is
    still owned by `current_owner_id`.

    `status` is a plain string column (not a native DB enum) so new states
    need no schema migration. EXPIRED is applied lazily on read.
    """

    __tablename__ = "pharmacy_ownership_transfer"

    transfer_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, index=True, autoincrement=True
    )

    medical_store_id: Mapped[int] = mapped_column(
        ForeignKey("medical_store.medical_store_id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
        index=True,
    )

    current_owner_id: Mapped[int] = mapped_column(
        ForeignKey("user.user_id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
        index=True,
    )
    new_owner_id: Mapped[int] = mapped_column(
        ForeignKey("user.user_id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
        index=True,
    )

    # core.enums.OwnershipTransferStatus (stored as its string *value*).
    status: Mapped[str] = mapped_column(
        String(20),
        default=OwnershipTransferStatus.PENDING.value,
        nullable=False,
        index=True,
    )

    # Optional free-text note from the current owner, shown to the recipient.
    message: Mapped[str | None] = mapped_column(String(500), nullable=True)

    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # lazy="selectin": these are read during response serialization on an
    # AsyncSession, where a lazy load would raise MissingGreenlet.
    pharmacy = relationship("Pharmacy", foreign_keys=[medical_store_id], lazy="selectin")
    current_owner = relationship("User", foreign_keys=[current_owner_id], lazy="selectin")
    new_owner = relationship("User", foreign_keys=[new_owner_id], lazy="selectin")
