from fastapi import APIRouter
from .signup import create_user
from .login import login
router=APIRouter()


router.add_api_route('/signup',endpoint=create_user,methods=["POST"])
router.add_api_route('/login',endpoint=login,methods=["POST"])