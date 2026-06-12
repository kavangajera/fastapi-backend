from enum import Enum


class UserRole(str, Enum):  # Just for example
    PHARMACY_OWNER = "OWNER"
    TECHNICIAN = "TECHNICIAN"
    ADMIN = "ADMIN"


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


class ProcessType(str, Enum):
    """
    The kind of processing a document should undergo.

    Each value maps 1:1 to a dedicated Kafka topic family
    (``<value>-processing`` / ``<value>-retry`` / ``<value>-dlq``)
    and to a dedicated worker that calls the matching service.
    """

    DISPENSE = "dispense"
    INVOICE = "invoice"
    BARCODE = "barcode"


# Allowed upload file extensions per process type.
# The unified upload endpoint validates against these.
ALLOWED_EXTENSIONS: dict[ProcessType, set[str]] = {
    ProcessType.DISPENSE: {"pdf", "docx", "doc", "xlsx", "xls"},
    ProcessType.INVOICE: {"pdf"},
    ProcessType.BARCODE: {"png", "jpg", "jpeg", "heic", "heif"},
}
