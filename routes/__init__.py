from fastapi import APIRouter
from .pharmacy_owner import create_pharmacy_owner
from .pharmacy_owner import login_pharmacy_owner
from .pharmacy_owner import dummy_protacted_route
from .pharmacy_owner import renew_access_token
from .pharmacy import create_pharmacy

router=APIRouter()


router.add_api_route('/signup/owner',endpoint=create_pharmacy_owner,methods=["POST"])
router.add_api_route('/login/owner',endpoint=login_pharmacy_owner,methods=["POST"])
router.add_api_route('/getowner',endpoint=dummy_protacted_route,methods=["GET"])
router.add_api_route('/renew-access-token',endpoint=renew_access_token,methods=["GET"])
router.add_api_route('/create-pharmacy',endpoint=create_pharmacy,methods=["POST"])