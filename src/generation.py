from __future__ import annotations

import json
import re
from typing import Any, Callable, Iterator

from src.diagnostics import get_logger


class OutputValidationError(Exception):
    """Raised when a model response does not match the requested structure."""


def extract_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", cleaned, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        cleaned = fenced.group(1)
    else:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            cleaned = cleaned[start : end + 1]

    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise OutputValidationError(f"Response was not valid JSON: {exc.msg}.") from exc
    if not isinstance(value, dict):
        raise OutputValidationError("Response must be one JSON object.")
    return value


def validate_payload(resource: str, payload: dict[str, Any], expected_count: int | None = None) -> list[str]:
    normalize_payload(resource, payload)
    issues: list[str] = []
    if resource == "questions":
        items = _items(payload, "questions", issues)
        _exact_count(items, expected_count, "questions", issues)
        for index, item in enumerate(items, 1):
            _required_text(item, ("question",), f"Question {index}", issues)
            if isinstance(item, dict) and not str(item.get("question", "")).strip().endswith("?"):
                issues.append(f"Question {index} must end with a question mark.")
    elif resource == "mcqs":
        items = _items(payload, "mcqs", issues)
        _exact_count(items, expected_count, "MCQs", issues)
        for index, item in enumerate(items, 1):
            _required_text(item, ("question", "correct_answer"), f"MCQ {index}", issues)
            if not isinstance(item, dict):
                continue
            options = item.get("options")
            if not isinstance(options, dict) or set(options) != {"A", "B", "C", "D"}:
                issues.append(f"MCQ {index} must contain exactly options A, B, C, and D.")
            elif any(not str(options[key]).strip() for key in ("A", "B", "C", "D")):
                issues.append(f"MCQ {index} contains an empty option.")
            answer = str(item.get("correct_answer", "")).strip().upper()
            if answer not in {"A", "B", "C", "D"}:
                issues.append(f"MCQ {index} correct_answer must be A, B, C, or D.")
    elif resource == "flashcards":
        items = _items(payload, "flashcards", issues)
        _exact_count(items, expected_count, "flashcards", issues)
        for index, item in enumerate(items, 1):
            _required_text(item, ("front", "back"), f"Flashcard {index}", issues)
    elif resource == "summary":
        _required_text(payload, ("short_summary", "detailed_summary"), "Summary", issues)
        _required_list(payload, ("key_concepts", "definitions", "exam_points"), "Summary", issues)
    elif resource == "detailed_notes":
        sections = _items(payload, "sections", issues)
        if not sections:
            issues.append("Detailed notes must contain at least one section.")
        for index, item in enumerate(sections, 1):
            _required_text(item, ("heading",), f"Notes section {index}", issues)
            _required_list(item, ("notes",), f"Notes section {index}", issues)
    elif resource == "key_points":
        _required_list(payload, ("key_points", "important_facts", "exam_tips"), "Key points", issues)
    elif resource == "terminology":
        terms = _items(payload, "terms", issues)
        if not terms:
            issues.append("Terminology must contain at least one term.")
        for index, item in enumerate(terms, 1):
            _required_text(item, ("term", "definition"), f"Term {index}", issues)
    elif resource == "study_guide":
        _required_text(payload, ("overview",), "Study guide", issues)
        _required_list(
            payload,
            ("learning_path", "must_know", "practice_plan", "common_mistakes", "quick_revision"),
            "Study guide",
            issues,
        )
    elif resource == "revision":
        _required_list(
            payload,
            ("must_revise", "definitions", "rules_or_formulas", "exam_tips", "practice_questions", "checklist"),
            "Revision sheet",
            issues,
        )
    elif resource == "study_plan":
        _required_text(payload, ("plan_title", "strategy"), "Study plan", issues)
        schedule = _items(payload, "schedule", issues)
        _exact_count(schedule, expected_count, "schedule periods", issues)
        if not schedule:
            issues.append("Study plan schedule must contain at least one period.")
        for index, item in enumerate(schedule, 1):
            _required_text(item, ("period", "revision", "milestone"), f"Schedule period {index}", issues)
            _required_list(item, ("topics", "objectives", "practice"), f"Schedule period {index}", issues)
        _required_list(payload, ("revision_schedule", "progress_milestones"), "Study plan", issues)
    else:
        issues.append(f"Unknown resource type: {resource}.")
    return issues


