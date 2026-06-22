from __future__ import annotations

from datetime import date
import re
from typing import Any
from dotenv import load_dotenv
import streamlit as st

from src.app_config import AppConfig, config_path, load_config, save_config
from src.credential_store import (
    CredentialStoreError,
    authenticate_windows_user,
    delete_api_key,
    load_api_key,
    save_api_key,
)
from src.diagnostics import get_logger, log_path, read_recent_log
from src.export_utils import as_docx, as_markdown, as_pdf, as_text
from src.gemini_service import GeminiService, GeminiServiceError, RECOMMENDED_GEMINI_MODELS
from src.generation import OutputValidationError, generate_validated_payload, render_payload
from src.llm_service import (
    DEFAULT_OLLAMA_HOST,
    OllamaService,
    OllamaServiceError,
    recommend_model,
    trim_content,
)
from src.pdf_utils import PdfProcessingError, extract_text_from_pdf
from src.planner import calculate_days_remaining, estimate_study_hours
from src.prompts import build_prompt
from src.ui_renderers import browser_copy_button, render_output_payload, render_static_preview


load_dotenv()
logger = get_logger()


RESOURCE_TITLES = {
    "summary": "Summary",
    "detailed_notes": "Detailed Notes",
    "key_points": "Key Points",
    "questions": "Question Bank",
    "mcqs": "MCQs",
    "flashcards": "Flashcards",
    "terminology": "Terminology",
    "study_guide": "Study Guide",
    "revision": "Revision Sheet",
    "study_plan": "Study Plan",
}

COMPARISON_RESOURCES = {
    "Summary": ("summary", {"mode": "Quick Revision"}),
    "Detailed Notes": ("detailed_notes", {}),
    "Key Points": ("key_points", {}),
    "Question Bank": ("questions", {"question_count": 8}),
    "MCQs": ("mcqs", {"mcq_count": 5}),
    "Flashcards": ("flashcards", {"flashcard_type": "Basic", "flashcard_count": 8}),
    "Terminology": ("terminology", {}),
    "Study Guide": ("study_guide", {}),
    "Revision Sheet": ("revision", {}),
}


