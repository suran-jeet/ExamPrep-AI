from __future__ import annotations

import html
import json
import random
import re
from typing import Any, Callable

import streamlit as st
import streamlit.components.v1 as components


DownloadCallback = Callable[[str, str], None]


def render_output_payload(
    resource: str,
    payload: dict[str, Any],
    *,
    active_model: str,
    provider: str,
    download_callback: DownloadCallback,
) -> None:
    st.divider()
    st.markdown(
        f'<div class="ep-output-meta">Validated output - {escape(active_model)} - {escape(provider)}</div>',
        unsafe_allow_html=True,
    )

    if resource == "summary":
        render_summary(payload)
    elif resource == "questions":
        render_question_bank(payload, download_callback)
    elif resource == "mcqs":
        render_mcq_quiz(payload)
    elif resource == "flashcards":
        render_flashcards(payload)
    elif resource == "detailed_notes":
        render_notes(payload)
    elif resource == "key_points":
        render_key_points(payload)
    elif resource == "terminology":
        render_terminology(payload)
    elif resource == "study_guide":
        render_study_guide(payload)
    elif resource == "revision":
        render_revision(payload)
    elif resource == "study_plan":
        render_study_plan(payload)
    else:
        st.info("Validated structured output is ready. Use Downloads to export it.")


def render_static_preview(resource: str, payload: dict[str, Any]) -> None:
    if resource == "summary":
        render_summary(payload)
    elif resource == "questions":
        for index, item in enumerate(payload.get("questions", [])[:5], 1):
            st.markdown(
                f'<div class="ep-question-card"><b>Question {index}</b><br>{escape(item.get("question", ""))}</div>',
                unsafe_allow_html=True,
            )
    elif resource == "mcqs":
        for index, item in enumerate(payload.get("mcqs", [])[:5], 1):
            options = item.get("options", {})
            option_items = [f"{key}. {options.get(key, '')}" for key in ("A", "B", "C", "D")]
            st.markdown(
                f"""
                <div class="ep-question-card">
                    <b>MCQ {index}</b><br>{escape(item.get("question", ""))}
                    <ul>{html_list(option_items)}</ul>
                    <b>Answer:</b> {escape(item.get("correct_answer", ""))}
                </div>
                """,
                unsafe_allow_html=True,
            )
    elif resource == "flashcards":
        for index, item in enumerate(payload.get("flashcards", [])[:6], 1):
            st.markdown(
                f"""
                <div class="ep-question-card">
                    <b>Card {index}</b><br>
                    <b>Front:</b> {escape(item.get("front", ""))}<br>
                    <b>Back:</b> {escape(item.get("back", ""))}
                </div>
                """,
                unsafe_allow_html=True,
            )
    elif resource == "detailed_notes":
        render_notes(payload)
    elif resource == "key_points":
        render_key_points(payload)
    elif resource == "terminology":
        render_terminology(payload)
    elif resource == "study_guide":
        render_study_guide(payload)
    elif resource == "revision":
        render_revision(payload)
    elif resource == "study_plan":
        render_study_plan(payload)
    else:
        st.info("Validated structured output is ready. Use Downloads to export it.")


def render_summary(payload: dict[str, Any]) -> None:
    st.markdown(f'<div class="ep-callout">{escape(payload.get("short_summary", ""))}</div>', unsafe_allow_html=True)
    st.markdown("### Key Concepts")
    for concept in payload.get("key_concepts", []):
        st.markdown(f'<span class="ep-pill">{escape(concept)}</span>', unsafe_allow_html=True)

    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("### Important Facts")
        st.markdown(f'<div class="ep-card"><ul>{html_list(payload.get("exam_points", []))}</ul></div>', unsafe_allow_html=True)
    with col_b:
        st.markdown("### Definitions")
        definitions = payload.get("definitions", [])
        items = [f"{item.get('term', 'Term')}: {item.get('definition', '')}" for item in definitions if isinstance(item, dict)]
        st.markdown(f'<div class="ep-card"><ul>{html_list(items[:8])}</ul></div>', unsafe_allow_html=True)

    with st.expander("Quick Revision", expanded=False):
        st.write(payload.get("detailed_summary", ""))


