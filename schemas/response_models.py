"""
Typed response models for Swagger documentation.

Each model replaces the generic ``Response_Schema`` on specific endpoints so
that Swagger/OpenAPI shows the **exact** shape of ``data`` instead of ``Any``.
"""

from pydantic import BaseModel, Field

from schemas.audit_fields import AuditFields
from schemas.user_state_fields import UserStateFields

# ───────────────────── Data sub-models ─────────────────────


class AccessTokenData(BaseModel):
    """JWT access token returned after login or token renewal."""

    access_token: str = Field(
        ...,
        description="JWT access token. Include in the Authorization header as 'Bearer <token>'.",
        examples=["eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."],
    )


class LoginData(AuditFields, UserStateFields):
    """Data returned after successful login — token + user info."""

    refresh_token:str=Field(
        ...,
        description="JWT refresh token. Include in the Cookies.",
        examples=["eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."],
    )
    access_token: str = Field(
        ...,
        description="JWT access token. Include in the Authorization header as 'Bearer <token>'.",
        examples=["eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."],
    )
    id: int = Field(..., description="Unique user identifier.", examples=[4])
    email: str = Field(..., description="Registered email.", examples=["user2@gmail.com"])
    role: str = Field(
        ...,
        description="User role — one of OWNER, TECHNICIAN, ADMIN.",
        examples=["OWNER"],
    )


class AppLoginData(LoginData):
    """``POST /app/login`` data — login payload plus the password hash for offline login."""

    password_hash: str = Field(
        ...,
        description=(
            "Argon2id PHC hash of the user's password (salt + params embedded). "
            "Stored on-device so the app can verify the password offline."
        ),
        examples=["$argon2id$v=19$m=65536,t=3,p=4$c29tZXNhbHQ$<hash>"],
    )


class UserData(AuditFields, UserStateFields):
    """User data returned after signup, update, or profile retrieval."""

    id: int = Field(..., description="Unique user identifier.", examples=[4])
    email: str = Field(..., description="Registered email.", examples=["user2@gmail.com"])
    role: str = Field(
        ...,
        description="User role — one of OWNER, TECHNICIAN, ADMIN.",
        examples=["OWNER"],
    )


class PharmacyData(AuditFields):
    """Pharmacy data returned by CRUD endpoints."""

    id: int = Field(..., description="Unique pharmacy identifier.", examples=[2])
    name: str = Field(..., description="Pharmacy name.", examples=["Deva'sShop"])
    address: str = Field(..., description="Street address.", examples=["skfnoajnf"])
    owner: UserData | None = Field(
        None,
        description="Owner details (included for ADMIN, null for OWNER viewing own pharmacy).",
    )


# ───────────────── Auth Responses ──────────────────


class SignupResponse(BaseModel):
    """``POST /user/signup`` — creates a new PHARMACY_OWNER account."""

    status_code: int = Field(..., description="Logical HTTP status code.", examples=[201])
    message: str = Field(..., description="Result summary.", examples=["User created successfully"])
    data: UserData = Field(..., description="Newly created user profile.")

    model_config = {
        "json_schema_extra": {
            "example": {
                "status_code": 201,
                "message": "User created successfully",
                "data": {
                    "id": 4,
                    "email": "user2@gmail.com",
                    "role": "OWNER",
                },
            }
        }
    }


class LoginResponse(BaseModel):
    """``POST /user/login`` — authenticates and returns a JWT access token with user info."""

    status_code: int = Field(..., description="Logical HTTP status code.", examples=[200])
    message: str = Field(..., description="Result summary.", examples=["Login successful"])
    data: LoginData = Field(
        ..., description="Object containing the JWT access token and user info."
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "status_code": 200,
                "message": "Login successful",
                "data": {
                    "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VybmFtZSI6InVzZXIyIiwidXNlcl9pZCI6NCwiZXhwaXJlIjoxNzQzOTM2MDAwfQ.xxxxx",
                    "id": 4,
                    "email": "user2@gmail.com",
                    "role": "OWNER",
                },
            }
        }
    }


class AppLoginResponse(BaseModel):
    """``POST /app/login`` — like login, but also returns the password hash for offline login."""

    status_code: int = Field(..., description="Logical HTTP status code.", examples=[200])
    message: str = Field(..., description="Result summary.", examples=["Login successful"])
    data: AppLoginData = Field(
        ..., description="Login payload plus the Argon2id password hash for on-device offline login."
    )


class ImpersonationData(AuditFields, UserStateFields):
    """Data returned when an ADMIN mints an impersonation token for another user."""

    access_token: str = Field(
        ...,
        description="JWT access token scoped to the impersonated user.",
        examples=["eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."],
    )
    id: int = Field(..., description="ID of the impersonated user.", examples=[4])
    email: str = Field(..., description="Email of the impersonated user.", examples=["user2@gmail.com"])
    role: str = Field(..., description="Role of the impersonated user.", examples=["OWNER"])
    medical_store_id: int | None = Field(
        None, description="Pre-selected pharmacy ID for the session, if provided.", examples=[2]
    )


