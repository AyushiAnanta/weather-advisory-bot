from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, ValidationInfo, field_validator, model_validator


Severity = Literal["info", "low", "medium", "high"]
Operator = Literal[">", ">=", "<", "<=", "==", "in"]
Day = Literal["today", "tomorrow", "requested"]
DEFAULT_ALLOWLIST_PATH = Path(__file__).parents[1] / "config" / "weather_fields.yaml"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Window(StrictModel):
    day: Day
    start_hour: int = Field(ge=0, le=23)
    end_hour: int = Field(ge=0, le=23)

    @model_validator(mode="after")
    def validate_order(self):
        if self.start_hour > self.end_hour:
            raise ValueError("window.start_hour must be <= window.end_hour")
        return self


class OperatorCondition(StrictModel):
    op: Operator
    value: int | float | list[int | float]

    @model_validator(mode="before")
    @classmethod
    def validate_operator_value(cls, data):
        if isinstance(data, dict) and "op" in data and "value" in data:
            op, value = data["op"], data["value"]
            if op == "in" and not isinstance(value, list):
                raise ValueError("value must be a list when op is 'in'")
            if op != "in" and isinstance(value, list):
                raise ValueError(f"value must not be a list when op is {op!r}")
        return data


class CurrentCondition(OperatorCondition):
    source: Literal["current"]
    field: str


class HourlyCondition(OperatorCondition):
    source: Literal["hourly"]
    field: str
    agg: Literal["max", "min", "sum"]
    window: Window | None = None


class DailyCondition(OperatorCondition):
    source: Literal["daily"]
    field: str
    day: Literal["today", "tomorrow"]


Condition = Annotated[
    CurrentCondition | HourlyCondition | DailyCondition,
    Field(discriminator="source"),
]


class Conditions(StrictModel):
    all: list[Condition] | None = None
    any: list[Condition] | None = None

    @model_validator(mode="after")
    def require_condition(self):
        if not (self.all or self.any):
            raise ValueError("at least one condition is required")
        return self


class ClassifierFact(StrictModel):
    source: Literal["hourly"]
    field: str
    agg: Literal["max", "min", "sum"]
    window: Window | None = None


class Classifier(StrictModel):
    facts: list[ClassifierFact]
    rubric: str
    outcomes: dict[str, str]

    @field_validator("facts")
    @classmethod
    def facts_must_not_be_empty(cls, value: list[ClassifierFact]) -> list[ClassifierFact]:
        if not value:
            raise ValueError("must contain at least one fact")
        return value

    @field_validator("rubric")
    @classmethod
    def rubric_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        return value

    @field_validator("outcomes")
    @classmethod
    def outcomes_must_have_exact_labels(cls, value: dict[str, str]) -> dict[str, str]:
        expected = {"suitable", "marginal", "unsuitable"}
        if set(value) != expected:
            raise ValueError(f"must contain exactly these keys: {sorted(expected)}")
        if any(not isinstance(text, str) or not text.strip() for text in value.values()):
            raise ValueError("each outcome must be a non-empty string")
        return value


