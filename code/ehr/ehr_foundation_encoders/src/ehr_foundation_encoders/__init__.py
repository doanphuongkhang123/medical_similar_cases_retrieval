"""Structured EHR foundation-encoder data preparation."""

from .common import build_common_dataset, validate_structured_tables
from .raw_workbook import prepare_smb_raw_dataset
from .smb import audit_smb_serialization, build_target_meds
from .tokenization import audit_smb_token_lengths
from .windowing import build_smb_window_selection

__all__ = [
    "audit_smb_serialization",
    "audit_smb_token_lengths",
    "build_common_dataset",
    "build_target_meds",
    "build_smb_window_selection",
    "prepare_smb_raw_dataset",
    "validate_structured_tables",
]
