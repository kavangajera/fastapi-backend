from fastapi import APIRouter
from .user import create_pharmacy_owner
from .user import login_pharmacy_owner
from .user import renew_access_token
from .pharmacy import create_pharmacy, get_pharmacy_by_owner_id
from .pharmacy import get_pharmacy
router=APIRouter()


router.add_api_route('/signup/user',endpoint=create_pharmacy_owner,methods=["POST"])
router.add_api_route('/login/user',endpoint=login_pharmacy_owner,methods=["POST"])
router.add_api_route('/renew-access-token',endpoint=renew_access_token,methods=["GET"])
router.add_api_route('/create-pharmacy',endpoint=create_pharmacy,methods=["POST"])
router.add_api_route('/get-pharmacy',endpoint=get_pharmacy,methods=["GET"])
router.add_api_route('/get-pharmacy-by-owner',endpoint=get_pharmacy_by_owner_id,methods=["GET"])