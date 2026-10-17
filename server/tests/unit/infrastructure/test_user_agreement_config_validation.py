from src.infrastructure.config.validation import RuntimeConfigValidator


def test_user_agreement_whitelist_defaults_to_an_empty_list():
    items = RuntimeConfigValidator._validate_user_agreement_config({})

    assert items[0].status == "ok"
    assert items[0].message == "协议豁免账号数: 0"


def test_user_agreement_whitelist_rejects_invalid_values():
    invalid = RuntimeConfigValidator._validate_user_agreement_config(
        {"user_agreements": {"exempt_user_uuids": ["valid", "", 1]}}
    )

    assert invalid[0].status == "error"