class SOP(StrictModel):
    id: str
    category: str
    severity: Severity
    applies_to: list[str]
    kind: Literal["rules", "classifier"] = "rules"
    conditions: Conditions | None = Field(default=None, validate_default=True)
    classifier: Classifier | None = Field(default=None, validate_default=True)
    guidance: str | None = Field(default=None, validate_default=True)
    rubric: str | None = None
    override: bool = False

    @field_validator("conditions", mode="before")
    @classmethod
    def conditions_required_for_rules_only(cls, value, info: ValidationInfo):
        kind = info.data.get("kind", "rules")
        if kind == "rules" and value is None:
            raise ValueError("conditions are required for rules SOPs")
        if kind == "classifier" and value is not None:
            raise ValueError("classifier SOPs must not have conditions")
        return value

    @field_validator("classifier", mode="before")
    @classmethod
    def classifier_required_for_classifier_only(cls, value, info: ValidationInfo):
        kind = info.data.get("kind", "rules")
        if kind == "classifier" and value is None:
            raise ValueError("classifier block is required for classifier SOPs")
        if kind == "rules" and value is not None:
            raise ValueError("rules SOPs must not have a classifier block")
        return value

    @field_validator("guidance", mode="before")
    @classmethod
    def guidance_required_for_rules_only(cls, value, info: ValidationInfo):
        kind = info.data.get("kind", "rules")
        if kind == "rules" and value is None:
            raise ValueError("guidance is required for rules SOPs")
        if kind == "classifier" and value is not None:
            raise ValueError("classifier SOPs must not have guidance")
        return value

    @field_validator("id")
    @classmethod
    def id_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        return value

    @field_validator("applies_to")
    @classmethod
    def applies_to_must_be_valid(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("must not be empty")
        if "*" in value and value != ["*"]:
            raise ValueError('applies_to must be ["*"] when using wildcard')
        return value


def _validation_field(error: dict) -> str:
    location = ".".join(str(part) for part in error["loc"])
    return location or "file"


def _load_allowlist(path: str | Path) -> dict[str, list[str]]:
    with Path(path).open(encoding="utf-8") as file:
        raw = yaml.safe_load(file)
    expected_sources = {"current", "hourly", "daily"}
    if not isinstance(raw, dict) or set(raw) != expected_sources:
        raise ValueError(f"{Path(path).name}: source: expected exactly {sorted(expected_sources)}")
    if any(not isinstance(fields, list) or any(not isinstance(name, str) for name in fields) for fields in raw.values()):
        raise ValueError(f"{Path(path).name}: fields: each source must contain a list of field names")
    return raw


def load_sops(
    directory: str | Path,
    allowlist_path: str | Path = DEFAULT_ALLOWLIST_PATH,
) -> list[SOP]:
    """Load and validate all YAML SOPs in a directory."""
    allowed = _load_allowlist(allowlist_path)
    sops: list[SOP] = []
    ids: set[str] = set()
    paths = sorted([*Path(directory).glob("*.yaml"), *Path(directory).glob("*.yml")])
    for path in paths:
        try:
            with path.open(encoding="utf-8") as file:
                raw = yaml.safe_load(file)
            sop = SOP.model_validate(raw)
        except (OSError, yaml.YAMLError, ValidationError, TypeError, ValueError) as exc:
            field = "file"
            if isinstance(exc, ValidationError) and exc.errors():
                error = exc.errors()[0]
                field = _validation_field(error)
                message = error["msg"]
            else:
                message = str(exc)
            raise ValueError(f"{path.name}: {field}: {message}") from exc
        fields_to_validate = [(condition.source, condition.field) for condition in _iter_conditions(sop)]
        if sop.classifier is not None:
            fields_to_validate.extend((fact.source, fact.field) for fact in sop.classifier.facts)
        for source, field_name in fields_to_validate:
            if field_name not in allowed[source]:
                allowed_names = ", ".join(allowed[source])
                raise ValueError(
                    f"{path.name}: field {field_name!r}: unknown {source} weather field; "
                    f"allowed: [{allowed_names}]"
                )
        if sop.id in ids:
            raise ValueError(f"{path.name}: id: duplicate SOP id {sop.id!r}")
        ids.add(sop.id)
        sops.append(sop)
    return sops


def _iter_conditions(sop: SOP):
    if sop.conditions is None:
        return []
    return (sop.conditions.all or []) + (sop.conditions.any or [])


def all_activity_tags(sops: list[SOP]) -> list[str]:
    return sorted({tag for sop in sops for tag in sop.applies_to if tag != "*"})


def required_fields(sops: list[SOP]) -> dict[str, list[str]]:
    fields: dict[str, set[str]] = {"current": set(), "hourly": set(), "daily": set()}
    for sop in sops:
        for condition in _iter_conditions(sop):
            fields[condition.source].add(condition.field)
        if sop.classifier is not None:
            for fact in sop.classifier.facts:
                fields[fact.source].add(fact.field)
    return {source: sorted(names) for source, names in fields.items()}
