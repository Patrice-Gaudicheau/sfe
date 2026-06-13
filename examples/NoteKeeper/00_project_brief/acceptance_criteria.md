# NoteKeeper acceptance criteria

## Project shape

- For the baseline scenario, the generated app must live in `examples/NoteKeeper/10_baseline_full_context_gpt54/app/`.
- For the SFE single-model no-multipass scenario, the generated app must live in `examples/NoteKeeper/20_sfe_single_model_gpt54_nomultipass/app/`.
- For the SFE split-model multipass-auto scenario, the generated app must live in `examples/NoteKeeper/30_sfe_split_gpt54_router_gpt54mini_executor/app/`.
- For the SFE single-model multipass-auto scenario, the generated app must live in `examples/NoteKeeper/40_sfe_single_model_gpt54_multipass/app/`.
- Each scenario app folder must contain exactly the required runtime files: `index.html`, `styles.css`, `app.js`, and `README.md`.
- The app runs by opening `index.html` directly in a modern browser.
- No server, package manager, framework, build step, external dependency, or external asset is required.
- The product is named NoteKeeper in the UI and README.
- The UI is original and does not copy Google Keep branding, logos, protected assets, or exact visual design.

## Core notes workflow

- A user can create a plain text note with an optional title and body.
- A user can edit an existing plain text note and save the changes.
- A user can delete an existing note.
- Note cards display enough content to identify the note.
- Empty title or empty body handling is intentional and does not break rendering.
- The UI shows a useful empty state when no active notes exist.

## Persistence

- Notes are persisted to `localStorage` under a NoteKeeper-specific key.
- Notes remain available after closing and reopening `index.html`.
- Stored data includes the note content and organizational state needed by the app.
- The app starts correctly when no stored data exists.
- The app does not crash permanently when stored JSON is malformed; it recovers to a usable empty state or equivalent safe behavior.

## Labels, search, and archive

- A user can assign labels or categories to a note.
- Labels are displayed on note cards.
- Search matches note titles.
- Search matches plain text note body content.
- Search matches checklist item text.
- Search matches labels.
- Search is case-insensitive or otherwise documented.
- A user can archive an active note.
- Archived notes are hidden from the active notes view.
- A user can switch to an archive view.
- A user can restore an archived note to the active notes view.
- The UI shows a useful empty state when filters or archive state leave no visible notes.

## Checklist notes and pinning

- A user can create a checklist-style note.
- A checklist note can contain multiple items.
- A user can mark checklist items complete and incomplete.
- A user can edit checklist item text.
- A user can remove checklist items.
- Checklist item state persists across reloads.
- A user can pin and unpin active notes.
- Pinned active notes are visually distinguished.
- Pinned active notes appear before unpinned active notes.

## Responsive behavior

- The layout is usable at approximately 360px wide without horizontal scrolling.
- The layout is usable at tablet widths such as approximately 768px.
- The layout uses a simple card arrangement on desktop widths.
- Controls remain usable on touch devices and are not hover-only.
- Text and controls do not visibly overlap at common viewport sizes.

## Accessibility and keyboard use

- Primary controls use semantic HTML elements such as `button`, `input`, and `textarea`.
- Form controls have visible labels or accessible names.
- Keyboard focus is visible.
- A user can tab through creation, search, filtering, and card action controls.
- Card actions can be triggered with the keyboard.
- The app does not require drag and drop.

## README and reviewability

- `README.md` explains how to run the static app.
- `README.md` lists the main supported features.
- `README.md` includes manual verification steps.
- JavaScript and CSS are readable and not minified.
- The implementation avoids unnecessary abstractions and hidden generated code.
