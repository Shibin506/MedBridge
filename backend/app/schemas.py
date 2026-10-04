"""Data shapes for MedBridge.

Two layers on purpose:

* ``*Draft`` models are what we ask the LLM to produce. Every item carries a
  ``source_quote``: the exact words from the discharge paper it came from.
* The un-suffixed models add fields that only *our code* sets (``grounded``,
  ``needs_confirmation``). The LLM never gets to decide those.

Keep the Draft models free of numeric/length constraints; the structured-output
feature of the API supports a limited subset of JSON Schema.
"""

from typing import Literal

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------
# Layer 1: what the LLM fills in
# --------------------------------------------------------------------------
class MedicationDraft(BaseModel):
    name: str = Field(description="Drug name exactly as written (brand or generic).")
    dose: str | None = Field(description="Strength per dose, e.g. '40 mg'. null if not stated.")
    route: str | None = Field(description="e.g. 'by mouth', 'inhaled', 'injection'. null if not stated.")
    frequency: str | None = Field(description="How often, e.g. 'once daily in the morning'. null if not stated.")
    duration: str | None = Field(description="How long, e.g. 'for 7 days', 'until follow-up'. null if not stated.")
    purpose: str | None = Field(description="Why it is taken, only if the document says so. Otherwise null.")
    instructions: str | None = Field(description="Special instructions, e.g. 'take with food'. null if none.")
    status: Literal["new", "changed", "continue", "stop"] = Field(
        description="'new' started this stay, 'changed' dose/frequency changed, "
        "'continue' unchanged home med, 'stop' patient must stop taking it."
    )
    source_quote: str = Field(description="Verbatim excerpt from the document that supports this item.")


class FollowUpDraft(BaseModel):
    what: str = Field(description="Appointment or test, e.g. 'Cardiology clinic visit', 'Blood test (BMP)'.")
    with_whom: str | None = Field(description="Clinic or clinician if stated, else null.")
    when: str | None = Field(description="Timing exactly as written, e.g. 'within 7 days'. null if not stated.")
    source_quote: str = Field(description="Verbatim excerpt from the document that supports this item.")


class WarningSignDraft(BaseModel):
    symptom: str = Field(description="The symptom or situation to watch for.")
    action: str = Field(description="What the document says to do, e.g. 'Call 911', 'Call your doctor'.")
    source_quote: str = Field(description="Verbatim excerpt from the document that supports this item.")


class RestrictionDraft(BaseModel):
    category: Literal["diet", "activity", "wound_care", "other"]
    instruction: str = Field(description="The do/don't instruction, e.g. 'No more than 2,000 mg sodium per day'.")
    source_quote: str = Field(description="Verbatim excerpt from the document that supports this item.")


class ExtractionDraft(BaseModel):
    diagnosis_summary: str | None = Field(
        description="One short sentence on why the patient was in hospital, only if stated. Otherwise null."
    )
    medications: list[MedicationDraft]
    follow_ups: list[FollowUpDraft]
    warning_signs: list[WarningSignDraft]
    restrictions: list[RestrictionDraft]
    unclear_items: list[str] = Field(
        description="Anything ambiguous, contradictory or missing that a human should check. "
        "Prefer listing a doubt here over guessing."
    )


# --------------------------------------------------------------------------
# Layer 2: what our code returns (Draft + verification fields set by code)
# --------------------------------------------------------------------------
class _Verification(BaseModel):
    grounded: bool = False  # source_quote really appears in the document
    needs_confirmation: bool = True  # patient/clinician must check this item
    issues: list[str] = Field(default_factory=list)  # why it needs confirmation


class Medication(MedicationDraft, _Verification):
    pass


class FollowUp(FollowUpDraft, _Verification):
    pass


class WarningSign(WarningSignDraft, _Verification):
    pass


class Restriction(RestrictionDraft, _Verification):
    pass


class ExtractionResult(BaseModel):
    diagnosis_summary: str | None
    medications: list[Medication]
    follow_ups: list[FollowUp]
    warning_signs: list[WarningSign]
    restrictions: list[Restriction]
    unclear_items: list[str]
    # Summary numbers the UI can show ("2 items need your check")
    total_items: int
    items_needing_confirmation: int
