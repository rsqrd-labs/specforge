from __future__ import annotations

from collections.abc import Callable

from prompt_eval.graders.common import GraderResult, clamp_score, make_result
from prompt_eval.graders.coverage import (
    fr_to_task_coverage_pct,
    fr_to_test_coverage_pct,
    harness_file_presence_pct,
    plan_section_presence_pct,
    rtm_coverage_pct,
)
from prompt_eval.graders.format import (
    code_fence_balance,
    heading_order_match,
    id_format_consistency,
    mermaid_validity,
    table_column_counts,
    trailing_newline_policy,
)
from prompt_eval.graders.quality import (
    adr_completeness_pct,
    banned_phrase_hit_count,
    capacity_model_presence,
    denylist_freshness,
    deprecated_api_hit_count,
    fmea_presence,
    frontend_section_presence_when_applicable,
    slo_presence,
    stride_presence,
)
from prompt_eval.graders.safety import (
    fake_system_message_echo,
    prompt_injection_echo_scan,
    role_change_accept,
    secret_shaped_string_scan,
    security_rules_stripped,
    untrusted_content_tag_presence,
)

GraderFn = Callable[[str, str, dict[str, str]], GraderResult]


ALL_GRADERS: tuple[GraderFn, ...] = (
    rtm_coverage_pct,
    fr_to_test_coverage_pct,
    fr_to_task_coverage_pct,
    plan_section_presence_pct,
    harness_file_presence_pct,
    deprecated_api_hit_count,
    banned_phrase_hit_count,
    adr_completeness_pct,
    frontend_section_presence_when_applicable,
    capacity_model_presence,
    stride_presence,
    slo_presence,
    fmea_presence,
    denylist_freshness,
    heading_order_match,
    code_fence_balance,
    mermaid_validity,
    table_column_counts,
    id_format_consistency,
    trailing_newline_policy,
    secret_shaped_string_scan,
    prompt_injection_echo_scan,
    untrusted_content_tag_presence,
    fake_system_message_echo,
    role_change_accept,
    security_rules_stripped,
)

__all__ = [
    "ALL_GRADERS",
    "GraderFn",
    "GraderResult",
    "clamp_score",
    "make_result",
]
