from enum import Enum

class UserRole(str, Enum):
    PHARMACY_OWNER="OWNER"
    TECHNICIAN="TECHNICIAN"
    ADMIN="ADMIN"


class OwnershipTransferStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class OtpPurpose(str, Enum):
    TRANSFER_CREATE = "TRANSFER_CREATE"
    TRANSFER_ACCEPT = "TRANSFER_ACCEPT"
