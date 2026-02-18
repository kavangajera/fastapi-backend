from fastapi import APIRouter
from .pharmacy_owner import create_pharmacy_owner
from .pharmacy_owner import login_pharmacy_owner
router=APIRouter()


router.add_api_route('/signup/owner',endpoint=create_pharmacy_owner,methods=["POST"])
router.add_api_route('/login/owner',endpoint=login_pharmacy_owner,methods=["POST"])