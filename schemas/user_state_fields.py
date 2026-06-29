"""
schemas/user_state_fields.py
────────────────────────────
User-only state flags, surfaced on every response that returns a user
(login, profile, technician creation, admin lists, impersonation).

Kept separate from ``AuditFields`` because these belong to the User
entity only — not to every model. ``from_attributes=True`` lets schemas
that validate a User ORM row pick them up automatically.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class UserStateFields(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    IsActive: int = 1  # 1 = active account, 0 = deactivated
    IsLogout: int = 0  # 1 = currently logged out, 0 = logged in