def render_question_bank(payload: dict[str, Any], download_callback: DownloadCallback) -> None:
    questions = payload.get("questions", [])
    search = st.text_input("Search questions", placeholder="Search by topic, difficulty, or keyword")
    difficulty = st.segmented_control("Difficulty group", ["All", "Easy", "Medium", "Hard"], default="All")
    selected: list[str] = []

    for index, item in enumerate(questions, 1):
        if not isinstance(item, dict):
            continue
        question = str(item.get("question", ""))
        item_difficulty = str(item.get("difficulty", "Medium"))
        haystack = f"{question} {item_difficulty} {item.get('type', '')}".lower()
        if search and search.lower() not in haystack:
            continue
        if difficulty != "All" and item_difficulty.lower() != str(difficulty).lower():
            continue

        with st.expander(f"Question {index} - {item_difficulty}", expanded=False):
            st.markdown(f"### {question}")
            st.caption(f"{item.get('type', 'Exam Question')} | Marks: {item.get('marks', 'Not specified')}")
            browser_copy_button("Copy Question", question, f"copy_question_{index}")
            if st.checkbox("Select for export", key=f"select_question_{index}"):
                selected.append(f"{index}. {question}")

    if selected:
        download_callback("Selected Questions", "\n".join(selected))


def render_mcq_quiz(payload: dict[str, Any]) -> None:
    mcqs = payload.get("mcqs", [])
    if not mcqs:
        st.caption("No MCQs available yet.")
        return

    answers = dict(st.session_state.quiz_answers)
    submitted = dict(st.session_state.quiz_submitted)
    score = sum(
        1
        for index, item in enumerate(mcqs, 1)
        if submitted.get(str(index)) and answers.get(str(index)) == str(item.get("correct_answer", "")).upper()
    )
    done = sum(1 for index in range(1, len(mcqs) + 1) if submitted.get(str(index)))
    st.progress(done / len(mcqs), text=f"Quiz progress: {done}/{len(mcqs)}")
    st.markdown(f'<div class="ep-card"><b>Score:</b> {score}/{len(mcqs)}</div>', unsafe_allow_html=True)

    for index, item in enumerate(mcqs, 1):
        options = item.get("options", {})
        st.markdown(
            f'<div class="ep-question-card"><b>Question {index} of {len(mcqs)}</b><br>{escape(item.get("question", ""))}</div>',
            unsafe_allow_html=True,
        )
        choice = st.radio(
            "Choose an answer",
            ["A", "B", "C", "D"],
            format_func=lambda key, opts=options: f"{key}. {opts.get(key, '')}",
            key=f"mcq_choice_{index}",
            label_visibility="collapsed",
        )
        answers[str(index)] = choice
        if st.button("Submit", key=f"submit_mcq_{index}"):
            submitted[str(index)] = True
        if submitted.get(str(index)):
            correct = str(item.get("correct_answer", "")).upper()
            if answers.get(str(index)) == correct:
                st.success("Correct")
            else:
                st.error(f"Incorrect. Correct answer: {correct}")
            st.info(f"Explanation: {item.get('explanation', '')}")

    st.session_state.quiz_answers = answers
    st.session_state.quiz_submitted = submitted
    if done == len(mcqs):
        percent = round((score / len(mcqs)) * 100)
        message = "Excellent Performance" if percent >= 80 else "Good Progress" if percent >= 60 else "Review Recommended"
        st.markdown(f'<div class="ep-card"><h2>{percent}%</h2><p>{message}</p></div>', unsafe_allow_html=True)
        incorrect = [
            (index, item)
            for index, item in enumerate(mcqs, 1)
            if answers.get(str(index)) != str(item.get("correct_answer", "")).upper()
        ]
        if incorrect:
            with st.expander("Review incorrect answers", expanded=True):
                for index, item in incorrect:
                    st.markdown(f"**Question {index}:** {item.get('question', '')}")
                    st.caption(f"Correct answer: {item.get('correct_answer', '')}")
                    st.info(item.get("explanation", ""))


