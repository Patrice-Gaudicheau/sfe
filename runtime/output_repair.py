"""Reusable output repair for executor-visible answers."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from typing import Any, Protocol

from runtime.output_validation import OutputValidationResult, OutputValidator
from runtime.run_experiment import _extract_response_text, _extract_token_usage


OUTPUT_REPAIR_STATUS_NOT_REQUIRED = "not_required"
OUTPUT_REPAIR_STATUS_SKIPPED_SELECTION_INCOMPLETE = "skipped_selection_incomplete"
OUTPUT_REPAIR_STATUS_ATTEMPTED_COMPLETE = "attempted_complete"
OUTPUT_REPAIR_STATUS_ATTEMPTED_INCOMPLETE = "attempted_incomplete"
OUTPUT_REPAIR_STATUS_DISABLED = "disabled"


class RepairProvider(Protocol):
    def chat(
        self,
        messages: list[dict[str, str]],
        model: str,
        max_tokens: int = 512,
        temperature: float = 0.2,
        chat_template_kwargs: dict | None = None,
    ) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class OutputRepairResult:
    """Single-attempt repair result for a visible executor answer."""

    status: str
    attempted: bool
    repair_count: int
    repaired_text: str
    missing_targets_before: tuple[str, ...]
    missing_targets_after: tuple[str, ...]
    used_same_context: bool
    added_tokens: int | None
    added_latency_ms: int | None
    added_estimated_cost: None
    error: str
    prompt_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    validation: OutputValidationResult | None

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["missing_targets_before"] = list(self.missing_targets_before)
        data["missing_targets_after"] = list(self.missing_targets_after)
        if self.validation is not None:
            data["validation"] = self.validation.to_dict()
        return data


class OutputRepairer:
    """Repair visible output using the same selected context and executor."""

    def __init__(self, validator: OutputValidator | None = None):
        self.validator = validator or OutputValidator()

    def repair(
        self,
        *,
        provider: RepairProvider,
        model: str,
        question: str,
        selected_block_id: str,
        selected_context: str,
        original_output: str,
        missing_targets: tuple[str, ...],
        required_targets: tuple[str, ...],
        max_tokens: int,
    ) -> OutputRepairResult:
        prompt = build_output_repair_prompt(
            question=question,
            selected_block_id=selected_block_id,
            selected_context=selected_context,
            original_output=original_output,
            missing_targets=missing_targets,
        )
        started = time.perf_counter()
        response: dict[str, Any] = {}
        repaired_output = ""
        error = ""
        try:
            response = provider.chat(
                [{"role": "user", "content": prompt}],
                model=model,
                max_tokens=max_tokens,
                temperature=0.0,
            )
            repaired_output = _extract_response_text(response)
        except Exception as exc:
            error = str(exc)
        latency_ms = int((time.perf_counter() - started) * 1000)
        token_usage = _extract_token_usage(response, prompt, repaired_output)
        validation = self.validator.validate(
            output=repaired_output,
            required_targets=required_targets,
        )
        status = (
            OUTPUT_REPAIR_STATUS_ATTEMPTED_COMPLETE
            if not error and validation.contains_all_targets
            else OUTPUT_REPAIR_STATUS_ATTEMPTED_INCOMPLETE
        )
        return OutputRepairResult(
            status=status,
            attempted=True,
            repair_count=1,
            repaired_text=repaired_output,
            missing_targets_before=missing_targets,
            missing_targets_after=validation.missing_targets,
            used_same_context=True,
            added_tokens=int(token_usage["total_tokens"]),
            added_latency_ms=latency_ms,
            added_estimated_cost=None,
            error=error,
            prompt_tokens=int(token_usage["input_tokens"]),
            output_tokens=int(token_usage["output_tokens"]),
            total_tokens=int(token_usage["total_tokens"]),
            validation=validation,
        )


def build_output_repair_prompt(
    *,
    question: str,
    selected_block_id: str,
    selected_context: str,
    original_output: str,
    missing_targets: tuple[str, ...],
) -> str:
    missing_targets_json = json.dumps(list(missing_targets))
    return (
        "/no_think\n"
        "Correct the visible final answer using only the selected context block below. "
        "Do not use outside facts. Do not explain your reasoning or include chain-of-thought. "
        "Return only a concise corrected final answer that includes every required value.\n\n"
        f"Question: {question}\n\n"
        f"Missing required targets JSON: {missing_targets_json}\n\n"
        f"Original visible answer:\n{original_output}\n\n"
        f"Selected context block id: {selected_block_id}\n"
        "Selected context block text:\n"
        f"{selected_context}\n\n"
        "Corrected final answer:"
    )


def output_repair_not_attempted(
    *,
    status: str,
    missing_targets_before: tuple[str, ...] = (),
    missing_targets_after: tuple[str, ...] = (),
    used_same_context: bool = False,
) -> OutputRepairResult:
    return OutputRepairResult(
        status=status,
        attempted=False,
        repair_count=0,
        repaired_text="",
        missing_targets_before=missing_targets_before,
        missing_targets_after=missing_targets_after,
        used_same_context=used_same_context,
        added_tokens=0,
        added_latency_ms=0,
        added_estimated_cost=None,
        error="",
        prompt_tokens=None,
        output_tokens=None,
        total_tokens=None,
        validation=None,
    )
