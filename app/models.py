"""Input models for each tool.

These do double duty: they validate inputs, and in Phase 2 we'll export their
JSON schemas to register the tools with Vapi (so the schema has one source of truth).
"""
from typing import Literal, Optional

from pydantic import BaseModel, Field


class CheckAvailabilityIn(BaseModel):
    date: str = Field(..., description="Date to check, YYYY-MM-DD, in the clinic's time zone.")
    provider: Optional[str] = Field(None, description="Optional provider name, e.g. 'Dr. Patel'. Omit for any provider.")
    time_of_day: Optional[Literal["morning", "afternoon", "any"]] = Field(
        None, description="Optional caller preference.")


class BookAppointmentIn(BaseModel):
    patient_name: str = Field(..., description="Caller's full name, first and last.")
    dob: str = Field(..., description="Caller's date of birth, YYYY-MM-DD.")
    slot_id: int = Field(..., description="slot_id from a check_availability result. Never invent one.")
    reason: str = Field(..., description="Short, non-clinical reason for the visit, in the caller's words.")


class FindAppointmentIn(BaseModel):
    patient_name: str = Field(..., description="Caller's full name.")
    dob: str = Field(..., description="Caller's date of birth, YYYY-MM-DD.")


class RescheduleAppointmentIn(BaseModel):
    appointment_id: int = Field(..., description="appointment_id from find_appointment.")
    new_slot_id: int = Field(..., description="slot_id from check_availability.")


class CancelAppointmentIn(BaseModel):
    appointment_id: int = Field(..., description="appointment_id from find_appointment.")


class TransferToHumanIn(BaseModel):
    reason: str = Field(..., description="Why the caller needs a human, e.g. 'caller requested', 'clinical question'.")


TOOL_MODELS = {
    "check_availability": CheckAvailabilityIn,
    "book_appointment": BookAppointmentIn,
    "find_appointment": FindAppointmentIn,
    "reschedule_appointment": RescheduleAppointmentIn,
    "cancel_appointment": CancelAppointmentIn,
    "transfer_to_human": TransferToHumanIn,
}
