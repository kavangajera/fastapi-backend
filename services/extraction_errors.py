"""Shared exception for LLM-vision extractors (dispense/invoice).

Raised only when an *entire* document yields no usable data across every
page — a signal the file isn't the expected report type at all, not a
per-page hiccup. Kept provider-agnostic (plain ValueError) so services/
doesn't depend on kafka_worker/; the worker handlers translate this into
`PermanentDocumentError` so it fails fast instead of burning retries.
"""

from __future__ import annotations


class NoExtractableDataError(ValueError):
    pass
