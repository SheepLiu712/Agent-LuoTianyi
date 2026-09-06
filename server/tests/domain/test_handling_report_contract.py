"""Public report behavior specified by domain/handling-report.md."""

from datetime import datetime, timezone, tzinfo
from enum import Enum

import pytest

import src.domain.agent as domain


PAST = datetime(2000, 1, 1, tzinfo=timezone.utc)
STATUSES = ("COMPLETED", "CANCELLED", "FAILED")
ID_FIELDS = (
    "considered_pending_stimulus_ids", "consumed_pending_stimulus_ids",
    "retained_pending_stimulus_ids", "emitted_plan_ids",
)
CONTRACT_CODES = (
    "CONTRACT_INVALID_STIMULUS", "CONTRACT_UNSUPPORTED_SCHEMA", "CONTRACT_SNAPSHOT_MISMATCH",
)
RUNTIME_CODES = (
    "UNSUPPORTED_STIMULUS", "UNSUPPORTED_INTERACTION", "STALE_INTERACTION", "SINK_CLOSED",
    "BACKPRESSURE_TIMEOUT", "DEPENDENCY_UNAVAILABLE", "PROVIDER_TIMEOUT", "INTERNAL_ERROR",
)


def _public(name):
    # Missing capabilities fail as assertions, never as import/collection errors.
    assert name in vars(domain), f"HandlingReport SPEC capability not implemented: {name}"
    assert name in domain.__all__, f"HandlingReport SPEC public export missing: {name}"
    return getattr(domain, name)


def _fields(status="COMPLETED", **overrides):
    fields = dict(
        request_id="request-1", request_status=getattr(_public("HandlingRequestStatus"), status),
        trigger_stimulus_id="deadline-1", basis_interaction_revision=7,
        considered_pending_stimulus_ids=("M2", "M1", "M3"),
        consumed_pending_stimulus_ids=("M2", "M3"), retained_pending_stimulus_ids=("M1",),
        emitted_plan_ids=("plan-2", "plan-1"), reconsider_at=PAST,
        error_code=_public("HandlingErrorCode").INTERNAL_ERROR if status == "FAILED" else None,
        retryable=False,
    )
    fields.update(overrides)
    return fields


def _report(status="COMPLETED", **overrides):
    return _public("HandlingReport")(**_fields(status, **overrides))


def _invalid(fields, *args):
    factory = _public("HandlingReport")
    error_type = _public("InvalidHandlingReportError")
    expected_code = _public("HandlingReportErrorCode").CONTRACT_INVALID_HANDLING_REPORT
    with pytest.raises(error_type) as caught:
        factory(*args, **fields)
    assert isinstance(caught.value, ValueError)
    assert caught.value.code is expected_code
    return caught.value


def _readonly(obj, field, replacement):
    original = getattr(obj, field)
    with pytest.raises((AttributeError, TypeError)):
        setattr(obj, field, replacement)
    assert getattr(obj, field) == original


class OtherEnum(str, Enum):
    COMPLETED = "completed"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class NoOffset(tzinfo):
    def utcoffset(self, dt):
        return None


@pytest.mark.parametrize("name", (
    "HandlingReport", "HandlingRequestStatus", "HandlingErrorCode",
    "InvalidHandlingReportError", "HandlingReportErrorCode",
))
def test_report_protocol_is_available_from_public_domain_package(name):
    """五个协议名称均能从公开包取得。"""
    _public(name)


def test_status_enum_has_exact_wire_values():
    """请求完成状态独立于内容是否消费。"""
    status = _public("HandlingRequestStatus")
    assert issubclass(status, str)
    assert {member.name: member.value for member in status} == {
        "COMPLETED": "completed", "CANCELLED": "cancelled", "FAILED": "failed",
    }


def test_failure_and_construction_error_enums_are_distinct_protocols():
    """分别锁定处理失败与报告构造失败的错误码。"""
    failure, construction = _public("HandlingErrorCode"), _public("HandlingReportErrorCode")
    assert failure is not construction
    assert issubclass(failure, str) and issubclass(construction, str)
    assert {member.name: member.value for member in failure} == {
        name: name for name in CONTRACT_CODES + RUNTIME_CODES
    }
    assert {member.name: member.value for member in construction} == {
        "CONTRACT_INVALID_HANDLING_REPORT": "CONTRACT_INVALID_HANDLING_REPORT",
    }


def test_report_preserves_all_explicit_values_and_nonlexical_order():
    """合法值原样保存，既不裁剪身份也不重排刺激或计划。"""
    fields = _fields(request_id="  request-1  ", trigger_stimulus_id="  deadline-1  ")
    report = _public("HandlingReport")(**fields)
    assert {key: getattr(report, key) for key in fields} == fields
    assert report.considered_pending_stimulus_ids == ("M2", "M1", "M3")
    assert report.emitted_plan_ids == ("plan-2", "plan-1")


