from fastapi import APIRouter

from schemas.response_models import (
    AppLoginResponse,
    ImpersonationResponse,
    LoginResponse,
    PharmacyCreateResponse,
    PharmacyDeleteResponse,
    PharmacyListResponse,
    PharmacyUpdateResponse,
    SignupResponse,
    TechnicianCreateResponse,
    TechnicianListResponse,
    TokenRenewResponse,
    UserByEmailResponse,
    UserDeleteResponse,
    UserListResponse,
    UserProfileResponse,
    UsersByRoleResponse,
    UserUpdateResponse,
)
from schemas.response_schema import Response_Schema

from .pharmacy import (
    create_pharmacy,
    delete_pharmacy,
    get_pharmacy,
    get_pharmacy_by_name,
    get_pharmacy_by_owner_id,
    update_pharmacy,
)
from .user import (
    app_login_user,
    create_technician,
    create_user,
    delete_me,
    delete_user,
    get_all_users,
    get_my_profile,
    get_technicians,
    get_user_by_email,
    get_users_by_role,
    impersonate_user,
    login_user,
    logout_user,
    renew_access_token,
    update_me,
    update_user,
)

router = APIRouter()


# ================= AUTH ROUTES =================

router.add_api_route(
    "/user/signup",
    endpoint=create_user,
    methods=["POST"],
    tags=["Auth"],
    summary="Register a new user account",
    description=(
        "Creates a new **PHARMACY_OWNER** account with the provided credentials.\n\n"
        "**No authentication required.**\n\n"
        "- Emails must be unique — duplicate emails are rejected with a 500 error.\n"
        "- The password is hashed server-side with Argon2 before storage.\n"
        "- After signup, call `POST /user/login` to obtain an access token."
    ),
    response_model=SignupResponse,
    operation_id="create_user",
)

router.add_api_route(
    "/user/login",
    endpoint=login_user,
    methods=["POST"],
    tags=["Auth"],
    summary="Authenticate and receive access token",
    description=(
        "Validates email and password, then returns a **JWT access token**.\n\n"
        "**No authentication required.**\n\n"
        "- A `refresh_token` is also set as an **httpOnly cookie** (used by the "
        "`/user/renew-access-token` endpoint).\n"
        "- Include the access token in subsequent requests via the "
        "`Authorization: Bearer <token>` header."
    ),
    response_model=LoginResponse,
    operation_id="login_user",
)

router.add_api_route(
    "/app/login",
    endpoint=app_login_user,
    methods=["POST"],
    tags=["Auth"],
    summary="App login — returns the password hash for offline login",
    description=(
        "Same as `POST /user/login`, but the response **also includes the stored "
        "Argon2id password hash** (`data.password_hash`).\n\n"
        "**No authentication required.**\n\n"
        "Intended for the mobile app's **offline login**: the app stores the hash "
        "on-device and verifies the password locally with Argon2id when there is no "
        "network. The hash is self-describing (salt + parameters are embedded in the "
        "PHC string), so no server secret is needed to verify it.\n\n"
        "⚠️ Returns a password hash — serve only over HTTPS and store it encrypted "
        "on the device."
    ),
    response_model=AppLoginResponse,
    operation_id="app_login_user",
)

router.add_api_route(
    "/user/renew-access-token",
    endpoint=renew_access_token,
    methods=["GET"],
    tags=["Auth"],
    summary="Renew access token via refresh cookie",
    description=(
        "Issues a **new access token** using the `refresh_token` cookie that was set "
        "during login.\n\n"
        "**No Bearer token required** — the refresh token is read automatically from "
        "the httpOnly cookie.\n\n"
        "- Returns `401` if the refresh token is missing, invalid, or expired."
    ),
    response_model=TokenRenewResponse,
    operation_id="renew_access_token",
)

router.add_api_route(
    "/user/logout",
    endpoint=logout_user,
    methods=["POST"],
    tags=["Auth"],
    summary="Log out the current user",
    description=(
        "Marks the authenticated user as logged out by setting their "
        "`IsLogout` flag to `1`.\n\n"
        "🔒 **Requires Bearer token.** Works for all roles."
    ),
    response_model=Response_Schema,
    operation_id="logout_user",
)


router.add_api_route(
    "/user/impersonate",
    endpoint=impersonate_user,
    methods=["POST"],
    tags=["Admin"],
    summary="Issue an impersonation token for another user",
    description=(
        "Mints a JWT access token scoped to **another user** so a Super Admin can view "
        "the QueueRx app as that user.\n\n"
        "🔒 **Requires Bearer token.** 🛡️ **ADMIN only** — returns 403 for other roles.\n\n"
        "- Optionally pass `medical_store_id` to pre-select one of the target user's "
        "pharmacies; it is validated to belong to the target user.\n"
        "- The token is longer-lived than a normal login token but still expires; no "
        "refresh cookie is issued."
    ),
    response_model=ImpersonationResponse,
    operation_id="impersonate_user",
)


# ================= USER ROUTES =================

