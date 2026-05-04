import json
from dataclasses import is_dataclass

import pytest
from dataclass_wizard import JSONWizard

from pi_apply.jd_data import EXTRACTION_PROTOCOL, JDData, JDDataError, parse_jd_json

FULL_JD = {
    "title": "Senior Platform Engineer",
    "company": "ExampleCo",
    "required": ["Python", "Kubernetes"],
    "preferred": ["FastAPI", "PostgreSQL"],
    "location": "Remote",
    "seniority": "senior",
    "required_years": 5.0,
    "team": "Platform",
    "key_responsibilities": [
        "Own deployment reliability",
        "Improve developer tooling",
    ],
    "pay_range_min": 180000.0,
    "pay_range_max": 220000.0,
}

FULL_JD_JSON = json.dumps(FULL_JD, separators=(",", ":"))


PARTIAL_JD = {
    "title": "Backend Engineer",
    "company": "ExampleCo",
    "required": ["Python"],
}

EXPECTED_PARTIAL_JD = {
    "title": "Backend Engineer",
    "company": "ExampleCo",
    "required": ["Python"],
    "preferred": None,
    "location": None,
    "seniority": "mid",
    "required_years": None,
    "team": None,
    "key_responsibilities": None,
    "pay_range_min": None,
    "pay_range_max": None,
}

PARTIAL_JD_JSON = """
{
  "title": "Backend Engineer",
  "company": "ExampleCo",
  "required": ["Python"]
}
"""


class TestJDDataModel:
    def test_jddata_is_dataclass(self):
        assert is_dataclass(JDData)

    def test_jddata_uses_json_wizard(self):
        assert issubclass(JDData, JSONWizard)

    def test_full_jddata_preserves_go_apply_fields(self):
        model = JDData(**FULL_JD)

        assert model.model_dump() == FULL_JD

    def test_optional_fields_can_be_omitted(self):
        model = JDData(**PARTIAL_JD)
        data = model.model_dump()

        assert data == EXPECTED_PARTIAL_JD

    def test_missing_or_empty_seniority_defaults_to_mid(self):
        missing = JDData(**PARTIAL_JD)
        empty = JDData(**PARTIAL_JD, seniority="")

        assert missing.model_dump()["seniority"] == "mid"
        assert empty.model_dump()["seniority"] == "mid"


class TestParseJDJson:
    def test_full_payload_round_trips(self):
        validated = parse_jd_json(FULL_JD_JSON)

        assert validated == FULL_JD

    def test_optional_fields_can_be_omitted(self):
        validated = parse_jd_json(PARTIAL_JD_JSON)

        assert validated == EXPECTED_PARTIAL_JD

    def test_malformed_json_is_rejected_with_invalid_jd(self):
        with pytest.raises(JDDataError) as exc_info:
            parse_jd_json("{not valid json")

        assert exc_info.value.code == "invalid_jd"

    def test_non_object_json_is_rejected_with_invalid_jd(self):
        with pytest.raises(JDDataError) as exc_info:
            parse_jd_json("[]")

        assert exc_info.value.code == "invalid_jd"

    def test_unsupported_seniority_is_rejected(self):
        jd_json = """
        {
          "title": "Backend Engineer",
          "company": "ExampleCo",
          "required": ["Python"],
          "seniority": "principal"
        }
        """

        with pytest.raises(JDDataError) as exc_info:
            parse_jd_json(jd_json)

        assert exc_info.value.code == "invalid_jd"

    def test_empty_payload_is_rejected_with_jd_empty(self):
        with pytest.raises(JDDataError) as exc_info:
            parse_jd_json("{}")

        assert exc_info.value.code == "jd_empty"


class TestExtractionProtocol:
    def test_contains_go_apply_extraction_rules(self):
        assert "Copy the EXACT string" in EXTRACTION_PROTOCOL
        assert "do NOT paraphrase" in EXTRACTION_PROTOCOL
        assert "compact JSON" in EXTRACTION_PROTOCOL
        assert "Do NOT invent values" in EXTRACTION_PROTOCOL

    def test_protocol_contract_matches_actual_jd_json(self):
        protocol_example = """{"title":"Senior Platform Engineer","company":"ExampleCo",
            "required":["Python","Kubernetes"],"preferred":["FastAPI","PostgreSQL"],
            "location":"Remote","seniority":"senior","required_years":5.0,
            "team":"Platform",
            "key_responsibilities":["Own deployment reliability","Improve developer tooling"],
            "pay_range_min":180000.0,"pay_range_max":220000.0}"""

        assert parse_jd_json(protocol_example) == FULL_JD