def normalize_payload(resource: str, payload: dict[str, Any]) -> None:
    """Repair harmless schema variations before enforcing semantic requirements."""
    if resource == "questions":
        items = payload.get("questions")
        if not isinstance(items, list):
            return
        for item in items:
            if not isinstance(item, dict):
                continue
            _alias(item, "question", ("question_text", "text", "prompt"))
            question = str(item.get("question", "")).strip()
            if question and not question.endswith("?"):
                item["question"] = f"{question.rstrip('.!')}?"
            item.setdefault("type", "Exam Question")
            item.setdefault("difficulty", "Medium")
            item.setdefault("marks", "Not specified")

    elif resource == "mcqs":
        items = payload.get("mcqs")
        if not isinstance(items, list):
            return
        for item in items:
            if not isinstance(item, dict):
                continue
            _alias(item, "question", ("question_text", "text", "prompt"))
            _alias(item, "correct_answer", ("answer", "correct", "correct_option"))
            _alias(item, "explanation", ("reason", "rationale"))
            item.setdefault("explanation", "The selected option is supported by the study material.")
            item["options"] = _normalize_options(item.get("options"))
            answer = str(item.get("correct_answer", "")).strip()
            match = re.search(r"\b([ABCD])\b", answer.upper())
            if match:
                item["correct_answer"] = match.group(1)
            elif isinstance(item["options"], dict):
                for label, option in item["options"].items():
                    if answer.casefold() == str(option).strip().casefold():
                        item["correct_answer"] = label
                        break

    elif resource == "flashcards":
        items = payload.get("flashcards")
        if not isinstance(items, list):
            return
        for item in items:
            if not isinstance(item, dict):
                continue
            _alias(item, "front", ("question", "term", "prompt"))
            _alias(item, "back", ("answer", "definition", "response"))

    elif resource == "detailed_notes":
        sections = payload.get("sections")
        if isinstance(sections, list):
            for item in sections:
                if isinstance(item, dict):
                    _alias(item, "heading", ("title", "topic"))
                    if "notes" not in item and isinstance(item.get("points"), list):
                        item["notes"] = item["points"]

    elif resource == "key_points":
        if "key_points" not in payload and isinstance(payload.get("points"), list):
            payload["key_points"] = payload["points"]
        payload.setdefault("important_facts", [])
        payload.setdefault("exam_tips", [])

    elif resource == "terminology":
        terms = payload.get("terms")
        if isinstance(terms, list):
            for item in terms:
                if isinstance(item, dict):
                    _alias(item, "term", ("name", "keyword"))
                    _alias(item, "definition", ("meaning", "description"))
                    item.setdefault("example", "")

    elif resource == "study_guide":
        payload.setdefault("overview", "")
        for key in ("learning_path", "must_know", "practice_plan", "common_mistakes", "quick_revision"):
            payload.setdefault(key, [])