def render_flashcards(payload: dict[str, Any]) -> None:
    cards = payload.get("flashcards", [])
    if not cards:
        st.caption("No flashcards available yet.")
        return

    index = min(st.session_state.flashcard_index, len(cards) - 1)
    st.session_state.flashcard_index = index
    card = cards[index]
    side = "back" if st.session_state.flashcard_flipped else "front"
    st.progress((index + 1) / len(cards), text=f"Card {index + 1} of {len(cards)}")
    st.markdown(
        f'<div class="ep-flashcard"><div class="ep-flashcard-text">{escape(card.get(side, ""))}</div></div>',
        unsafe_allow_html=True,
    )

    prev_col, flip_col, shuffle_col, difficult_col, next_col = st.columns(5)
    if prev_col.button("Previous", disabled=index == 0, use_container_width=True):
        st.session_state.flashcard_index = max(0, index - 1)
        st.session_state.flashcard_flipped = False
        st.rerun()
    if flip_col.button("Show Front" if st.session_state.flashcard_flipped else "Flip Card", use_container_width=True):
        st.session_state.flashcard_flipped = not st.session_state.flashcard_flipped
        st.rerun()
    if shuffle_col.button("Shuffle", use_container_width=True):
        st.session_state.flashcard_index = random.randrange(len(cards))
        st.session_state.flashcard_flipped = False
        st.rerun()
    difficult = set(st.session_state.flashcard_difficult)
    if difficult_col.button("Mark Difficult", use_container_width=True):
        difficult.add(index)
        st.session_state.flashcard_difficult = sorted(difficult)
        st.toast("Marked difficult")
    if next_col.button("Next", disabled=index >= len(cards) - 1, use_container_width=True):
        st.session_state.flashcard_index = min(len(cards) - 1, index + 1)
        st.session_state.flashcard_flipped = False
        st.rerun()
    if difficult:
        st.caption(f"{len(difficult)} card(s) marked difficult.")

    st.caption("Keyboard shortcuts: Left/Right for previous/next, Space to flip.")
    components.html(
        """
        <script>
        function clickButton(label) {
          const buttons = Array.from(window.parent.document.querySelectorAll("button"));
          const target = buttons.find((button) => button.innerText.trim() === label && !button.disabled);
          if (target) target.click();
        }
        window.parent.onkeydown = (event) => {
          if (event.target && ["INPUT", "TEXTAREA"].includes(event.target.tagName)) return;
          if (event.key === "ArrowLeft") clickButton("Previous");
          if (event.key === "ArrowRight") clickButton("Next");
          if (event.key === " ") {
            event.preventDefault();
            clickButton("Flip Card") || clickButton("Show Front");
          }
        };
        </script>
        """,
        height=0,
    )


def render_notes(payload: dict[str, Any]) -> None:
    for section in payload.get("sections", []):
        with st.expander(str(section.get("heading", "Section")), expanded=True):
            for note in section.get("notes", []):
                st.markdown(f"- {note}")


def render_key_points(payload: dict[str, Any]) -> None:
    col_a, col_b, col_c = st.columns(3)
    sections = [
        (col_a, "Key Points", payload.get("key_points", [])),
        (col_b, "Important Facts", payload.get("important_facts", [])),
        (col_c, "Exam Tips", payload.get("exam_tips", [])),
    ]
    for column, title, items in sections:
        with column:
            st.markdown(f"### {title}")
            st.markdown(f'<div class="ep-card"><ul>{html_list(items)}</ul></div>', unsafe_allow_html=True)


def render_terminology(payload: dict[str, Any]) -> None:
    search = st.text_input("Search terminology", placeholder="Search term or definition")
    for item in payload.get("terms", []):
        haystack = f"{item.get('term', '')} {item.get('definition', '')}".lower()
        if search and search.lower() not in haystack:
            continue
        with st.expander(str(item.get("term", "Term")), expanded=False):
            st.write(item.get("definition", ""))
            if str(item.get("example", "")).strip():
                st.info(item.get("example", ""))


