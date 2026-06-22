# Development Log - ExamPrep AI

## Project Summary

ExamPrep AI is a Streamlit-based educational study assistant that converts text-based PDF notes into interactive learning resources. It supports local Ollama models for offline/private generation and Google Gemini models for cloud generation.

## Development Timeline

### Phase 1: Core Application Setup

- Created Streamlit application structure.
- Added PDF upload and text extraction using `PyPDF2`.
- Added source validation for PDF format, file size, encryption, and empty text extraction.
- Built initial study-resource generation flow.
- Added support for summaries, questions, MCQs, flashcards, revision sheets, and study plans.

### Phase 2: Local AI Integration

- Replaced API-key-only AI flow with local Ollama support.
- Added automatic Ollama model discovery.
- Added local model recommendation, preferring `qwen2.5:7b`.
- Added sidebar provider switching between Ollama and Gemini.
- Added model comparison support for the active provider.

### Phase 3: Gemini Integration

- Added Google Gemini provider support using `google-genai`.
- Added secure Gemini API key storage with Windows Data Protection API.
- Added masked API key display by default.
- Added Windows device authentication before revealing saved API keys.
- Replaced manual Gemini model entry with dropdown-based model selection.
- Added Gemini connection testing.

### Phase 4: Gemini Reliability Upgrade

- Added automatic retry with exponential backoff for temporary Gemini failures.
- Added fallback model chain:

```text
gemini-2.5-flash -> gemini-2.0-flash -> gemini-1.5-flash
```

- Added user-friendly error messages for:
  - Gemini overload
  - quota or rate-limit failures
  - invalid API keys
  - unavailable models
  - network timeouts
- Prevented raw API/JSON errors from being shown directly to users.

### Phase 5: Structured Generation And Validation

- Added strict JSON prompt contracts for every output type.
- Added response JSON extraction.
- Added output normalization for common model mistakes.
- Added exact-count validation for:
  - Question Bank
  - MCQs
  - Flashcards
  - Study Plan periods
- Added automatic repair prompts when model output fails validation.
- Added logging for prompt creation, provider selection, response handling, validation success, and validation failure.

### Phase 6: Interactive Output Rendering

- Replaced raw AI text display with dedicated renderers in `src/ui_renderers.py`.
- Added Summary renderer with:
  - overview callout
  - key concepts
  - definitions
  - important facts
  - quick revision section
- Added Question Bank renderer with:
  - expandable question cards
  - search
  - difficulty filtering
  - copy question button
  - selected-question export
- Added MCQ quiz renderer with:
  - radio options
  - submit answer
  - correct/incorrect feedback
  - explanation display
  - score tracking
  - progress bar
  - incorrect-answer review
  - final result message
- Added Flashcard renderer with:
  - large card UI
  - flip action
  - previous/next navigation
  - shuffle
  - mark difficult
  - progress tracking
  - keyboard navigation
- Added Terminology renderer with searchable glossary cards.
- Added Study Plan renderer with:
  - timeline layout
  - daily/weekly schedule
  - completion checkboxes
  - progress visualization
- Added Study Guide and Revision renderers with structured card layouts.

### Phase 7: UI And UX Redesign

- Redesigned the app toward a premium educational SaaS style.
- Added custom theme-aware CSS.
- Improved dark mode and light mode consistency.
- Added metric cards for:
  - pages
  - words
  - reading time
  - estimated study time
  - difficulty level
  - generated resource count
- Improved PDF source panel with:
  - file metadata
  - file size
  - extracted source metrics
  - replace/remove source flow
- Added icon-based tab navigation.
- Added staged generation progress:
  - Extracting PDF
  - Preparing Prompt
  - Generating Content
  - Validating Format
  - Rendering Output

### Phase 8: Exports

- Added Markdown export.
- Added TXT export.
- Added PDF export using `reportlab`.
- Added DOCX export using `python-docx`.
- Added export support for every generated resource.

### Phase 9: Architecture Cleanup

- Separated major responsibilities:
  - `app.py`: Streamlit shell, navigation, settings, generation flow
  - `src/gemini_service.py`: Gemini provider, retry, fallback, connection testing
  - `src/llm_service.py`: Ollama provider and local model discovery
  - `src/generation.py`: JSON parsing, validation, normalization, repair
  - `src/ui_renderers.py`: interactive output rendering
  - `src/pdf_utils.py`: PDF validation and extraction
  - `src/export_utils.py`: Markdown, TXT, DOCX, PDF export
  - `src/credential_store.py`: secure API key storage
  - `src/diagnostics.py`: diagnostic logging
  - `src/prompts.py`: structured prompt templates
  - `src/planner.py`: study-time estimation

## Final Features

- Local Ollama AI support.
- Google Gemini support.
- Secure Gemini key storage.
- Gemini retry and fallback models.
- Interactive study dashboard.
- PDF extraction and source metrics.
- Summary generation.
- Detailed notes generation.
- Key points generation.
- Question bank generation.
- MCQ quiz generation.
- Flashcard generation.
- Terminology generation.
- Study guide generation.
- Revision sheet generation.
- Study plan generation.
- Model comparison.
- Markdown, TXT, DOCX, and PDF exports.
- Light/dark theme support.
- Diagnostic logging.

## Testing Performed

### Static Checks

- Python compile check:

```powershell
.\.venv\Scripts\python.exe -m compileall app.py src
```

### Generation Validation Tests

Validated that:

- question outputs normalize missing punctuation and missing difficulty
- MCQ outputs normalize A-D options
- flashcards validate exact count
- summaries validate required sections
- terminology validates term/definition structure
- study plans validate schedule periods and milestones

### Gemini Reliability Helper Tests

Validated that:

- fallback model sequence is correct
- `503 UNAVAILABLE` becomes a friendly overload message
- invalid API-key errors become user-friendly key messages

### Export Tests

Validated:

- Markdown export
- TXT export
- DOCX export
- PDF export

### Streamlit Smoke Tests

Validated:

- Study Workspace page loads without exceptions
- Model Settings page loads without exceptions
- sidebar navigation does not trigger session state errors

### Runtime Check

Validated:

```text
http://localhost:8501 -> HTTP 200
```

## Known Limitations

- Scanned image PDFs require OCR before upload.
- Local Ollama performance depends on the user's CPU/GPU/RAM and selected model.
- Gemini requires internet access and available Google AI quota.
- Windows device authentication for API key reveal is implemented for Windows environments.

## Submission Files

- `app.py`
- `src/`
- `README.md`
- `requirements.txt`
- `DEVELOPMENT_LOG.md`
- `SRS.md`

