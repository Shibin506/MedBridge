"""Data shapes for MedBridge.

Two layers on purpose:

* ``*Draft`` models are what we ask the LLM to produce. Every item carries a
  ``source_quote``: the exact words from the discharge paper it came from.
* The un-suffixed models add fields that only *our code* sets (``grounded``,
  ``needs_confirmation``). The LLM never gets to decide those.

Keep the Draft models free of numeric/length constraints; the structured-output
feature of the API supports a limited subset of JSON Schema.
"""

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator


# --------------------------------------------------------------------------
# Layer 1: what the LLM fills in
# --------------------------------------------------------------------------
Route = Literal[
    "oral", "sublingual", "inhaled", "topical", "ophthalmic", "otic", "nasal",
    "rectal", "subcutaneous", "intramuscular", "intravenous", "other",
]


class MedicationDraft(BaseModel):
    name: str = Field(description="Drug name exactly as written (brand or generic).")
    dose: str | None = Field(
        description="Amount taken each time, exactly as the paper says, INCLUDING the number of tablets/puffs when it is "
        "more than one (for example '500 mg, 2 tablets'). null if not stated."
    )
    route: Route | None = Field(
        description="Route of administration as a standard clinical term, chosen from the paper's wording "
        "(e.g. 'by mouth' or 'swallow' -> oral, 'puffs' -> inhaled, 'shot' under the skin -> subcutaneous). "
        "Use 'other' if it is stated but not in the list. null if the paper does not say."
    )
    frequency: str | None = Field(description="How often, e.g. 'once daily in the morning'. null if not stated.")
    duration: str | None = Field(
        description="How long or until when, WITHOUT a leading 'for': '7 days', 'until your surgeon says it is safe'. "
        "Always keep any 'until ...' condition, especially for medicines to stop. null if not stated."
    )
    purpose: str | None = Field(description="Why it is taken, only if the document says so. Otherwise null.")
    instructions: str | None = Field(description="Special instructions, e.g. 'take with food'. null if none.")
    status: Literal["new", "changed", "continue", "stop"] = Field(
        description="'new' started this stay, 'changed' dose/frequency changed, "
        "'continue' unchanged home med, 'stop' patient must stop taking it."
    )
    previous_dose: str | None = Field(
        default=None,
        description="ONLY when status is 'changed': the dose BEFORE the change, e.g. '20 mg'. null otherwise.",
    )
    source_quote: str = Field(description="Verbatim excerpt from the document that supports this item.")

    @field_validator("name")
    @classmethod
    def _capitalize_name(cls, value: str) -> str:
        value = value.strip()
        return value[:1].upper() + value[1:]

    @field_validator("duration")
    @classmethod
    def _drop_leading_for(cls, value: str | None) -> str | None:
        # Models often write "for 35 days"; screens and the schedule add their own "for".
        return re.sub(r"^\s*for\s+", "", value, flags=re.I) or None if value else value


class FollowUpDraft(BaseModel):
    what: str = Field(description="Appointment or test, e.g. 'Cardiology clinic visit', 'Blood test (BMP)'.")
    with_whom: str | None = Field(description="Clinic or clinician if stated, else null.")
    when: str | None = Field(description="Timing exactly as written, e.g. 'within 7 days'. null if not stated.")
    contact: str | None = Field(
        default=None,
        description="The phone number exactly as written, followed in brackets by what it is for ONLY if the paper says "
        "(for example '555-0142 (to schedule)'). Do not start with 'Call'. null if the paper gives no number.",
    )
    source_quote: str = Field(description="Verbatim excerpt from the document that supports this item.")


class WarningSignDraft(BaseModel):
    symptom: str = Field(description="The symptom or situation to watch for.")
    action: str = Field(description="What the document says to do, e.g. 'Call 911', 'Call your doctor'.")
    source_quote: str = Field(description="Verbatim excerpt from the document that supports this item.")


class RestrictionDraft(BaseModel):
    category: Literal["diet", "activity", "wound_care", "monitoring", "medication_limit", "other"] = Field(
        description="'monitoring' = something to measure or record (weigh yourself, blood sugar, blood pressure); "
        "'medication_limit' = a permitted over-the-counter medicine or a maximum daily amount."
    )
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
    patient_confirmed: bool = False  # set by the patient on the confirm screen (Phase 2)


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
    # The text we extracted from, so the UI can show "your paper" next to the data.
    document_text: str = ""
    # Sentences of the paper that nothing extracted seems to cover (a hint that something may have been dropped).
    uncovered_lines: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Phase 2: the plain-language plan