router.add_api_route(
    "/user/create-technician",
    endpoint=create_technician,
    methods=["POST"],
    tags=["User"],
    summary="Create a technician for a pharmacy",
    description=(
        "Creates a new **TECHNICIAN** user linked to an existing pharmacy.\n\n"
        "🔒 **Requires Bearer token.**\n\n"
        "| Caller Role | Behaviour |\n"
        "|-------------|----------|\n"
        "| **OWNER** | Can create technicians **only** for pharmacies they own. |\n"
        "| **ADMIN** | Can create technicians for any pharmacy. |\n"
        "| **TECHNICIAN** | ❌ Forbidden (403). |"
    ),
    response_model=TechnicianCreateResponse,
    operation_id="create_technician",
)

router.add_api_route(
    "/user/get-technician",
    endpoint=get_technicians,
    methods=["POST"],
    tags=["User"],
    summary="List technicians for a pharmacy",
    description=(
        "Returns a list of technician users, optionally filtered by pharmacy ID.\n\n"
        "🔒 **Requires Bearer token.**\n\n"
        "| Caller Role | Behaviour |\n"
        "|-------------|----------|\n"
        "| **OWNER** | Sees technicians of **own pharmacies only**. |\n"
        "| **ADMIN** | Sees all technicians, optionally filtered by `ph_id`. |\n"
        "| **TECHNICIAN** | ❌ Forbidden (403). |"
    ),
    response_model=TechnicianListResponse,
    operation_id="get_technicians",
)

router.add_api_route(
    "/user/me",
    endpoint=get_my_profile,
    methods=["GET"],
    tags=["User"],
    summary="Get the current authenticated user profile",
    description=(
        "Returns the full profile of the **currently authenticated user**.\n\n"
        "🔒 **Requires Bearer token.** Works for all roles."
    ),
    response_model=UserProfileResponse,
    operation_id="get_my_profile",
)

# /me routes MUST be before /{user_id} routes to avoid path conflicts
router.add_api_route(
    "/user/update/me",
    endpoint=update_me,
    methods=["PUT"],
    tags=["User"],
    summary="Update the current user profile",
    description=(
        "Updates profile fields of the **currently authenticated user**.\n\n"
        "🔒 **Requires Bearer token.** Works for all roles.\n\n"
        "Send only the fields you want to change — omitted fields keep their "
        "current values (partial update)."
    ),
    response_model=UserUpdateResponse,
    operation_id="update_me",
)

router.add_api_route(
    "/user/delete/me",
    endpoint=delete_me,
    methods=["DELETE"],
    tags=["User"],
    summary="Delete the current user account",
    description=(
        "**Permanently deletes** the account of the currently authenticated user.\n\n"
        "🔒 **Requires Bearer token.** Works for all roles.\n\n"
        "⚠️ This action is **irreversible** — all associated data will be removed."
    ),
    response_model=UserDeleteResponse,
    operation_id="delete_me",
)

router.add_api_route(
    "/user/update/{user_id}",
    endpoint=update_user,
    methods=["PUT"],
    tags=["User"],
    summary="Update a user by ID",
    description=(
        "Updates the profile of the user identified by `user_id`.\n\n"
        "🔒 **Requires Bearer token.**\n\n"
        "| Caller Role | Behaviour |\n"
        "|-------------|----------|\n"
        "| **OWNER** | Can update self or technicians of own pharmacies. |\n"
        "| **ADMIN** | Can update any user. |\n"
        "| **TECHNICIAN** | ❌ Must use `/user/update/me` instead. |"
    ),
    response_model=UserUpdateResponse,
    operation_id="update_user",
)

router.add_api_route(
    "/user/delete/{user_id}",
    endpoint=delete_user,
    methods=["DELETE"],
    tags=["User"],
    summary="Delete a user by ID",
    description=(
        "**Permanently deletes** the user identified by `user_id`.\n\n"
        "🔒 **Requires Bearer token.**\n\n"
        "| Caller Role | Behaviour |\n"
        "|-------------|----------|\n"
        "| **OWNER** | Can delete self or technicians of own pharmacies. |\n"
        "| **ADMIN** | Can delete any user. |\n"
        "| **TECHNICIAN** | ❌ Must use `/user/delete/me` instead. |"
    ),
    response_model=UserDeleteResponse,
    operation_id="delete_user",
)


# ================= ADMIN ROUTES =================

router.add_api_route(
    "/user/all",
    endpoint=get_all_users,
    methods=["GET"],
    tags=["Admin"],
    summary="List all registered users",
    description=(
        "Returns a list of **every user** in the system.\n\n"
        "🔒 **Requires Bearer token.** 🛡️ **ADMIN only** — returns 403 for other roles."
    ),
    response_model=UserListResponse,
    operation_id="get_all_users",
)

router.add_api_route(
    "/user/by-email",
    endpoint=get_user_by_email,
    methods=["GET"],
    tags=["Admin"],
    summary="Find a user by email address",
    description=(
        "Retrieves a single user matching the provided `user_email` query parameter.\n\n"
        "🔒 **Requires Bearer token.** 🛡️ **ADMIN only** — returns 403 for other roles.\n\n"
        "Returns 404 if no user matches."
    ),
    response_model=UserByEmailResponse,
    operation_id="get_user_by_email",
)