class ImpersonationResponse(BaseModel):
    """``POST /user/impersonate`` — issues an access token for another user (Admin only)."""

    status_code: int = Field(..., description="Logical HTTP status code.", examples=[200])
    message: str = Field(..., description="Result summary.", examples=["Impersonation token issued"])
    data: ImpersonationData = Field(..., description="Impersonation token and target user info.")

    model_config = {
        "json_schema_extra": {
            "example": {
                "status_code": 200,
                "message": "Impersonation token issued",
                "data": {
                    "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                    "id": 4,
                    "email": "user2@gmail.com",
                    "role": "OWNER",
                    "medical_store_id": 2,
                },
            }
        }
    }


class TokenRenewResponse(BaseModel):
    """``GET /user/renew-access-token`` — issues a new access token from the refresh cookie."""

    status_code: int = Field(..., description="Logical HTTP status code.", examples=[200])
    message: str = Field(
        ..., description="Result summary.", examples=["Token renewed successfully"]
    )
    data: AccessTokenData = Field(..., description="Object containing the new JWT access token.")

    model_config = {
        "json_schema_extra": {
            "example": {
                "status_code": 200,
                "message": "Token renewed successfully",
                "data": {
                    "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VybmFtZSI6InVzZXIyIiwidXNlcl9pZCI6NCwiZXhwaXJlIjoxNzQzOTM2MDAwfQ.yyyyy",
                },
            }
        }
    }


# ───────────────── User Responses ──────────────────


class UserProfileResponse(BaseModel):
    """``GET /user/me`` — returns the authenticated user's profile."""

    status_code: int = Field(..., description="Logical HTTP status code.", examples=[200])
    message: str = Field(
        ..., description="Result summary.", examples=["Profile retrieved successfully"]
    )
    data: UserData = Field(..., description="User profile object.")

    model_config = {
        "json_schema_extra": {
            "example": {
                "status_code": 200,
                "message": "Profile retrieved successfully",
                "data": {
                    "id": 4,
                    "email": "user2@gmail.com",
                    "role": "OWNER",
                },
            }
        }
    }


class UserUpdateResponse(BaseModel):
    """Response for ``PUT /user/update/me`` or ``PUT /user/update/{user_id}``."""

    status_code: int = Field(..., description="Logical HTTP status code.", examples=[200])
    message: str = Field(..., description="Result summary.", examples=["User updated successfully"])
    data: UserData = Field(..., description="Updated user profile.")

    model_config = {
        "json_schema_extra": {
            "example": {
                "status_code": 200,
                "message": "User updated successfully",
                "data": {
                    "id": 4,
                    "email": "updated_user2@gmail.com",
                    "role": "OWNER",
                },
            }
        }
    }


class UserDeleteResponse(BaseModel):
    """Response for ``DELETE /user/delete/me`` or ``DELETE /user/delete/{user_id}``."""

    status_code: int = Field(..., description="Logical HTTP status code.", examples=[200])
    message: str = Field(..., description="Result summary.", examples=["User deleted successfully"])
    data: str | None = Field(None, description="Always null on successful deletion.")

    model_config = {
        "json_schema_extra": {
            "example": {
                "status_code": 200,
                "message": "User deleted successfully",
                "data": None,
            }
        }
    }


class TechnicianCreateResponse(BaseModel):
    """``POST /user/create-technician`` — creates a technician linked to a pharmacy."""

    status_code: int = Field(..., description="Logical HTTP status code.", examples=[201])
    message: str = Field(
        ..., description="Result summary.", examples=["Technician created successfully"]
    )
    data: UserData = Field(..., description="Newly created technician profile.")

    model_config = {
        "json_schema_extra": {
            "example": {
                "status_code": 201,
                "message": "Technician created successfully",
                "data": {
                    "id": 12,
                    "email": "User2Tech@gmail.com",
                    "role": "TECHNICIAN",
                },
            }
        }
    }


class TechnicianListResponse(BaseModel):
    """``POST /user/get-technician`` — lists technicians for a pharmacy."""

    status_code: int = Field(..., description="Logical HTTP status code.", examples=[200])
    message: str = Field(
        ..., description="Result summary.", examples=["Technicians retrieved successfully"]
    )
    data: list[UserData] = Field(..., description="Array of technician profiles.")

    model_config = {
        "json_schema_extra": {
            "example": {
                "status_code": 200,
                "message": "Technicians retrieved successfully",
                "data": [
                    {
                        "id": 9,
                        "email": "Every time add new email because of it is unique",
                        "role": "TECHNICIAN",
                    },
                    {
                        "id": 12,
                        "email": "User2Tech@gmail.com",
                        "role": "TECHNICIAN",
                    },
                ],
            }
        }
    }


# ────────────── Admin User Responses ───────────────