# --------------------------------------------------------------------------
# What the LLM writes. Ids ("med_0", "fu_1", ...) are assigned by our code so we
# can check that nothing was dropped or invented.
class MedExplanationDraft(BaseModel):
    id: str
    how_to_take: str = Field(
        description="Plain-language instructions built ONLY from the dose, route, frequency, "
        "duration and instructions in the data. For status 'stop', say clearly to stop taking it."
    )
    why_taking: str | None = Field(
        description="One plain sentence on what the medicine is for. Use the 'purpose' field if given; "
        "otherwise a short, general description of what this kind of medicine is commonly used for, "
        "or null if you are not sure."
    )


class TextItemDraft(BaseModel):
    id: str
    plain_text: str


class PlanDraft(BaseModel):
    summary: str = Field(description="2-3 short sentences: why the patient was in hospital (if stated) and what this plan covers.")
    medications: list[MedExplanationDraft]
    follow_ups: list[TextItemDraft]
    warning_signs: list[TextItemDraft]
    restrictions: list[TextItemDraft]
    disclaimer: str = Field(description="The provided disclaimer sentence, translated into the target language.")


class PlanRequest(BaseModel):
    extraction: ExtractionResult
    language: str = "en"
    reading_level: Literal["simple", "standard"] = "simple"
    acknowledged_unclear: bool = False  # patient has read the "please check" notes
    acknowledged_review: bool = False  # patient says they compared the whole list with their paper


class PlanMedication(BaseModel):
    id: str
    status: Literal["new", "changed", "continue", "stop"]  # copied by code, never by the LLM
    name: str  # copied by code
    dose: str | None  # copied by code
    frequency: str | None  # copied by code
    how_to_take: str  # LLM
    why_taking: str | None  # LLM
    why_source: Literal["your_paper", "general_knowledge"] | None  # decided by code
    missing_info: list[Literal["dose", "frequency"]] = Field(default_factory=list)  # decided by code


class PlanItem(BaseModel):
    id: str
    plain_text: str  # LLM
    original: str  # what the paper data says, rendered by code (shown for transparency)
    emergency: bool = False  # code: the item involves calling 911


class PatientPlan(BaseModel):
    language: str
    language_name: str
    reading_level: str
    summary: str
    medications: list[PlanMedication]
    follow_ups: list[PlanItem]
    warning_signs: list[PlanItem]
    restrictions: list[PlanItem]
    disclaimer: str
    disclaimer_en: str


# --------------------------------------------------------------------------
# Phase 3: daily schedule and safety check (all produced by code, not the LLM)
# --------------------------------------------------------------------------
class ScheduleItem(BaseModel):
    name: str
    dose: str | None
    note: str | None  # instructions, duration, "dose changed", "with meals"
    status: Literal["new", "changed", "continue", "stop"]


class ScheduleSlot(BaseModel):
    time: str  # "08:00" (24h, easy to sort and to use for SMS reminders later)
    label: str  # "Morning"
    items: list[ScheduleItem]


class AsNeededItem(BaseModel):
    name: str
    dose: str | None
    how_often: str | None  # the paper's own words
    note: str | None


class TaperStep(BaseModel):
    when: str  # "Days 1-2"
    dose: str  # "40 mg"


class TaperPlan(BaseModel):
    name: str
    steps: list[TaperStep]
    after: str | None  # "Then stop."
    note: str | None


class UnscheduledItem(BaseModel):
    name: str
    reason: str  # why we did not guess a time


class DailySchedule(BaseModel):
    slots: list[ScheduleSlot]
    as_needed: list[AsNeededItem]
    tapers: list[TaperPlan]
    unscheduled: list[UnscheduledItem]


class NormalizedMed(BaseModel):
    name: str
    ingredients: list[str]
    source: Literal["local", "rxnorm", "name"]  # how sure we are: name = assumed from the written name


class DuplicateFinding(BaseModel):
    ingredient: str
    medicines: list[str]
    message: str


class StoppedConflict(BaseModel):
    ingredient: str
    stopped: str
    still_listed: str
    message: str


class InteractionHint(BaseModel):
    drug_a: str
    drug_b: str
    source: str  # where the sentence comes from
    excerpt: str  # verbatim sentence from that source


class TotalContribution(BaseModel):
    name: str
    mg_per_dose: int
    doses_per_day: int  # the most the schedule or the "as needed" wording allows
    mg_per_day: int
    as_needed: bool = False


class DailyTotalFinding(BaseModel):
    ingredient: str
    total_mg: int
    limit_mg: int
    limit_source: Literal["your paper", "common label maximum"]
    contributors: list[TotalContribution]
    message: str


class SafetyReport(BaseModel):
    normalized: list[NormalizedMed]
    duplicates: list[DuplicateFinding]
    stopped_conflicts: list[StoppedConflict]
    interactions: list[InteractionHint]
    interaction_check: Literal["done", "partial", "unavailable", "not_run"]
    notes: list[str]
    daily_totals: list[DailyTotalFinding] = Field(default_factory=list)
