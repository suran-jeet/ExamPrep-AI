# Software Requirements Specification

# Project Title

**ExamPrep AI - AI-Powered Exam Preparation Assistant**

## Version

Version 1.2 - Hybrid Local and Cloud AI Edition

## 1. Objective

ExamPrep AI converts educational PDFs into predictable, structured exam-preparation resources. Users can generate content with locally hosted Ollama models or their own Google Gemini account.

## 2. Technology Stack

Frontend:
- Streamlit

Backend:
- Python

AI Providers:
- Ollama local runtime
- Google Gemini API through the Google Gen AI SDK

Recommended Local Model:
- Qwen 2.5 7B Instruct (`qwen2.5:7b`)

PDF Processing:
- PyPDF2

Export:
- Markdown
- TXT
- PDF

## 3. Architecture

```text
PDF Upload
   |
Text Extraction
   |
Provider Selection
   |-----------------------|
Ollama Local          Google Gemini
   |-----------------------|
Strict JSON Generation
   |
Schema and Count Validation
   |
Automatic Repair Retry
   |
Rendered Study Resource
```

## 4. Functional Requirements

The system shall:
- upload and validate text-based PDF files
- extract text and display page and word counts
- generate summaries, questions, MCQs, flashcards, revision sheets, and study plans
- generate exactly the quantity selected for questions, MCQs, and flashcards
- require four options, a correct answer, and an explanation for every MCQ
- generate daily or weekly study schedules with topics, objectives, practice, revision, and milestones
- validate structured model output before displaying it
- retry malformed output up to three times
- discover all installed Ollama models automatically
- allow users to enter and validate a Gemini API key and model
- persist provider, model, and theme settings locally
- switch between Ollama and Gemini from one sidebar toggle
- compare outputs across models from the active provider
- export generated content as Markdown, TXT, and PDF
- support persistent light and dark themes

## 5. Model Settings

The dedicated Model Settings view shall provide:
- Ollama host configuration
- installed local model discovery
- Gemini API key entry
- Gemini model-name entry and discovery
- connection validation with actionable errors
- local settings persistence
- a clear privacy notice for cloud generation

## 6. Output Validation

Quantity-based resources shall be represented as JSON arrays and validated for exact length.

MCQs shall be rejected unless every item contains:
- a question
- exactly four options labeled A-D
- a correct answer letter
- an explanation

Study plans shall be rejected unless they contain schedule periods, topics, learning objectives, practice tasks, revision instructions, and milestones.

## 7. Non-Functional Requirements

Reliability:
- The interface shall display only output that passes its resource contract.
- Provider and validation failures shall produce actionable error messages.

Privacy:
- Ollama mode shall keep study material on the user's device.
- Gemini mode shall inform users that extracted content is transmitted to Google.

Usability:
- The interface shall separate the study workspace from model settings.
- Controls shall remain readable and usable on desktop and mobile layouts.

Accessibility:
- Light and dark themes shall maintain readable contrast.
- Theme preference shall persist between sessions.

Security:
- PDFs shall not be permanently stored by the application.
- Gemini credentials shall be stored only in the user's local application-data directory.
- The application shall warn that locally saved API keys are plain text.

## 8. Future Enhancements

- OCR for scanned PDFs
- encrypted credential storage using the operating-system keychain
- chat with notes
- retrieval-augmented generation
- multilingual content generation
- learner progress analytics