def render_payload(resource: str, payload: dict[str, Any]) -> str:
    if resource == "questions":
        lines = ["## Important Questions"]
        for index, item in enumerate(payload["questions"], 1):
            lines.extend(
                [
                    f"### {index}. {item['question']}",
                    f"**Type:** {item['type']}  ",
                    f"**Difficulty:** {item['difficulty']}  ",
                    f"**Marks:** {item.get('marks', 'Not specified')}",
                ]
            )
        return "\n\n".join(lines)

    if resource == "mcqs":
        lines = ["## Multiple-Choice Questions"]
        for index, item in enumerate(payload["mcqs"], 1):
            lines.append(f"### {index}. {item['question']}")
            for label in ("A", "B", "C", "D"):
                lines.append(f"- **{label}.** {item['options'][label]}")
            lines.extend(
                [
                    f"\n**Correct answer:** {item['correct_answer'].upper()}",
                    f"**Explanation:** {item['explanation']}",
                ]
            )
        return "\n\n".join(lines)

    if resource == "flashcards":
        lines = ["## Flashcards"]
        for index, item in enumerate(payload["flashcards"], 1):
            lines.extend([f"### Card {index}", f"**Front:** {item['front']}", f"**Back:** {item['back']}"])
        return "\n\n".join(lines)

    if resource == "summary":
        return "\n\n".join(
            [
                "## Short Summary",
                payload["short_summary"],
                "## Detailed Summary",
                payload["detailed_summary"],
                _list_section("Key Concepts", payload["key_concepts"]),
                _definition_section(payload["definitions"]),
                _list_section("Exam-Relevant Points", payload["exam_points"]),
            ]
        )

    if resource == "detailed_notes":
        lines = ["## Detailed Notes"]
        for section in payload["sections"]:
            lines.append(f"### {section['heading']}")
            lines.extend(f"- {note}" for note in section["notes"])
        return "\n\n".join(lines)

    if resource == "key_points":
        return "\n\n".join(
            [
                _list_section("Key Points", payload["key_points"]),
                _list_section("Important Facts", payload["important_facts"]),
                _list_section("Exam Tips", payload["exam_tips"]),
            ]
        )

    if resource == "terminology":
        lines = ["## Terminology"]
        for item in payload["terms"]:
            lines.append(f"### {item['term']}")
            lines.append(item["definition"])
            if str(item.get("example", "")).strip():
                lines.append(f"**Example:** {item['example']}")
        return "\n\n".join(lines)

    if resource == "study_guide":
        return "\n\n".join(
            [
                "## Study Guide",
                payload["overview"],
                _list_section("Learning Path", payload["learning_path"]),
                _list_section("Must-Know Areas", payload["must_know"]),
                _list_section("Practice Plan", payload["practice_plan"]),
                _list_section("Common Mistakes", payload["common_mistakes"]),
                _list_section("Quick Revision", payload["quick_revision"]),
            ]
        )

    if resource == "revision":
        return "\n\n".join(
            [
                _list_section("Must-Revise Concepts", payload["must_revise"]),
                _definition_section(payload["definitions"]),
                _list_section("Formulas or Rules", payload["rules_or_formulas"]),
                _list_section("Exam Tips", payload["exam_tips"]),
                _list_section("Practice Questions", payload["practice_questions"]),
                _list_section("Last-Hour Checklist", payload["checklist"]),
            ]
        )

    if resource == "study_plan":
        lines = [f"## {payload['plan_title']}", payload["strategy"]]
        for item in payload["schedule"]:
            lines.extend(
                [
                    f"### {item['period']}",
                    _list_section("Topics", item["topics"], heading_level=4),
                    _list_section("Learning Objectives", item["objectives"], heading_level=4),
                    _list_section("Practice", item["practice"], heading_level=4),
                    f"#### Revision\n{item['revision']}",
                    f"#### Milestone\n{item['milestone']}",
                ]
            )
        lines.extend(
            [
                _list_section("Revision Schedule", payload["revision_schedule"]),
                _list_section("Progress Milestones", payload["progress_milestones"]),
            ]
        )
        return "\n\n".join(lines)

    raise OutputValidationError(f"Cannot render unknown resource type: {resource}.")


def generate_validated(
    stream_request: Callable[[str, bool], Iterator[str]],
    prompt: str,
    resource: str,
    expected_count: int | None = None,
    attempts: int = 3,
    on_chunk: Callable[[str], None] | None = None,
) -> str:
    payload = generate_validated_payload(
        stream_request=stream_request,
        prompt=prompt,
        resource=resource,
        expected_count=expected_count,
        attempts=attempts,
        on_chunk=on_chunk,
    )
    return render_payload(resource, payload)


