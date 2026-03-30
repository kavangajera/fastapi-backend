from enum import Enum

class UserRole(str, Enum): # Just for example
    PHARMACY_OWNER="OWNER"
    TECHNICIAN="TECHNICIAN"
    ADMIN="ADMIN"