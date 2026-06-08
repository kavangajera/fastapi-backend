from enum import Enum

class UserRole(str, Enum): # Just for example
    PHARMACY_OWNER="OWNER"
    TECHNICIAN="TECHNICIAN"
    ADMIN="ADMIN"


class DocumentStatus(str, Enum):
    UPLOADED = "UPLOADED"
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    RETRYING = "RETRYING"
    FAILED_PERMANENTLY = "FAILED_PERMANENTLY"


class DocumentType(str, Enum):
    PDF = "pdf"
    IMAGE = "image"
    CSV = "csv"