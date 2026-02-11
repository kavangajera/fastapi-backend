from enum import Enum

class UserRole(str, Enum): # Just for example
    DOCTOR = "ADMIN"
    PATIENT = "USER"