def render_study_guide(payload: dict[str, Any]) -> None:
    st.markdown(f'<div class="ep-callout">{escape(payload.get("overview", ""))}</div>', unsafe_allow_html=True)
    render_key_points(
        {
            "key_points": payload.get("learning_path", []),
            "important_facts": payload.get("must_know", []),
            "exam_tips": payload.get("quick_revision", []),
        }
    )
    with st.expander("Practice Plan", expanded=True):
        for item in payload.get("practice_plan", []):
            st.markdown(f"- {item}")
    with st.expander("Common Mistakes", expanded=False):
        for item in payload.get("common_mistakes", []):
            st.markdown(f"- {item}")


def render_revision(payload: dict[str, Any]) -> None:
    render_key_points(
        {
            "key_points": payload.get("must_revise", []),
            "important_facts": payload.get("rules_or_formulas", []),
            "exam_tips": payload.get("exam_tips", []),
        }
    )
    with st.expander("Definitions", expanded=False):
        for item in payload.get("definitions", []):
            if isinstance(item, dict):
                st.markdown(f"**{item.get('term', 'Term')}:** {item.get('definition', '')}")
    with st.expander("Practice Questions", expanded=False):
        for item in payload.get("practice_questions", []):
            st.markdown(f"- {item}")


def render_study_plan(payload: dict[str, Any]) -> None:
    st.markdown(f"### {payload.get('plan_title', 'Study Plan')}")
    st.markdown(f'<div class="ep-callout">{escape(payload.get("strategy", ""))}</div>', unsafe_allow_html=True)
    schedule = payload.get("schedule", [])
    completed = sum(1 for index, _ in enumerate(schedule, 1) if st.session_state.get(f"study_plan_done_{index}", False))
    progress = completed / len(schedule) if schedule else 0
    st.progress(progress, text=f"Completion progress: {completed}/{len(schedule)}")

    st.markdown('<div class="ep-timeline">', unsafe_allow_html=True)
    for index, item in enumerate(schedule, 1):
        st.checkbox(f"Mark {item.get('period', f'Period {index}')} complete", key=f"study_plan_done_{index}")
        st.markdown(
            f"""
            <div class="ep-timeline-item">
                <h4>{escape(item.get("period", "Period"))}</h4>
                <b>Topics</b><ul>{html_list(item.get("topics", []))}</ul>
                <b>Objectives</b><ul>{html_list(item.get("objectives", []))}</ul>
                <b>Practice</b><ul>{html_list(item.get("practice", []))}</ul>
                <p><b>Revision:</b> {escape(item.get("revision", ""))}</p>
                <p><b>Milestone:</b> {escape(item.get("milestone", ""))}</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
    st.markdown("</div>", unsafe_allow_html=True)

    with st.expander("Revision Schedule", expanded=True):
        for item in payload.get("revision_schedule", []):
            st.markdown(f"- {item}")


def browser_copy_button(label: str, text: str, key: str) -> None:
    safe_label = html.escape(label)
    text_json = json.dumps(text)
    safe_key = re.sub(r"[^a-zA-Z0-9_]+", "_", key)
    components.html(
        f"""
        <button id="{safe_key}" style="
            border:1px solid #8aa;
            border-radius:8px;
            background:transparent;
            color:inherit;
            cursor:pointer;
            padding:0.35rem 0.65rem;
            font:inherit;
        ">{safe_label}</button>
        <script>
        const button = document.getElementById("{safe_key}");
        button.onclick = async () => {{
          await navigator.clipboard.writeText({text_json});
          button.innerText = "Copied";
          setTimeout(() => button.innerText = "{safe_label}", 1200);
        }};
        </script>
        """,
        height=42,
    )


def html_list(items: list[Any]) -> str:
    return "".join(f"<li>{escape(item)}</li>" for item in items)


def escape(value: Any) -> str:
    return html.escape(str(value))