def generate_validated_payload(
    stream_request: Callable[[str, bool], Iterator[str]],
    prompt: str,
    resource: str,
    expected_count: int | None = None,
    attempts: int = 3,
    on_chunk: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    logger = get_logger()
    request = prompt
    last_issues: list[str] = []
    last_response = ""

    for attempt in range(attempts):
        logger.info(
            "generation_attempt resource=%s attempt=%s expected_count=%s prompt_chars=%s",
            resource,
            attempt + 1,
            expected_count,
            len(request),
        )
        chunks: list[str] = []
        for chunk in stream_request(request, True):
            chunks.append(chunk)
            if on_chunk:
                on_chunk("".join(chunks))
        last_response = "".join(chunks).strip()
        logger.info(
            "response_received resource=%s attempt=%s response_chars=%s",
            resource,
            attempt + 1,
            len(last_response),
        )

        try:
            payload = extract_json(last_response)
            last_issues = validate_payload(resource, payload, expected_count)
            if not last_issues:
                logger.info("validation_passed resource=%s attempt=%s", resource, attempt + 1)
                return payload
        except OutputValidationError as exc:
            last_issues = [str(exc)]
        logger.warning(
            "validation_failed resource=%s attempt=%s issues=%s",
            resource,
            attempt + 1,
            " | ".join(last_issues),
        )

        if attempt < attempts - 1:
            request = _repair_prompt(prompt, last_response, last_issues)

    detail = "; ".join(last_issues) or "The response did not match the required format."
    raise OutputValidationError(f"Could not produce a valid {resource} output after {attempts} attempts. {detail}")


def _alias(item: dict[str, Any], target: str, alternatives: tuple[str, ...]) -> None:
    if str(item.get(target, "")).strip():
        return
    for key in alternatives:
        if str(item.get(key, "")).strip():
            item[target] = item[key]
            return


def _normalize_options(value: Any) -> dict[str, str] | Any:
    if isinstance(value, dict):
        normalized: dict[str, str] = {}
        for key, option in value.items():
            label_match = re.search(r"[ABCD]", str(key).upper())
            if label_match:
                normalized[label_match.group(0)] = str(option).strip()
        return normalized

    if isinstance(value, list):
        normalized = {}
        for index, option in enumerate(value[:4]):
            label = "ABCD"[index]
            if isinstance(option, dict):
                text = option.get("text") or option.get("option") or option.get("value") or ""
                explicit_label = option.get("label") or option.get("key")
                if explicit_label and re.search(r"[ABCD]", str(explicit_label).upper()):
                    label = re.search(r"[ABCD]", str(explicit_label).upper()).group(0)
                normalized[label] = str(text).strip()
            else:
                text = re.sub(r"^\s*[ABCD][\).:-]\s*", "", str(option), flags=re.IGNORECASE)
                normalized[label] = text.strip()
        return normalized

    return value


def _repair_prompt(original_prompt: str, response: str, issues: list[str]) -> str:
    return f"""{original_prompt}

Your previous response failed validation.
Problems:
{chr(10).join(f"- {issue}" for issue in issues)}

Previous response:
{response}

Return a completely corrected JSON object only. Do not explain the correction."""


def _items(payload: dict[str, Any], key: str, issues: list[str]) -> list[Any]:
    value = payload.get(key)
    if not isinstance(value, list):
        issues.append(f"`{key}` must be a JSON array.")
        return []
    return value


def _exact_count(items: list[Any], expected: int | None, label: str, issues: list[str]) -> None:
    if expected is not None and len(items) != expected:
        issues.append(f"Expected exactly {expected} {label}, received {len(items)}.")


def _required_text(value: Any, keys: tuple[str, ...], label: str, issues: list[str]) -> None:
    if not isinstance(value, dict):
        issues.append(f"{label} must be a JSON object.")
        return
    for key in keys:
        if not str(value.get(key, "")).strip():
            issues.append(f"{label} is missing `{key}`.")


def _required_list(value: Any, keys: tuple[str, ...], label: str, issues: list[str]) -> None:
    if not isinstance(value, dict):
        issues.append(f"{label} must be a JSON object.")
        return
    for key in keys:
        item = value.get(key)
        if not isinstance(item, list) or not item:
            issues.append(f"{label} requires a non-empty `{key}` array.")


def _list_section(title: str, items: list[Any], heading_level: int = 2) -> str:
    lines = [f"{'#' * heading_level} {title}"]
    for item in items:
        if isinstance(item, dict):
            term = item.get("term") or item.get("name") or item.get("question") or "Item"
            detail = item.get("definition") or item.get("detail") or item.get("answer") or ""
            lines.append(f"- **{term}:** {detail}")
        else:
            lines.append(f"- {item}")
    return "\n".join(lines)


def _definition_section(items: list[Any]) -> str:
    return _list_section("Important Definitions", items)