def test_equal_reports_compare_by_all_field_values():
    """独立构造的同值报告相等，任一合法字段变化可区分报告。"""
    original = _report()
    equal = _report()
    assert original is not equal and original == equal
    alternatives = _fields(
        request_id="request-2", request_status=_public("HandlingRequestStatus").CANCELLED,
        trigger_stimulus_id="M2", basis_interaction_revision=8,
        considered_pending_stimulus_ids=("M2", "M1", "M3", "M4"),
        consumed_pending_stimulus_ids=("M2",), retained_pending_stimulus_ids=("M1", "M3"),
        emitted_plan_ids=("other-plan",), reconsider_at=None, retryable=True,
    )
    # Use independent valid changes; partitions are checked as one related change.
    for field in ("request_id", "request_status", "trigger_stimulus_id",
                  "basis_interaction_revision", "emitted_plan_ids", "reconsider_at", "retryable"):
        assert original != _report(**{field: alternatives[field]})
    assert original != _report(consumed_pending_stimulus_ids=("M2",),
                               retained_pending_stimulus_ids=("M1", "M3"))
    assert original != _report(considered_pending_stimulus_ids=("M2", "M1", "M3", "M4"),
                               retained_pending_stimulus_ids=("M1", "M4"))
    assert _report("FAILED") != _report("FAILED", error_code=_public("HandlingErrorCode").SINK_CLOSED)


def test_fields_and_identity_tuples_are_immutable():
    """所有报告字段及元组内容不可原地修改。"""
    report = _report()
    for field in _fields():
        _readonly(report, field, None)
    for field in ID_FIELDS:
        with pytest.raises(TypeError):
            getattr(report, field)[0] = "changed"


def test_all_constructor_fields_are_required_keywords():
    """包括 None/False/空集合字段在内都必须显式传入。"""
    fields = _fields()
    for omitted in fields:
        _invalid({key: value for key, value in fields.items() if key != omitted})
    _invalid({key: value for key, value in fields.items() if key != "request_id"}, "request-1")
    _invalid(dict(fields, unexpected=None))


@pytest.mark.parametrize("field,value", [
    ("request_id", ""), ("request_id", 1), ("trigger_stimulus_id", " \t"),
    ("trigger_stimulus_id", None), ("basis_interaction_revision", -1),
    ("basis_interaction_revision", True), ("basis_interaction_revision", 1.0),
    ("request_status", "completed"), ("request_status", "unknown"),
    ("request_status", OtherEnum.COMPLETED), ("retryable", 1), ("retryable", None),
])
def test_invalid_scalar_fields_are_rejected_without_coercion(field, value):
    """拒绝非法身份、修订、状态和布尔声明。"""
    _invalid(_fields(**{field: value}))


@pytest.mark.parametrize("field", ID_FIELDS)
@pytest.mark.parametrize("value", [[], (" ",), (7,), ("M1", "M1")])
def test_each_identity_tuple_rejects_wrong_container_members_and_duplicates(field, value):
    """四类身份元组都拒绝列表、空白/非字符串成员和重复身份。"""
    _invalid(_fields(**{field: value}))


@pytest.mark.parametrize("consumed,retained", [
    (("M2",), ("M1",)),  # M3 omitted
    (("M2", "M3"), ("M1", "M2")),  # overlap
    (("M2", "M3", "outsider"), ("M1",)),
    (("M2", "M3"), ("M1", "outsider")),
    (("M3", "M2"), ("M1",)),  # reversed consumed
    (("M1",), ("M3", "M2")),  # reversed retained
])
def test_pending_partition_requires_exact_disjoint_coverage_and_relative_order(consumed, retained):
    """逐项拒绝漏结算、交叉结算、外部身份和逆序子序列。"""
    _invalid(_fields(consumed_pending_stimulus_ids=consumed, retained_pending_stimulus_ids=retained))


@pytest.mark.parametrize("field", ("consumed_pending_stimulus_ids", "retained_pending_stimulus_ids"))
def test_empty_considered_cannot_settle_any_content(field):
    """没有考察内容时，不能消费或保留外部身份。"""
    fields = _fields(considered_pending_stimulus_ids=(), consumed_pending_stimulus_ids=(),
                     retained_pending_stimulus_ids=(), reconsider_at=None)
    fields[field] = ("M1",)
    _invalid(fields)


@pytest.mark.parametrize("status", STATUSES)
@pytest.mark.parametrize("considered,consumed,retained", [
    ((), (), ()),
    (("M2", "M1"), (), ("M2", "M1")),
    (("M2", "M1"), ("M2", "M1"), ()),
    (("M2", "M1"), ("M2",), ("M1",)),
])
def test_every_status_accepts_empty_full_retained_full_consumed_and_partial_results(
    status, considered, consumed, retained,
):
    """请求状态与四种合法内容划分独立。"""
    report = _report(status, considered_pending_stimulus_ids=considered,
                     consumed_pending_stimulus_ids=consumed, retained_pending_stimulus_ids=retained,
                     reconsider_at=None, emitted_plan_ids=())
    assert report.request_status is getattr(_public("HandlingRequestStatus"), status)
    assert (report.considered_pending_stimulus_ids, report.consumed_pending_stimulus_ids,
            report.retained_pending_stimulus_ids) == (considered, consumed, retained)


