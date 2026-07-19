from enum import StrEnum


class RunStatus(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ShopRunStatus(StrEnum):
    PENDING = "pending"
    NAVIGATING = "navigating"
    EXTRACTING_POOL = "extracting_pool"
    DISCOVERING_PRODUCTS = "discovering_products"
    PROCESSING_PRODUCTS = "processing_products"
    PAUSED = "paused"
    MANUAL_ACTION_REQUIRED = "manual_action_required"
    COMPLETED = "completed"
    FAILED = "failed"


class ProductRunStatus(StrEnum):
    PENDING = "pending"
    PREPARING_SCREEN_IMAGE = "preparing_screen_image"
    SEARCHING_LISTING_IMAGE = "searching_listing_image"
    SCREENED_QUALIFIED = "screened_qualified"
    EXTRACTING_DETAIL = "extracting_detail"
    SEARCHING_DETAIL_IMAGE = "searching_detail_image"
    ARCHIVING = "archiving"
    QUALIFIED = "qualified"
    REJECTED = "rejected"
    REVIEW = "review"
    FAILED = "failed"
    SKIPPED_CATEGORY_QUOTA_REACHED = "skipped_category_quota_reached"
    SKIPPED_AFTER_SHOP_REJECTED = "skipped_after_shop_rejected"


class PageKind(StrEnum):
    SHOP_HOME = "shop_home"
    PRODUCT_LISTING = "product_listing"
    PRODUCT_DETAIL = "product_detail"
    LOGIN = "login"
    VERIFICATION = "verification"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


class ProductVerdict(StrEnum):
    EXACT_EXTERNAL_IMAGE_MATCH = "exact_external_image_match"
    FULL_IMAGE_UNMAPPED = "full_image_unmapped"
    PARTIAL_EXTERNAL_IMAGE_MATCH = "partial_external_image_match"
    NO_INDEXED_MATCH_FOUND = "no_indexed_match_found"
    SEARCH_ERROR = "search_error"
    MANUAL_REVIEW = "manual_review"


class ShopDecision(StrEnum):
    CANDIDATE = "candidate"
    REJECTED = "rejected"
    REVIEW = "review"
    INSUFFICIENT_DATA = "insufficient_data"
    FAILED = "failed"


class EvidenceKind(StrEnum):
    LOCAL_SHA256_MATCH = "local_sha256_match"
    FULL_MATCH_PAGE = "full_match_page"
    FULL_MATCH_IMAGE = "full_match_image"
    PARTIAL_MATCH_PAGE = "partial_match_page"
    PARTIAL_MATCH_IMAGE = "partial_match_image"
    VISUALLY_SIMILAR_IMAGE = "visually_similar_image"
    WEB_ENTITY = "web_entity"
    BEST_GUESS_LABEL = "best_guess_label"


class UrlRelation(StrEnum):
    SELF_ITEM = "self_item"
    SELF_SHOP = "self_shop"
    EXTERNAL = "external"
    IMAGE_HOST_ONLY = "image_host_only"
    UNKNOWN = "unknown"


class VisionQueryStatus(StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
