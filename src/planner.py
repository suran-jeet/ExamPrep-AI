from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import math


DIFFICULTY_MULTIPLIERS = {
    "Easy": 0.9,
    "Medium": 1.15,
    "Hard": 1.45,
}


@dataclass(frozen=True)
class StudyEstimate:
    days_remaining: int
    total_hours: float
    daily_hours: float
    markdown: str


def calculate_days_remaining(exam_date: date, today: date | None = None) -> int:
    base_date = today or date.today()
    return max(0, (exam_date - base_date).days)


def estimate_study_hours(word_count: int, page_count: int, difficulty: str, days_remaining: int) -> StudyEstimate:
    multiplier = DIFFICULTY_MULTIPLIERS.get(difficulty, DIFFICULTY_MULTIPLIERS["Medium"])
    reading_hours = word_count / 1800 if word_count else page_count * 0.08
    practice_hours = max(1.5, page_count * 0.08)
    revision_hours = max(1.0, reading_hours * 0.35)
    total_hours = max(3.0, (reading_hours + practice_hours + revision_hours) * multiplier)

    available_days = max(1, days_remaining)
    daily_hours = min(8.0, max(0.5, total_hours / available_days))
    daily_hours = math.ceil(daily_hours * 2) / 2

    markdown = build_local_plan(days_remaining, total_hours, daily_hours, difficulty)
    return StudyEstimate(
        days_remaining=days_remaining,
        total_hours=round(total_hours, 1),
        daily_hours=round(daily_hours, 1),
        markdown=markdown,
    )


def build_local_plan(days_remaining: int, total_hours: float, daily_hours: float, difficulty: str) -> str:
    if days_remaining <= 0:
        timeline = [
            "Block 1: scan headings, definitions, and formulas.",
            "Block 2: revise high-weight concepts and solved examples.",
            "Block 3: attempt MCQs and short-answer questions.",
            "Block 4: do a final recall pass without looking at notes.",
        ]
    elif days_remaining == 1:
        timeline = [
            "Morning: finish core concepts and definitions.",
            "Afternoon: practice MCQs and short-answer questions.",
            "Evening: revise formulas, diagrams, and likely long answers.",
            "Night: quick recall pass and rest.",
        ]
    elif days_remaining <= 3:
        timeline = [
            "Day 1: understand the chapter map and mark weak areas.",
            "Day 2: practice important questions and MCQs.",
            "Final day: revise definitions, formulas, and mistakes.",
        ]
    else:
        timeline = [
            "First 40% of days: learn and summarize the material.",
            "Middle 40% of days: solve MCQs, short answers, and long answers.",
            "Final 20% of days: rapid revision, weak-topic repair, and mock tests.",
        ]

    plan_lines = "\n".join(f"- {item}" for item in timeline)
    return f"""## Days Remaining
{days_remaining}

## Daily Study Hours
{daily_hours} hours per day

## Total Study Estimate
{round(total_hours, 1)} hours for a {difficulty.lower()} subject.

## Revision Plan
{plan_lines}

## Practice Slots
- Reserve at least 30% of each session for active recall.
- Use generated MCQs first, then important questions.
- Review incorrect answers before starting the next session.

## Final-Day Strategy
- Focus on definitions, formulas, diagrams, and frequently asked questions.
- Avoid starting large new topics unless they are high weight.
- Sleep enough to preserve recall."""