def init_state() -> None:
    config = load_config()
    try:
        saved_key = load_api_key()
    except CredentialStoreError as exc:
        saved_key = ""
        logger.error("credential_load_failed error=%s", exc)
    defaults = {
        "page": "Study Workspace",
        "provider": config.provider,
        "theme": config.theme,
        "ollama_host": config.ollama_host or DEFAULT_OLLAMA_HOST,
        "selected_ollama_model": "",
        "gemini_api_key": saved_key,
        "gemini_api_key_input": "",
        "gemini_model": config.gemini_model,
        "gemini_models": list(RECOMMENDED_GEMINI_MODELS),
        "gemini_validated": False,
        "revealed_api_key": "",
        "available_models": [],
        "provider_error": "",
        "pdf_text": "",
        "pdf_name": "",
        "page_count": 0,
        "word_count": 0,
        "difficulty_level": "Intermediate",
        "outputs": {},
        "output_payloads": {},
        "comparisons": {},
        "comparison_payloads": {},
        "comparison_title": "",
        "comparison_resource": "",
        "content_trimmed": False,
        "quiz_answers": {},
        "quiz_submitted": {},
        "flashcard_index": 0,
        "flashcard_flipped": False,
        "flashcard_difficult": [],
        "selected_questions": [],
        "last_generation_error": "",
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def current_config() -> AppConfig:
    return AppConfig(
        provider=st.session_state.provider,
        ollama_host=st.session_state.ollama_host,
        gemini_model=st.session_state.gemini_model,
        theme=st.session_state.theme,
    )


@st.cache_data(ttl=15, show_spinner=False)
def discover_ollama_models(host: str) -> tuple[list[str], str]:
    try:
        return OllamaService(host=host).list_models(), ""
    except OllamaServiceError as exc:
        return [], str(exc)


def sync_ollama_models() -> tuple[list[str], str]:
    models, error = discover_ollama_models(st.session_state.ollama_host)
    st.session_state.available_models = models
    if models and st.session_state.selected_ollama_model not in models:
        st.session_state.selected_ollama_model = recommend_model(models) or models[0]
    return models, error


def active_model() -> str:
    if st.session_state.provider == "Gemini":
        return st.session_state.gemini_model
    return st.session_state.selected_ollama_model


def provider_is_ready() -> bool:
    if st.session_state.provider == "Gemini":
        return bool(st.session_state.gemini_api_key.strip() and st.session_state.gemini_model.strip())
    return bool(st.session_state.available_models and st.session_state.selected_ollama_model)


def provider_diagnostic() -> str:
    if st.session_state.provider == "Gemini":
        if not st.session_state.gemini_api_key.strip():
            return "Gemini is selected, but no API key is securely saved. Open Model Settings and save a valid key."
        if not st.session_state.gemini_model.strip():
            return "Gemini is selected, but no model is selected. Open Model Settings and choose a model."
        return ""
    if not st.session_state.available_models:
        return "Ollama is selected, but no running local models were found. Start Ollama or switch to Gemini."
    if not st.session_state.selected_ollama_model:
        return "Ollama is selected, but no local model is selected."
    return ""


def provider_stream(model: str | None = None):
    logger.info(
        "provider_request provider=%s model=%s api_key_present=%s",
        st.session_state.provider,
        model or active_model(),
        bool(st.session_state.gemini_api_key),
    )
    if st.session_state.provider == "Gemini":
        return GeminiService(
            api_key=st.session_state.gemini_api_key,
            model=model or st.session_state.gemini_model,
        ).stream
    return OllamaService(
        host=st.session_state.ollama_host,
        model=model or st.session_state.selected_ollama_model,
    ).stream


def estimated_study_time_label() -> str:
    estimate = estimate_study_hours(
        word_count=st.session_state.word_count,
        page_count=st.session_state.page_count,
        difficulty="Medium",
        days_remaining=7,
    )
    hours = int(estimate.total_hours)
    minutes = round((estimate.total_hours - hours) * 60)
    return f"{hours}h {minutes}m"


def estimated_reading_time_label() -> str:
    minutes = max(1, round(st.session_state.word_count / 220)) if st.session_state.word_count else 0
    hours, mins = divmod(minutes, 60)
    if hours:
        return f"{hours}h {mins}m"
    return f"{mins}m"


def inject_theme(theme: str) -> None:
    dark = theme == "Dark"
    colors = {
        "bg": "#111418" if dark else "#f7f8fa",
        "surface": "#191e24" if dark else "#ffffff",
        "surface_alt": "#20262d" if dark else "#f0f3f5",
        "text": "#edf1f4" if dark else "#17212b",
        "muted": "#aab4bd" if dark else "#62707c",
        "line": "#343c45" if dark else "#d9e0e5",
        "accent": "#2ab3a8" if dark else "#087f7a",
        "accent_hover": "#36c8bc" if dark else "#066b67",
        "danger": "#ff8a78" if dark else "#c94f3b",
    }
    st.markdown(
        f"""
        <style>
        :root {{
            color-scheme: {"dark" if dark else "light"};
            --ep-bg: {colors["bg"]};
            --ep-surface: {colors["surface"]};
            --ep-surface-alt: {colors["surface_alt"]};
            --ep-text: {colors["text"]};
            --ep-muted: {colors["muted"]};
            --ep-line: {colors["line"]};
            --ep-accent: {colors["accent"]};
            --ep-accent-hover: {colors["accent_hover"]};
            --ep-danger: {colors["danger"]};
        }}
        html, body, [data-testid="stAppViewContainer"], .stApp {{
            background: var(--ep-bg);
            color: var(--ep-text);
        }}
        [data-testid="stHeader"] {{ background: color-mix(in srgb, var(--ep-bg) 88%, transparent); }}
        [data-testid="stSidebar"] {{
            background: var(--ep-surface);
            border-right: 1px solid var(--ep-line);
        }}
        .block-container {{
            max-width: 1500px;
            padding: 1.4rem 2rem 3rem;
        }}
        h1, h2, h3, h4, p, label, [data-testid="stMarkdownContainer"] {{
            color: var(--ep-text);
        }}
        .ep-header {{
            border-bottom: 1px solid var(--ep-line);
            margin-bottom: 1.4rem;
            padding-bottom: 1rem;
        }}
        .ep-kicker {{
            color: var(--ep-accent);
            font-size: 0.76rem;
            font-weight: 700;
            margin-bottom: 0.25rem;
            text-transform: uppercase;
        }}
        .ep-title {{ color: var(--ep-text); font-size: 1.9rem; line-height: 1.2; margin: 0; }}
        .ep-subtitle {{ color: var(--ep-muted); margin: 0.35rem 0 0; max-width: 760px; }}
        .ep-status {{
            align-items: center;
            display: flex;
            gap: 0.5rem;
            margin: 0.15rem 0 0.8rem;
        }}
        .ep-dot {{
            background: var(--ep-accent);
            border-radius: 50%;
            display: inline-block;
            height: 0.55rem;
            width: 0.55rem;
        }}
        .ep-dot.offline {{ background: var(--ep-danger); }}
        .ep-status-text {{ color: var(--ep-muted); font-size: 0.82rem; font-weight: 600; }}
        .ep-output-meta {{
            color: var(--ep-muted);
            font-size: 0.82rem;
            margin-bottom: 0.5rem;
        }}
        div[data-baseweb="input"] > div,
        div[data-baseweb="select"] > div,
        div[data-baseweb="textarea"] > div,
        [data-testid="stFileUploader"] section {{
            background: var(--ep-surface);
            border-color: var(--ep-line);
            color: var(--ep-text);
        }}
        input, textarea {{ color: var(--ep-text) !important; }}
        [data-baseweb="popover"], [role="listbox"], [role="dialog"] {{
            background: var(--ep-surface) !important;
            color: var(--ep-text) !important;
        }}
        [role="option"]:hover {{ background: var(--ep-surface-alt) !important; }}
        [data-testid="stMetric"], [data-testid="stExpander"] {{
            background: var(--ep-surface);
            border-color: var(--ep-line);
        }}
        [data-testid="stMetric"] {{
            border-left: 3px solid var(--ep-accent);
            padding: 0.55rem 0.7rem;
        }}
        .ep-hero {{
            background:
                radial-gradient(circle at top left, color-mix(in srgb, var(--ep-accent) 22%, transparent), transparent 32%),
                linear-gradient(135deg, color-mix(in srgb, var(--ep-surface) 92%, var(--ep-accent)), var(--ep-surface));
            border: 1px solid var(--ep-line);
            border-radius: 22px;
            box-shadow: 0 18px 48px color-mix(in srgb, #000 18%, transparent);
            margin-bottom: 1.25rem;
            padding: 1.45rem 1.6rem;
        }}
        .ep-card, .ep-upload-card, .ep-section-card {{
            background: color-mix(in srgb, var(--ep-surface) 94%, transparent);
            border: 1px solid var(--ep-line);
            border-radius: 18px;
            box-shadow: 0 12px 32px color-mix(in srgb, #000 12%, transparent);
            padding: 1rem;
            transition: transform 160ms ease, border-color 160ms ease, box-shadow 160ms ease;
        }}
        .ep-card:hover, .ep-upload-card:hover, .ep-section-card:hover {{
            border-color: color-mix(in srgb, var(--ep-accent) 58%, var(--ep-line));
            box-shadow: 0 16px 42px color-mix(in srgb, #000 16%, transparent);
            transform: translateY(-1px);
        }}
        .ep-metrics {{
            display: grid;
            gap: 0.75rem;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            margin: 1rem 0;
        }}
        .ep-metric-card {{
            background: linear-gradient(145deg, color-mix(in srgb, var(--ep-surface) 88%, var(--ep-accent)), var(--ep-surface));
            border: 1px solid var(--ep-line);
            border-radius: 16px;
            padding: 0.9rem;
        }}
        .ep-metric-label {{ color: var(--ep-muted); font-size: 0.78rem; font-weight: 700; }}
        .ep-metric-value {{ color: var(--ep-text); font-size: 1.55rem; font-weight: 800; margin-top: 0.25rem; }}
        .ep-pill {{
            background: color-mix(in srgb, var(--ep-accent) 16%, transparent);
            border: 1px solid color-mix(in srgb, var(--ep-accent) 38%, var(--ep-line));
            border-radius: 999px;
            color: var(--ep-accent);
            display: inline-flex;
            font-size: 0.78rem;
            font-weight: 800;
            margin: 0 0.35rem 0.35rem 0;
            padding: 0.28rem 0.58rem;
        }}
        .ep-callout {{
            background: color-mix(in srgb, var(--ep-accent) 10%, var(--ep-surface));
            border-left: 4px solid var(--ep-accent);
            border-radius: 14px;
            margin: 0.65rem 0;
            padding: 0.85rem 1rem;
        }}
        .ep-flashcard {{
            align-items: center;
            background: linear-gradient(145deg, color-mix(in srgb, var(--ep-surface) 76%, var(--ep-accent)), var(--ep-surface));
            border: 1px solid color-mix(in srgb, var(--ep-accent) 36%, var(--ep-line));
            border-radius: 22px;
            box-shadow: 0 20px 48px color-mix(in srgb, #000 18%, transparent);
            display: flex;
            min-height: 270px;
            justify-content: center;
            margin: 0.8rem auto;
            max-width: 760px;
            padding: 2rem;
            text-align: center;
        }}
        .ep-flashcard-text {{ font-size: 1.35rem; font-weight: 750; line-height: 1.45; }}
        .ep-question-card {{
            background: var(--ep-surface);
            border: 1px solid var(--ep-line);
            border-radius: 16px;
            margin: 0.7rem 0;
            padding: 0.95rem 1rem;
        }}
        .ep-progress-track {{
            background: var(--ep-surface-alt);
            border-radius: 999px;
            height: 0.7rem;
            overflow: hidden;
            width: 100%;
        }}
        .ep-progress-bar {{
            background: linear-gradient(90deg, var(--ep-accent), #58d68d);
            height: 100%;
        }}
        .ep-timeline {{
            border-left: 3px solid color-mix(in srgb, var(--ep-accent) 58%, var(--ep-line));
            margin-left: 0.75rem;
            padding-left: 1rem;
        }}
        .ep-timeline-item {{
            background: var(--ep-surface);
            border: 1px solid var(--ep-line);
            border-radius: 16px;
            margin: 0 0 0.85rem;
            padding: 0.9rem 1rem;
            position: relative;
        }}
        .ep-timeline-item::before {{
            background: var(--ep-accent);
            border: 3px solid var(--ep-bg);
            border-radius: 50%;
            content: "";
            height: 0.8rem;
            left: -1.52rem;
            position: absolute;
            top: 1rem;
            width: 0.8rem;
        }}
        [data-baseweb="tab-list"] {{ border-bottom: 1px solid var(--ep-line); gap: 0.15rem; }}
        [data-baseweb="tab"] {{
            border-radius: 999px 999px 0 0;
            color: var(--ep-muted);
            padding-left: 0.75rem;
            padding-right: 0.75rem;
            transition: background 160ms ease, color 160ms ease, transform 160ms ease;
        }}
        [data-baseweb="tab"]:hover {{
            background: color-mix(in srgb, var(--ep-accent) 10%, transparent);
            color: var(--ep-text);
            transform: translateY(-1px);
        }}
        [aria-selected="true"][data-baseweb="tab"] {{
            background: color-mix(in srgb, var(--ep-accent) 14%, transparent);
            color: var(--ep-text);
        }}
        .stButton > button, .stDownloadButton > button {{
            background: var(--ep-surface);
            border-color: var(--ep-line);
            border-radius: 6px;
            color: var(--ep-text);
        }}
        .stButton > button:hover, .stDownloadButton > button:hover {{
            border-color: var(--ep-accent);
            color: var(--ep-accent);
        }}
        .stButton > button[kind="primary"] {{
            background: var(--ep-accent);
            border-color: var(--ep-accent);
            color: #ffffff;
        }}
        .stButton > button[kind="primary"]:hover {{
            background: var(--ep-accent-hover);
            color: #ffffff;
        }}
        @keyframes epFlip {{
            from {{ transform: rotateY(-7deg) scale(0.985); opacity: 0.82; }}
            to {{ transform: rotateY(0deg) scale(1); opacity: 1; }}
        }}
        .ep-flashcard {{
            animation: epFlip 220ms ease;
        }}
        [data-testid="stAlert"] {{
            background: var(--ep-surface);
            border-color: var(--ep-line);
            color: var(--ep-text);
        }}
        hr {{ border-color: var(--ep-line); }}
        @media (max-width: 800px) {{
            .block-container {{ padding: 1rem 1rem 2rem; }}
            .ep-title {{ font-size: 1.55rem; }}
            [data-baseweb="tab-list"] {{ overflow-x: auto; }}
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def save_preferences() -> None:
    save_config(current_config())
    logger.info(
        "preferences_saved provider=%s model=%s theme=%s",
        st.session_state.provider,
        active_model(),
        st.session_state.theme,
    )


def open_model_settings() -> None:
    st.session_state.page = "Model Settings"


def render_sidebar() -> None:
    with st.sidebar:
        st.markdown("## ExamPrep AI")
        st.radio(
            "Navigation",
            ["Study Workspace", "Model Settings"],
            key="page",
            label_visibility="collapsed",
        )

        st.divider()
        use_gemini = st.toggle("Use Gemini cloud", value=st.session_state.provider == "Gemini")
        new_provider = "Gemini" if use_gemini else "Ollama"
        if new_provider != st.session_state.provider:
            st.session_state.provider = new_provider
            save_preferences()
            st.rerun()

        use_dark = st.toggle("Dark mode", value=st.session_state.theme == "Dark")
        new_theme = "Dark" if use_dark else "Light"
        if new_theme != st.session_state.theme:
            st.session_state.theme = new_theme
            save_preferences()
            st.rerun()

        st.divider()
        if st.session_state.provider == "Ollama":
            models, error = sync_ollama_models()
            if models:
                recommended = recommend_model(models)
                st.markdown(
                    f'<div class="ep-status"><span class="ep-dot"></span>'
                    f'<span class="ep-status-text">Local AI ready · {len(models)} model(s)</span></div>',
                    unsafe_allow_html=True,
                )
                if st.session_state.page == "Study Workspace":
                    st.selectbox(
                        "Active model",
                        models,
                        key="selected_ollama_model",
                        format_func=lambda value: f"{value} (Recommended)" if value == recommended else value,
                    )
                else:
                    st.caption(f"Active model: `{st.session_state.selected_ollama_model}`")
            else:
                st.markdown(
                    '<div class="ep-status"><span class="ep-dot offline"></span>'
                    '<span class="ep-status-text">Ollama unavailable</span></div>',
                    unsafe_allow_html=True,
                )
                st.caption(error or "No local model is installed.")
        else:
            ready = provider_is_ready()
            state_class = "" if ready else " offline"
            label = "Gemini configured" if ready else "Gemini needs setup"
            st.markdown(
                f'<div class="ep-status"><span class="ep-dot{state_class}"></span>'
                f'<span class="ep-status-text">{label}</span></div>',
                unsafe_allow_html=True,
            )
            if st.session_state.gemini_model:
                st.caption(f"Model: `{st.session_state.gemini_model}`")

        st.button("Open Model Settings", use_container_width=True, on_click=open_model_settings)

        st.divider()
        left, right = st.columns(2)
        left.metric("Pages", st.session_state.page_count)
        right.metric("Words", st.session_state.word_count)
        st.caption(f"Study time: {estimated_study_time_label()}")
        if st.session_state.pdf_name:
            st.caption(st.session_state.pdf_name)


def stream_validated_resource(resource: str, model: str | None = None, **kwargs: object) -> tuple[str, dict[str, Any]] | None:
    if not st.session_state.pdf_text.strip():
        st.error("No extracted document text is available. Upload a PDF and click Extract text first.")
        logger.error("generation_blocked reason=no_extracted_text resource=%s", resource)
        return None

    diagnostic = provider_diagnostic()
    if diagnostic:
        st.error(diagnostic)
        logger.error("generation_blocked reason=provider_not_ready detail=%s", diagnostic)
        return None

    content, trimmed = trim_content(st.session_state.pdf_text)
    st.session_state.content_trimmed = trimmed
    prompt = build_prompt(resource, content=content, **kwargs)
    logger.info(
        "prompt_created resource=%s provider=%s model=%s source_chars=%s prompt_chars=%s trimmed=%s",
        resource,
        st.session_state.provider,
        model or active_model(),
        len(st.session_state.pdf_text),
        len(prompt),
        trimmed,
    )
    expected_count = {
        "questions": kwargs.get("question_count"),
        "mcqs": kwargs.get("mcq_count"),
        "flashcards": kwargs.get("flashcard_count"),
        "study_plan": kwargs.get("schedule_periods"),
    }.get(resource)

    progress = st.progress(0, text="Extracting PDF...")
    status = st.empty()
    status.info("Extracted text is ready. Preparing the prompt.")
    progress.progress(22, text="Preparing Prompt...")

    def update_progress(raw: str) -> None:
        received = min(78, 35 + len(raw) // 240)
        progress.progress(received, text="Generating Content...")
        status.info(f"Generating with {model or active_model()} - {len(raw):,} characters received.")

    try:
        status.info("Generating content and validating the selected format.")
        payload = generate_validated_payload(
            stream_request=provider_stream(model),
            prompt=prompt,
            resource=resource,
            expected_count=int(expected_count) if expected_count is not None else None,
            attempts=3,
            on_chunk=update_progress,
        )
        progress.progress(90, text="Validating Format...")
        output = render_payload(resource, payload)
        progress.progress(100, text="Rendering Output...")
    except (OllamaServiceError, GeminiServiceError, OutputValidationError) as exc:
        progress.empty()
        status.empty()
        logger.exception(
            "generation_failed resource=%s provider=%s model=%s error=%s",
            resource,
            st.session_state.provider,
            model or active_model(),
            exc,
        )
        st.error(f"{RESOURCE_TITLES.get(resource, resource.title())} generation failed: {exc}")
        st.caption(f"Diagnostic log: `{log_path()}`")
        return None

    status.success("Format validated and rendered.")
    return output, payload


def generate_resource(resource: str, model: str | None = None, **kwargs: object) -> None:
    output = stream_validated_resource(resource, model=model, **kwargs)
    if output:
        body, payload = output
        outputs = dict(st.session_state.outputs)
        payloads = dict(st.session_state.output_payloads)
        outputs[resource] = body
        payloads[resource] = payload
        st.session_state.outputs = outputs
        st.session_state.output_payloads = payloads
        st.success(f"{RESOURCE_TITLES[resource]} generated and format-validated.")


def payload_for(resource: str) -> dict[str, Any]:
    payload = st.session_state.output_payloads.get(resource, {})
    return payload if isinstance(payload, dict) else {}


def render_static_payload_preview(resource: str, payload: dict[str, Any]) -> None:
    render_static_preview(resource, payload)


def render_output(resource: str) -> None:
    output = st.session_state.outputs.get(resource)
    if not output:
        st.caption("Generated content will appear here.")
        return
    render_output_payload(
        resource,
        payload_for(resource),
        active_model=active_model(),
        provider=st.session_state.provider,
        download_callback=render_download_buttons,
    )
def render_pdf_panel() -> None:
    st.markdown('<div class="ep-upload-card">', unsafe_allow_html=True)
    st.subheader("Source Material")
    st.caption("Drag and drop a text-based PDF. Extract it once, then generate any study resource.")
    uploaded_file = st.file_uploader("Choose PDF notes", type=["pdf"], label_visibility="collapsed")
    if uploaded_file is None:
        st.info("Drop your PDF here to begin.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    size_mb = uploaded_file.size / (1024 * 1024) if uploaded_file.size else 0
    st.markdown(
        f"""
        <div class="ep-card">
            <div style="display:flex; gap:0.8rem; align-items:center;">
                <div style="font-size:2.4rem;">📘</div>
                <div>
                    <b>{uploaded_file.name}</b><br>
                    <span class="ep-output-meta">PDF - {size_mb:.1f} MB</span>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    action_a, action_b = st.columns(2)
    action_a.caption("Replace file by choosing another PDF above.")
    if action_b.button("Remove source", use_container_width=True):
        st.session_state.pdf_text = ""
        st.session_state.pdf_name = ""
        st.session_state.page_count = 0
        st.session_state.word_count = 0
        st.session_state.outputs = {}
        st.session_state.output_payloads = {}
        st.session_state.comparisons = {}
        st.session_state.comparison_payloads = {}
        st.rerun()

    if st.button("Extract text", type="primary", use_container_width=True):
        try:
            extract_progress = st.progress(0, text="Extracting PDF...")
            result = extract_text_from_pdf(uploaded_file, filename=uploaded_file.name, size=uploaded_file.size)
            extract_progress.progress(100, text="Text extracted")
            st.session_state.pdf_text = result.text
            st.session_state.pdf_name = uploaded_file.name
            st.session_state.page_count = result.page_count
            st.session_state.word_count = result.word_count
            st.session_state.outputs = {}
            st.session_state.output_payloads = {}
            st.session_state.comparisons = {}
            st.session_state.comparison_payloads = {}
            st.session_state.quiz_answers = {}
            st.session_state.quiz_submitted = {}
            st.session_state.flashcard_index = 0
            st.session_state.flashcard_flipped = False
            logger.info(
                "pdf_extracted filename=%s pages=%s words=%s chars=%s",
                uploaded_file.name,
                result.page_count,
                result.word_count,
                len(result.text),
            )
            st.success("Text extracted.")
        except PdfProcessingError as exc:
            logger.exception("pdf_extraction_failed filename=%s error=%s", uploaded_file.name, exc)
            st.error(str(exc))

    if st.session_state.pdf_text:
        st.markdown(
            f"""
            <div class="ep-card">
                <b>Extracted Source</b><br>
                <span class="ep-output-meta">
                    {st.session_state.page_count} pages - {st.session_state.word_count} words - {estimated_reading_time_label()} reading time
                </span>
            </div>
            """,
            unsafe_allow_html=True,
        )
        with st.expander("Extracted text preview"):
            st.text_area("Preview", st.session_state.pdf_text[:5000], height=260, disabled=True, label_visibility="collapsed")
    st.markdown("</div>", unsafe_allow_html=True)


def generation_is_disabled() -> bool:
    return not st.session_state.pdf_text or not provider_is_ready()


def render_metric_cards() -> None:
    resource_count = len(st.session_state.outputs)
    st.markdown(
        f"""
        <div class="ep-metrics">
            <div class="ep-metric-card"><div class="ep-metric-label">📄 Pages</div><div class="ep-metric-value">{st.session_state.page_count}</div></div>
            <div class="ep-metric-card"><div class="ep-metric-label">📝 Words</div><div class="ep-metric-value">{st.session_state.word_count}</div></div>
            <div class="ep-metric-card"><div class="ep-metric-label">⏱ Reading Time</div><div class="ep-metric-value">{estimated_reading_time_label()}</div></div>
            <div class="ep-metric-card"><div class="ep-metric-label">🎯 Study Time</div><div class="ep-metric-value">{estimated_study_time_label()}</div></div>
            <div class="ep-metric-card"><div class="ep-metric-label">📈 Difficulty</div><div class="ep-metric-value">{st.session_state.difficulty_level}</div></div>
            <div class="ep-metric-card"><div class="ep-metric-label">✅ Resources</div><div class="ep-metric-value">{resource_count}</div></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_summary_tab() -> None:
    action, control = st.columns([2, 1])
    mode = control.segmented_control("Detail", ["Quick Revision", "Detailed"], default="Quick Revision")
    if action.button("Generate summary", type="primary", disabled=generation_is_disabled(), use_container_width=True):
        generate_resource("summary", mode=mode)
    render_output("summary")


def render_detailed_notes_tab() -> None:
    if st.button("Generate detailed notes", type="primary", disabled=generation_is_disabled(), use_container_width=True):
        generate_resource("detailed_notes")
    render_output("detailed_notes")


def render_key_points_tab() -> None:
    if st.button("Generate key points", type="primary", disabled=generation_is_disabled(), use_container_width=True):
        generate_resource("key_points")
    render_output("key_points")


def render_questions_tab() -> None:
    action, control = st.columns([2, 1])
    count = control.number_input("Number of questions", min_value=1, max_value=50, value=8, step=1)
    if action.button("Generate questions", type="primary", disabled=generation_is_disabled(), use_container_width=True):
        generate_resource("questions", question_count=int(count))
    render_output("questions")


def render_mcq_tab() -> None:
    action, control = st.columns([2, 1])
    count = control.number_input("Number of MCQs", min_value=1, max_value=40, value=10, step=1)
    if action.button("Generate MCQs", type="primary", disabled=generation_is_disabled(), use_container_width=True):
        generate_resource("mcqs", mcq_count=int(count))
    render_output("mcqs")


def render_flashcards_tab() -> None:
    action, kind_col, count_col = st.columns([2, 1, 1])
    card_type = kind_col.selectbox("Card type", ["Basic", "Definition", "Formula"])
    count = count_col.number_input("Number of cards", min_value=1, max_value=60, value=20, step=1)
    if action.button("Generate flashcards", type="primary", disabled=generation_is_disabled(), use_container_width=True):
        generate_resource("flashcards", flashcard_type=card_type, flashcard_count=int(count))
    render_output("flashcards")


def render_terminology_tab() -> None:
    if st.button("Generate terminology", type="primary", disabled=generation_is_disabled(), use_container_width=True):
        generate_resource("terminology")
    render_output("terminology")


def render_study_guide_tab() -> None:
    if st.button("Generate study guide", type="primary", disabled=generation_is_disabled(), use_container_width=True):
        generate_resource("study_guide")
    render_output("study_guide")


def render_revision_tab() -> None:
    if st.button("Generate revision sheet", type="primary", disabled=generation_is_disabled(), use_container_width=True):
        generate_resource("revision")
    render_output("revision")


def render_study_plan_tab() -> None:
    date_col, difficulty_col = st.columns(2)
    exam_date = date_col.date_input("Exam date", value=date.today())
    difficulty = difficulty_col.selectbox("Subject difficulty", ["Easy", "Medium", "Hard"], index=1)
    days = calculate_days_remaining(exam_date)
    estimate = estimate_study_hours(
        word_count=st.session_state.word_count,
        page_count=st.session_state.page_count,
        difficulty=difficulty,
        days_remaining=days,
    )
    schedule_style = "daily" if days <= 14 else "weekly"
    schedule_periods = max(1, min(days or 1, 14)) if schedule_style == "daily" else max(2, min(12, (days + 6) // 7))

    metric_a, metric_b, metric_c = st.columns(3)
    metric_a.metric("Days remaining", estimate.days_remaining)
    metric_b.metric("Daily hours", estimate.daily_hours)
    metric_c.metric("Schedule", f"{schedule_periods} {schedule_style} periods")

    if st.button("Generate study plan", type="primary", disabled=generation_is_disabled(), use_container_width=True):
        generate_resource(
            "study_plan",
            exam_date=exam_date.isoformat(),
            days_remaining=estimate.days_remaining,
            difficulty=difficulty,
            page_count=st.session_state.page_count,
            word_count=st.session_state.word_count,
            daily_hours=estimate.daily_hours,
            schedule_style=schedule_style,
            schedule_periods=schedule_periods,
        )
    render_output("study_plan")


def provider_model_options() -> list[str]:
    if st.session_state.provider == "Gemini":
        models = st.session_state.gemini_models
        current = st.session_state.gemini_model
        return list(dict.fromkeys(([current] if current else []) + models))
    return st.session_state.available_models


def render_model_comparison_tab() -> None:
    st.subheader("Model comparison")
    models = provider_model_options()
    type_col, model_col = st.columns([1, 2])
    title = type_col.selectbox("Output type", list(COMPARISON_RESOURCES))
    defaults = models[: min(3, len(models))]
    selected = model_col.multiselect("Models", models, default=defaults)
    disabled = not st.session_state.pdf_text or not selected

    if st.button("Compare models", type="primary", disabled=disabled, use_container_width=True):
        resource, kwargs = COMPARISON_RESOURCES[title]
        comparisons: dict[str, str] = {}
        comparison_payloads: dict[str, dict[str, Any]] = {}
        for model in selected:
            st.caption(f"Generating with {model}")
            output = stream_validated_resource(resource, model=model, **kwargs)
            if output:
                body, payload = output
                comparisons[model] = body
                comparison_payloads[model] = payload
        st.session_state.comparisons = comparisons
        st.session_state.comparison_payloads = comparison_payloads
        st.session_state.comparison_title = title
        st.session_state.comparison_resource = resource

    if st.session_state.comparisons:
        for model, body in st.session_state.comparisons.items():
            with st.expander(model, expanded=True):
                payload = st.session_state.comparison_payloads.get(model, {})
                render_static_payload_preview(st.session_state.get("comparison_resource", ""), payload)
                render_download_buttons(f"{st.session_state.comparison_title} - {model}", body)
    else:
        st.caption("Select models from the active provider to compare validated outputs.")


def filename_safe(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_") or "examprep_output"


def render_download_buttons(title: str, body: str) -> None:
    base = filename_safe(title)
    markdown_col, text_col, docx_col, pdf_col = st.columns(4)
    markdown_col.download_button(
        "Markdown",
        as_markdown(title, body),
        file_name=f"{base}.md",
        mime="text/markdown",
        use_container_width=True,
    )
    text_col.download_button(
        "TXT",
        as_text(title, body),
        file_name=f"{base}.txt",
        mime="text/plain",
        use_container_width=True,
    )
    try:
        docx_col.download_button(
            "DOCX",
            as_docx(title, body),
            file_name=f"{base}.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            use_container_width=True,
        )
    except RuntimeError as exc:
        docx_col.caption(str(exc))
    try:
        pdf_col.download_button(
            "PDF",
            as_pdf(title, body),
            file_name=f"{base}.pdf",
            mime="application/pdf",
            use_container_width=True,
        )
    except RuntimeError as exc:
        pdf_col.caption(str(exc))


def render_download_center() -> None:
    st.subheader("Downloads")
    if not st.session_state.outputs:
        st.caption("Generated resources will appear here.")
        return
    for resource, body in st.session_state.outputs.items():
        title = RESOURCE_TITLES.get(resource, resource.title())
        with st.expander(title):
            render_download_buttons(title, body)


def render_workspace() -> None:
    st.markdown(
        """
        <div class="ep-hero">
            <div class="ep-kicker">ExamPrep AI</div>
            <h1 class="ep-title">Turn notes into active study sessions.</h1>
            <p class="ep-subtitle">Generate validated summaries, quizzes, flashcards, study guides, and revision plans from your PDF using local Ollama or Google Gemini.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    diagnostic = provider_diagnostic()
    if diagnostic:
        st.warning(diagnostic)

    source_col, tools_col = st.columns([0.78, 1.9], gap="large")
    with source_col:
        render_pdf_panel()
        render_metric_cards()
    with tools_col:
        if st.session_state.content_trimmed:
            st.warning("The source was shortened to fit the model context limit.")
        tabs = st.tabs(
            [
                "📘 Summary",
                "📝 Detailed Notes",
                "🔑 Key Points",
                "❓ Question Bank",
                "🎯 MCQs",
                "🃏 Flashcards",
                "📚 Terminology",
                "🧭 Study Guide",
                "🔁 Revision",
                "📅 Study Plan",
                "⚖ Compare",
                "⬇ Downloads",
            ]
        )
        with tabs[0]:
            render_summary_tab()
        with tabs[1]:
            render_detailed_notes_tab()
        with tabs[2]:
            render_key_points_tab()
        with tabs[3]:
            render_questions_tab()
        with tabs[4]:
            render_mcq_tab()
        with tabs[5]:
            render_flashcards_tab()
        with tabs[6]:
            render_terminology_tab()
        with tabs[7]:
            render_study_guide_tab()
        with tabs[8]:
            render_revision_tab()
        with tabs[9]:
            render_study_plan_tab()
        with tabs[10]:
            render_model_comparison_tab()
        with tabs[11]:
            render_download_center()


def render_model_settings() -> None:
    st.markdown(
        """
        <div class="ep-header">
            <div class="ep-kicker">AI configuration</div>
            <h1 class="ep-title">Model Settings</h1>
            <p class="ep-subtitle">Choose local processing or Gemini cloud generation, validate connections, and store preferences on this computer.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    provider_tab, appearance_tab = st.tabs(["Providers", "Appearance"])

    with provider_tab:
        st.subheader("Ollama local models")
        st.caption("PDF content remains on this computer when Ollama is active.")
        st.text_input("Ollama host", key="ollama_host")
        local_models, local_error = sync_ollama_models()
        local_action, local_status = st.columns([1, 2])
        if local_action.button("Refresh local models", use_container_width=True):
            discover_ollama_models.clear()
            st.rerun()
        if local_models:
            local_status.success(f"Connected. Found {len(local_models)} installed model(s).")
            st.selectbox("Preferred local model", local_models, key="selected_ollama_model")
        else:
            local_status.error(local_error or "No local models found.")
            st.code("ollama pull qwen2.5:7b", language="powershell")

        st.divider()
        st.subheader("Google Gemini")
        st.caption("Gemini sends the extracted study material to Google's API. Usage may be subject to quota or billing.")
        key_state = "Saved securely" if st.session_state.gemini_api_key else "Not saved"
        st.markdown(f'<span class="ep-pill">API key: {key_state}</span>', unsafe_allow_html=True)
        st.text_input(
            "New Gemini API key",
            key="gemini_api_key_input",
            type="password",
            placeholder="Paste a key only when saving or replacing it",
        )
        model_options = list(
            dict.fromkeys(
                ([st.session_state.gemini_model] if st.session_state.gemini_model else [])
                + st.session_state.gemini_models
                + RECOMMENDED_GEMINI_MODELS
            )
        )
        st.selectbox("Gemini model", model_options, key="gemini_model")

        validate_col, save_col, reveal_col = st.columns(3)
        if validate_col.button("Test connection", use_container_width=True):
            key_to_test = st.session_state.gemini_api_key_input.strip() or st.session_state.gemini_api_key
            if not key_to_test:
                st.error("Enter a Gemini API key or save one before testing.")
            else:
                with st.spinner("Testing API key, model availability, network, and quota..."):
                    result = GeminiService(
                        api_key=key_to_test,
                        model=st.session_state.gemini_model,
                    ).test_connection()
                st.session_state.gemini_models = result.models or list(RECOMMENDED_GEMINI_MODELS)
                st.session_state.gemini_validated = result.ok
                logger.info(
                    "gemini_connection_test ok=%s model=%s models=%s message=%s",
                    result.ok,
                    st.session_state.gemini_model,
                    len(result.models),
                    result.message,
                )
                if result.ok:
                    st.success(result.message)
                else:
                    st.error(result.message)

        if save_col.button("Save and use Gemini", type="primary", use_container_width=True):
            key_to_save = st.session_state.gemini_api_key_input.strip() or st.session_state.gemini_api_key
            if not key_to_save:
                st.error("Enter a Gemini API key before saving.")
            else:
                try:
                    with st.spinner("Validating and saving Gemini settings..."):
                        service = GeminiService(api_key=key_to_save, model=st.session_state.gemini_model)
                        result = service.test_connection()
                        if not result.ok:
                            raise GeminiServiceError(result.message)
                        save_api_key(key_to_save)
                    st.session_state.gemini_api_key = key_to_save
                    st.session_state.gemini_models = result.models or list(RECOMMENDED_GEMINI_MODELS)
                    st.session_state.gemini_validated = True
                    st.session_state.provider = "Gemini"
                    path = save_config(current_config())
                    logger.info("gemini_saved model=%s config=%s", st.session_state.gemini_model, path)
                    st.success("Gemini configuration saved securely and activated.")
                except (GeminiServiceError, CredentialStoreError) as exc:
                    st.session_state.gemini_validated = False
                    logger.exception("gemini_save_failed model=%s error=%s", st.session_state.gemini_model, exc)
                    st.error(str(exc))

        if reveal_col.button("Show API key", use_container_width=True):
            try:
                if not st.session_state.gemini_api_key:
                    st.info("No Gemini key is saved.")
                elif authenticate_windows_user():
                    st.session_state.revealed_api_key = st.session_state.gemini_api_key
                else:
                    st.info("Device authentication was cancelled.")
            except CredentialStoreError as exc:
                st.error(str(exc))

        if st.session_state.revealed_api_key:
            st.text_input("Saved API key", value=st.session_state.revealed_api_key, type="password", disabled=True)
            browser_copy_button("Copy API key", st.session_state.revealed_api_key, "copy_gemini_api_key")

        delete_col, prefs_col = st.columns(2)
        if delete_col.button("Remove saved Gemini key", use_container_width=True):
            try:
                delete_api_key()
                st.session_state.gemini_api_key = ""
                st.session_state.revealed_api_key = ""
                st.session_state.gemini_validated = False
                st.success("Saved Gemini key removed from this device.")
            except CredentialStoreError as exc:
                st.error(str(exc))

        if prefs_col.button("Save provider preferences", use_container_width=True):
            path = save_config(current_config())
            st.success(f"Settings saved locally to {path}.")

        st.info(
            "Gemini API keys are encrypted with Windows Data Protection API for the current Windows user. "
            "Saved keys are masked by default and require device authentication before reveal."
        )

        with st.expander("Diagnostics"):
            st.caption(f"Log file: `{log_path()}`")
            st.code(read_recent_log(), language="text")

    with appearance_tab:
        st.subheader("Theme")
        selected_theme = st.segmented_control(
            "Application theme",
            ["Light", "Dark"],
            default=st.session_state.theme,
        )
        if selected_theme and selected_theme != st.session_state.theme:
            st.session_state.theme = selected_theme
            save_preferences()
            st.rerun()
        st.caption("Theme preference is saved locally and restored the next time the app opens.")

    st.caption(f"Configuration file: `{config_path()}`")


def main() -> None:
    st.set_page_config(page_title="ExamPrep AI", page_icon="E", layout="wide")
    init_state()
    inject_theme(st.session_state.theme)
    render_sidebar()
    if st.session_state.page == "Model Settings":
        render_model_settings()
    else:
        render_workspace()


if __name__ == "__main__":
    main()