def test_trigger_membership_and_different_identity_domains_are_independent():
    """协调 trigger 可在 considered 外，计划身份也可与刺激身份同值。"""
    report = _report(trigger_stimulus_id="deadline-1", emitted_plan_ids=("M2",))
    assert report.trigger_stimulus_id == "deadline-1"
    assert report.emitted_plan_ids == ("M2",)
    assert _report(trigger_stimulus_id="M2").trigger_stimulus_id == "M2"
    assert _report(basis_interaction_revision=0).basis_interaction_revision == 0


@pytest.mark.parametrize("status", STATUSES)
def test_accepted_plans_survive_each_request_end_state(status):
    """取消或失败仍可保留已接受计划的原始顺序。"""
    assert _report(status).emitted_plan_ids == ("plan-2", "plan-1")


@pytest.mark.parametrize("status", STATUSES)
@pytest.mark.parametrize("retryable", [False, True])
def test_retryable_is_preserved_independently_of_status_and_plans(status, retryable):
    """同状态及计划事实下，重试声明不被推断或改写。"""
    assert _report(status, retryable=retryable).retryable is retryable
    assert _report(status, retryable=retryable, emitted_plan_ids=(),
                   consumed_pending_stimulus_ids=("M2", "M1", "M3"),
                   retained_pending_stimulus_ids=(), reconsider_at=None).retryable is retryable


@pytest.mark.parametrize("status", ("COMPLETED", "CANCELLED"))
def test_nonfailed_report_cannot_carry_failure_code(status):
    """正常结束和取消报告不携带失败码。"""
    _invalid(_fields(status, error_code=_public("HandlingErrorCode").INTERNAL_ERROR))


@pytest.mark.parametrize("value", [None, "INTERNAL_ERROR", "UNKNOWN", OtherEnum.INTERNAL_ERROR])
def test_failed_report_requires_its_own_typed_failure_code(value):
    """FAILED 必须使用 HandlingErrorCode，不能缺失或借用字符串/其他枚举。"""
    _invalid(_fields("FAILED", error_code=value))


@pytest.mark.parametrize("name", CONTRACT_CODES)
def test_input_contract_failure_requires_all_considered_content_retained(name):
    """三种输入契约失败禁止声明已消费内容。"""
    code = getattr(_public("HandlingErrorCode"), name)
    _invalid(_fields("FAILED", error_code=code))
    report = _report("FAILED", error_code=code, consumed_pending_stimulus_ids=(),
                     retained_pending_stimulus_ids=("M2", "M1", "M3"))
    assert report.consumed_pending_stimulus_ids == ()
    assert report.retained_pending_stimulus_ids == ("M2", "M1", "M3")


@pytest.mark.parametrize("name", RUNTIME_CODES)
def test_runtime_failure_can_preserve_partial_consumption(name):
    """运行时失败保留失败前的合法部分消费和已接受计划。"""
    code = getattr(_public("HandlingErrorCode"), name)
    report = _report("FAILED", error_code=code)
    assert report.error_code is code
    assert report.consumed_pending_stimulus_ids == ("M2", "M3")
    assert report.retained_pending_stimulus_ids == ("M1",)
    assert report.emitted_plan_ids == ("plan-2", "plan-1")


@pytest.mark.parametrize("value", ["2000-01-01", PAST.replace(tzinfo=None), PAST.replace(tzinfo=NoOffset())])
def test_reconsider_time_requires_datetime_with_effective_timezone(value):
    """重评时间必须为具有有效时区偏移的 datetime。"""
    _invalid(_fields(reconsider_at=value))


@pytest.mark.parametrize("status", STATUSES)
def test_reconsider_time_is_optional_and_may_already_be_due(status):
    """有 retained 时，三种状态都接受空时间和已到期的带时区时间。"""
    assert _report(status, reconsider_at=None).reconsider_at is None
    assert _report(status, reconsider_at=PAST).reconsider_at == PAST
    _invalid(_fields(status, consumed_pending_stimulus_ids=("M2", "M1", "M3"),
                     retained_pending_stimulus_ids=()))


def test_construction_error_code_is_readonly_and_not_a_runtime_failure():
    """失败构造提供只读稳定码，不混入处理失败枚举。"""
    error = _invalid(_fields(request_id=""))
    _readonly(error, "code", None)
    assert not isinstance(error.code, _public("HandlingErrorCode"))


def test_shared_input_tuples_remain_unchanged_across_reports_and_rejected_construction():
    """成功与失败构造均保留调用方和已有报告的集合值。"""
    fields = _fields(emitted_plan_ids=("  plan-2  ", "plan-1"))
    first = _public("HandlingReport")(**fields)
    second = _public("HandlingReport")(**fields)
    _invalid(dict(fields, request_id=""))
    assert first == second
    assert fields["emitted_plan_ids"] == ("  plan-2  ", "plan-1")
    assert first.emitted_plan_ids == second.emitted_plan_ids == ("  plan-2  ", "plan-1")
    assert fields["considered_pending_stimulus_ids"] == ("M2", "M1", "M3")