class UserListResponse(BaseModel):
    """``GET /user/all`` — returns all registered users (Admin only)."""

    status_code: int = Field(..., description="Logical HTTP status code.", examples=[200])
    message: str = Field(
        ..., description="Result summary.", examples=["Users retrieved successfully"]
    )
    data: list[UserData] = Field(..., description="Array of all user profiles.")

    model_config = {
        "json_schema_extra": {
            "example": {
                "status_code": 200,
                "message": "Users retrieved successfully",
                "data": [
                    {
                        "id": 4,
                        "email": "user2@gmail.com",
                        "role": "OWNER",
                    },
                    {
                        "id": 6,
                        "email": "admin@gmail.com",
                        "role": "ADMIN",
                    },
                    {
                        "id": 12,
                        "email": "User2Tech@gmail.com",
                        "role": "TECHNICIAN",
                    },
                ],
            }
        }
    }


class UserByEmailResponse(BaseModel):
    """``GET /user/by-email`` — finds a user by email address (Admin only)."""

    status_code: int = Field(..., description="Logical HTTP status code.", examples=[200])
    message: str = Field(
        ..., description="Result summary.", examples=["User retrieved successfully"]
    )
    data: UserData = Field(..., description="Matching user profile.")

    model_config = {
        "json_schema_extra": {
            "example": {
                "status_code": 200,
                "message": "User retrieved successfully",
                "data": {
                    "id": 4,
                    "email": "user2@gmail.com",
                    "role": "OWNER",
                },
            }
        }
    }


class UsersByRoleResponse(BaseModel):
    """``GET /user/by-role`` — lists users filtered by role (Admin only)."""

    status_code: int = Field(..., description="Logical HTTP status code.", examples=[200])
    message: str = Field(
        ..., description="Result summary.", examples=["Users retrieved successfully"]
    )
    data: list[UserData] = Field(
        ..., description="Array of user profiles matching the requested role."
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "status_code": 200,
                "message": "Users retrieved successfully",
                "data": [
                    {
                        "id": 4,
                        "email": "user2@gmail.com",
                        "role": "OWNER",
                    },
                    {
                        "id": 7,
                        "email": "tech@gmail.com",
                        "role": "OWNER",
                    },
                ],
            }
        }
    }


# ────────────── Pharmacy Responses ─────────────────


class PharmacyCreateResponse(BaseModel):
    """``POST /pharmacy/create-pharmacy`` — creates a new pharmacy."""

    status_code: int = Field(..., description="Logical HTTP status code.", examples=[201])
    message: str = Field(
        ..., description="Result summary.", examples=["Pharmacy created successfully"]
    )
    data: PharmacyData = Field(..., description="Newly created pharmacy object.")

    model_config = {
        "json_schema_extra": {
            "example": {
                "status_code": 201,
                "message": "Pharmacy created successfully",
                "data": {
                    "id": 2,
                    "name": "Deva'sShop",
                    "address": "skfnoajnf",
                    "owner": {
                        "id": 4,
                        "email": "user2@gmail.com",
                        "role": "OWNER",
                    },
                },
            }
        }
    }


class PharmacyListResponse(BaseModel):
    """Response for pharmacy list / search endpoints."""

    status_code: int = Field(..., description="Logical HTTP status code.", examples=[200])
    message: str = Field(
        ..., description="Result summary.", examples=["Pharmacy retrieved successfully"]
    )
    data: list[PharmacyData] = Field(..., description="Array of pharmacy objects.")

    model_config = {
        "json_schema_extra": {
            "example": {
                "status_code": 200,
                "message": "Pharmacy retrieved successfully",
                "data": [
                    {
                        "id": 2,
                        "name": "Deva'sShop",
                        "address": "skfnoajnf",
                        "owner": {
                            "id": 4,
                            "email": "user2@gmail.com",
                            "role": "OWNER",
                        },
                    },
                    {
                        "id": 9,
                        "name": "Enter Your pharmacy name",
                        "address": "Dummy address",
                        "owner": {
                            "id": 7,
                            "email": "tech@gmail.com",
                            "role": "OWNER",
                        },
                    },
                ],
            }
        }
    }


class PharmacyUpdateResponse(BaseModel):
    """``PUT /pharmacy/update/{ph_id}`` — updates pharmacy details."""

    status_code: int = Field(..., description="Logical HTTP status code.", examples=[200])
    message: str = Field(
        ..., description="Result summary.", examples=["Pharmacy updated successfully"]
    )
    data: PharmacyData = Field(..., description="Updated pharmacy object.")

    model_config = {
        "json_schema_extra": {
            "example": {
                "status_code": 200,
                "message": "Pharmacy updated successfully",
                "data": {
                    "id": 2,
                    "name": "Deva's Health Hub",
                    "address": "456 Wellness Ave, Pune",
                    "owner": {
                        "id": 4,
                        "email": "user2@gmail.com",
                        "role": "OWNER",
                    },
                },
            }
        }
    }


class PharmacyDeleteResponse(BaseModel):
    """``DELETE /pharmacy/delete/{ph_id}`` — deletes a pharmacy."""

    status_code: int = Field(..., description="Logical HTTP status code.", examples=[200])
    message: str = Field(
        ..., description="Result summary.", examples=["Pharmacy deleted successfully"]
    )
    data: str | None = Field(None, description="Always null on successful deletion.")

    model_config = {
        "json_schema_extra": {
            "example": {
                "status_code": 200,
                "message": "Pharmacy deleted successfully",
                "data": None,
            }
        }
    }