router.add_api_route(
    "/user/by-role",
    endpoint=get_users_by_role,
    methods=["GET"],
    tags=["Admin"],
    summary="List users filtered by role",
    description=(
        "Returns all users matching the specified `role` query parameter.\n\n"
        "🔒 **Requires Bearer token.** 🛡️ **ADMIN only** — returns 403 for other roles.\n\n"
        "Valid role values: `OWNER`, `TECHNICIAN`, `ADMIN`."
    ),
    response_model=UsersByRoleResponse,
    operation_id="get_users_by_role",
)


# ================= PHARMACY ROUTES =================

router.add_api_route(
    "/pharmacy/create-pharmacy",
    endpoint=create_pharmacy,
    methods=["POST"],
    tags=["Pharmacy"],
    summary="Create a new pharmacy",
    description=(
        "Creates a new pharmacy **owned by the authenticated user**.\n\n"
        "🔒 **Requires Bearer token.**\n\n"
        "| Caller Role | Behaviour |\n"
        "|-------------|----------|\n"
        "| **OWNER** | Creates pharmacy for self. |\n"
        "| **ADMIN** | Creates pharmacy for self. |\n"
        "| **TECHNICIAN** | ❌ Forbidden (403). |"
    ),
    response_model=PharmacyCreateResponse,
    operation_id="create_pharmacy",
)

router.add_api_route(
    "/pharmacy/get-pharmacy",
    endpoint=get_pharmacy,
    methods=["GET"],
    tags=["Pharmacy"],
    summary="Get pharmacies for the current user",
    description=(
        "Returns pharmacies visible to the authenticated user, optionally filtered "
        "by `ph_id`.\n\n"
        "🔒 **Requires Bearer token.**\n\n"
        "| Caller Role | Behaviour |\n"
        "|-------------|----------|\n"
        "| **OWNER** | Sees only pharmacies they own (owner info hidden). |\n"
        "| **ADMIN** | Sees all pharmacies with owner info. |\n"
        "| **TECHNICIAN** | ❌ Forbidden (403). |"
    ),
    response_model=PharmacyListResponse,
    operation_id="get_pharmacy",
)

router.add_api_route(
    "/pharmacy/get-pharmacy-by-owner",
    endpoint=get_pharmacy_by_owner_id,
    methods=["GET"],
    tags=["Admin"],
    summary="Get pharmacies owned by a specific user",
    description=(
        "Returns all pharmacies owned by the user identified by `owner_id`.\n\n"
        "🔒 **Requires Bearer token.** 🛡️ **ADMIN only** — returns 403 for other roles."
    ),
    response_model=PharmacyListResponse,
    operation_id="get_pharmacy_by_owner_id",
)

router.add_api_route(
    "/pharmacy/by-name",
    endpoint=get_pharmacy_by_name,
    methods=["GET"],
    tags=["Pharmacy"],
    summary="Search pharmacies by name",
    description=(
        "Searches for pharmacies whose name **partially matches** the provided `name` "
        "query parameter (case-insensitive).\n\n"
        "🔒 **Requires Bearer token.**\n\n"
        "| Caller Role | Behaviour |\n"
        "|-------------|----------|\n"
        "| **OWNER** | Sees only their own matching pharmacies. |\n"
        "| **ADMIN** | Sees all matching pharmacies. |\n"
        "| **TECHNICIAN** | ❌ Forbidden (403). |"
    ),
    response_model=PharmacyListResponse,
    operation_id="get_pharmacy_by_name",
)

router.add_api_route(
    "/pharmacy/update/{ph_id}",
    endpoint=update_pharmacy,
    methods=["PUT"],
    tags=["Pharmacy"],
    summary="Update a pharmacy by ID",
    description=(
        "Updates the pharmacy identified by `ph_id`. Send only the fields you "
        "want to change.\n\n"
        "🔒 **Requires Bearer token.**\n\n"
        "| Caller Role | Behaviour |\n"
        "|-------------|----------|\n"
        "| **OWNER** | Can update only their own pharmacy. |\n"
        "| **ADMIN** | Can update any pharmacy. |\n"
        "| **TECHNICIAN** | ❌ Forbidden (403). |"
    ),
    response_model=PharmacyUpdateResponse,
    operation_id="update_pharmacy",
)

router.add_api_route(
    "/pharmacy/delete/{ph_id}",
    endpoint=delete_pharmacy,
    methods=["DELETE"],
    tags=["Pharmacy"],
    summary="Delete a pharmacy by ID",
    description=(
        "**Permanently deletes** the pharmacy identified by `ph_id`.\n\n"
        "🔒 **Requires Bearer token.**\n\n"
        "⚠️ This action is **irreversible** — the pharmacy and its data will be "
        "removed.\n\n"
        "| Caller Role | Behaviour |\n"
        "|-------------|----------|\n"
        "| **OWNER** | Can delete only their own pharmacy. |\n"
        "| **ADMIN** | Can delete any pharmacy. |\n"
        "| **TECHNICIAN** | ❌ Forbidden (403). |"
    ),
    response_model=PharmacyDeleteResponse,
    operation_id="delete_pharmacy",
)
