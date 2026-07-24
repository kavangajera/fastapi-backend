from enum import Enum


class UserRole(str, Enum):  # Just for example
    PHARMACY_OWNER = "OWNER"
    TECHNICIAN = "TECHNICIAN"
    ADMIN = "ADMIN"


class OtpPurpose(str, Enum):
    """What a one-time code was issued for.

    An OTP is only ever accepted for the exact purpose (and scope) it was
    issued under, so a code mailed for a password reset can never be
    replayed against an ownership transfer.
    """

    PASSWORD_RESET = "PASSWORD_RESET"
    TRANSFER_CREATE = "TRANSFER_CREATE"  # sent to the CURRENT owner
    TRANSFER_ACCEPT = "TRANSFER_ACCEPT"  # sent to the NEW owner


class OwnershipTransferStatus(str, Enum):
    """Lifecycle of a pharmacy ownership-transfer request.

    PENDING is the only actionable state. EXPIRED is applied lazily on read
    once ``expires_at`` has passed — there is no background sweeper.
    """

    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"  # withdrawn by the current owner
    EXPIRED = "EXPIRED"


class PlanCode(str, Enum):
    """Subscription plan tiers (QueueRx Pricing Reference v2).

    Additive: every feature in a lower tier is included in the tiers above it.
    """

    BASIC = "BASIC"          # $29/mo  — compliance + inventory fundamentals
    ADVANCED = "ADVANCED"    # $179/mo — Basic + invoice automation + billing analytics
    ULTIMATE = "ULTIMATE"    # $349/mo — full platform, unlimited dispensary intelligence


class SubscriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"    # admin-revoked / owner-cancelled
    
class PaymentStatus(str, Enum):
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    REFUNDED = "REFUNDED"


class Feature(str, Enum):
    """Canonical entitlement flag keys (QueueRx v2 developer contract).

    Values are the stable snake_case keys the frontend and API guards check
    against. Which plan grants which flag is stored per-plan in
    ``Plan.features`` (a DB JSON column), so entitlements are admin-editable at
    runtime. The min-plan noted per flag is the lowest tier that grants it; it
    stays granted for every tier above.

    NOTE: the drug-reconciliation cap is NOT a boolean flag — it lives in
    ``Plan.limits`` as ``drug_reconciliation_limit`` / ``drugs_reconciled``
    (250 for Basic & Advanced, unlimited for Ultimate).
    """

    # ── Basic (min plan: BASIC) ─────────────────────────────────────────
    TEMP_MONITORING_ALERTS = "temp_monitoring_alerts"
    COMPLIANCE_REPORTS = "compliance_reports"
    INVENTORY_LITE = "inventory_lite"
    INVOICE_UPLOAD_MANUAL = "invoice_upload_manual"
    EXPIRATION_LOT_TRACKING = "expiration_lot_tracking"
    OVERSTOCK_MONITORING = "overstock_monitoring"
    MULTI_LOCATION_ACCESS = "multi_location_access"

    # ── Advanced (min plan: ADVANCED) ───────────────────────────────────
    INVOICE_TO_INVENTORY_AUTO = "invoice_to_inventory_auto"
    INVENTORY_RECONCILIATION_AUTO = "inventory_reconciliation_auto"
    TOP_QUANTITY_DRUG_REPORT = "top_quantity_drug_report"
    INSURANCE_NDC_ANALYTICS = "insurance_ndc_analytics"
    PACK_SIZE_BILLED_RECONCILIATION = "pack_size_billed_reconciliation"
    CUSTOM_PATIENT_MED_REPORTS = "custom_patient_med_reports"
    REFILL_ANALYSIS_BILLINGS = "refill_analysis_billings"

    # ── Ultimate (min plan: ULTIMATE) ───────────────────────────────────
    NDC_CLAIM_MISMATCH_CHECKS = "ndc_claim_mismatch_checks"
    DAYS_SUPPLY_VALIDATION = "days_supply_validation"
    DISCONTINUED_DRUG_DETECTION = "discontinued_drug_detection"
    INVOICE_BILLED_CROSS_RECONCILIATION = "invoice_billed_cross_reconciliation"
    ANNUAL_CHECKUP_AUDIT = "annual_checkup_audit"
    EARLY_ACCESS_FEATURES = "early_access_features"


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
