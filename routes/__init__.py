from fastapi import APIRouter
from .user import create_user, create_technician
from .user import login_user
from .user import renew_access_token
from .user import get_technicians
from .user import update_user, delete_user
from .user import update_me, delete_me
from .user import get_all_users, get_user_by_email, get_users_by_role, get_my_profile

from .pharmacy import create_pharmacy, get_pharmacy_by_owner_id
from .pharmacy import get_pharmacy
from .pharmacy import update_pharmacy, delete_pharmacy, get_pharmacy_by_name

router = APIRouter()


# ================= USER ROUTES =================
router.add_api_route('/user/signup', endpoint=create_user, methods=["POST"])
router.add_api_route('/user/login', endpoint=login_user, methods=["POST"])
router.add_api_route('/user/renew-access-token', endpoint=renew_access_token, methods=["GET"])
router.add_api_route('/user/create-technician', endpoint=create_technician, methods=["POST"])
router.add_api_route('/user/get-technician', endpoint=get_technicians, methods=["POST"])
router.add_api_route('/user/me', endpoint=get_my_profile, methods=["GET"])

# /me routes MUST be before /{user_id} routes to avoid path conflicts
router.add_api_route('/user/update/me', endpoint=update_me, methods=["PUT"])
router.add_api_route('/user/delete/me', endpoint=delete_me, methods=["DELETE"])

router.add_api_route('/user/all', endpoint=get_all_users, methods=["GET"])
router.add_api_route('/user/by-email', endpoint=get_user_by_email, methods=["GET"])
router.add_api_route('/user/by-role', endpoint=get_users_by_role, methods=["GET"])
router.add_api_route('/user/update/{user_id}', endpoint=update_user, methods=["PUT"])
router.add_api_route('/user/delete/{user_id}', endpoint=delete_user, methods=["DELETE"])

# ================= PHARMACY ROUTES =================
router.add_api_route('/pharmacy/create-pharmacy', endpoint=create_pharmacy, methods=["POST"])
router.add_api_route('/pharmacy/get-pharmacy', endpoint=get_pharmacy, methods=["GET"])
router.add_api_route('/pharmacy/get-pharmacy-by-owner', endpoint=get_pharmacy_by_owner_id, methods=["GET"])
router.add_api_route('/pharmacy/by-name', endpoint=get_pharmacy_by_name, methods=["GET"])
router.add_api_route('/pharmacy/update/{ph_id}', endpoint=update_pharmacy, methods=["PUT"])
router.add_api_route('/pharmacy/delete/{ph_id}', endpoint=delete_pharmacy, methods=["DELETE"])
