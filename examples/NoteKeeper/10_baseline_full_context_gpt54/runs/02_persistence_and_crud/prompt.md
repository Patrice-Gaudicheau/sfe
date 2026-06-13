# NoteKeeper full-context baseline task

You are executing one task in a five-step benchmark. This is the baseline run: use the full context below. Do not use SFE routing, discovery, or context reduction.

Return only strict JSON with this exact shape:

```json
{
  "files": [
    {"path": "index.html", "content": "..."},
    {"path": "styles.css", "content": "..."},
    {"path": "app.js", "content": "..."},
    {"path": "README.md", "content": "..."}
  ],
  "notes": "optional short implementation notes"
}
```

Rules for your response:
- Return JSON only, with no markdown fences or explanatory text.
- Include exactly the four required files.
- Use only these paths: index.html, styles.css, app.js, README.md.
- Provide complete replacement contents for every file on every task.
- Do not include external dependencies, package files, server code, or extra files.
- The app must remain runnable by opening index.html directly in a browser.

## Product brief

# NoteKeeper product request

I want to build a small browser-only notes application called NoteKeeper. The point of the project is not to create another huge productivity suite, and it is definitely not to copy Google Keep's brand, artwork, layout, color system, icons, or protected assets. The inspiration is only the broad idea that a person can quickly capture small bits of information as cards, find them later, and keep the interface light enough that it does not get in the way.

The app should feel like a practical local-first tool that someone could open from a folder on their computer and use immediately. It should be implemented as a static web application with only `index.html`, `styles.css`, `app.js`, and `README.md`. There should be no Symfony, no PHP, no Node build step, no server, no bundler, no package manager, no external dependency, and no external assets. I should be able to double-click `index.html` or open it directly in a browser and use the whole application.

The product name is NoteKeeper. Please use that name in the interface and documentation. The visual direction should be original and restrained: clean typography, a clear workspace, simple cards, and controls that are easy to understand. Avoid making it look like a clone of any existing branded notes app. Do not use any logos, icons, fonts, illustrations, screenshots, or images from outside the project. If icons are needed, use text labels or simple inline characters that are not dependent on icon libraries.

At a high level, NoteKeeper should let me create notes, edit them later, delete notes I no longer need, organize them with labels or categories, search through them, pin the notes that matter most, and archive notes that I want out of the main view without permanently deleting them. It should support both regular plain text notes and checklist-style notes. It does not need accounts, syncing, collaboration, rich text editing, reminders, drawing, image uploads, server storage, or import/export. Keep it small, readable, and easy to manually review.

The first screen should be the actual app, not a landing page. I expect a header with the app name, a search field, and a clear way to switch between active notes and archived notes. There should be an obvious note creation area where I can enter a title, body text, and optional labels. For note type, I should be able to choose between a plain text note and a checklist note. For checklist notes, I should be able to add multiple checklist items, mark items complete or incomplete, edit item text, and remove items while editing.

The note cards should show the title when present, the body or checklist content, labels, and useful actions such as edit, delete, pin or unpin, archive or restore. Pinned notes should be visually distinguished and should appear before unpinned notes in the active notes view. Archived notes should not appear in the active notes view, but they should be visible in an archive view where they can be restored or deleted. Deleting can be immediate; a complex trash system is not required.

Data must persist in `localStorage`. If I create a few notes, close the browser tab, and reopen `index.html`, the notes should still be there. Use a clear storage key that belongs to NoteKeeper. The saved data should include note title, body, note type, checklist items and checked states, labels, pinned state, archived state, creation time, and update time if useful. The app should tolerate an empty store. It should also avoid crashing if the stored JSON is missing, empty, or malformed; a simple reset to an empty list is acceptable if parsing fails.

Search should work across note title, body text, checklist item text, and labels. It can be case-insensitive and simple substring matching. Labels do not need a full management screen, but users should be able to add labels to notes as comma-separated text or an equivalent simple control. Label display should be readable on each card. If search or the active/archive filter leaves no visible notes, show a helpful empty state instead of leaving a blank area.

The layout should use responsive note cards. On a small phone-sized viewport, the cards should stack in a single column and the creation/editing controls should remain usable without horizontal scrolling. On medium and desktop widths, cards can flow into a simple grid. The interface should not rely on hover-only controls because it should remain usable on touch devices. The page should feel usable at common widths like 360px, 768px, and desktop browser sizes.

Accessibility matters even for this small benchmark. Use semantic HTML where it fits: buttons for actions, labels for form inputs, and headings where they clarify structure. Interactive controls should be reachable by keyboard. Focus states should be visible. Form controls should have accessible names. The app should not require drag and drop. Keyboard interaction does not need to be elaborate, but a user should be able to tab through the main controls, type a note, save it, search, and activate card actions.

Please keep the code clear enough for manual review. Since this is a benchmark project, readability matters more than cleverness. Use plain JavaScript with straightforward state management, rendering, and event handling. Avoid minification and avoid unnecessary abstractions. Comments are welcome where they explain important decisions, but the code should mostly explain itself through good names and simple structure.

Manual testing expectations are part of the request. After implementation, I would expect a reviewer to open `index.html` directly in a browser and verify the main flows: create a text note, create a checklist note, edit both kinds of note, delete a note, add labels, search by title/body/label/checklist item, pin and unpin notes, archive and restore a note, reload the page to confirm persistence, and resize the browser to check the responsive layout. The README should explain how to run the app and list the main supported features and manual test steps.

For this benchmark, do not expand scope beyond the static local app. Do not introduce a framework, server, build tool, dependency, test runner, external API, analytics, authentication, or remote persistence. The finished project should remain a small, self-contained example that makes it easy to compare development workflows and review the generated files.

## Acceptance criteria

# NoteKeeper acceptance criteria

## Project shape

- For the baseline scenario, the generated app must live in `examples/NoteKeeper/10_baseline_full_context_gpt54/app/`.
- For the SFE single-model scenario, the generated app must live in `examples/NoteKeeper/20_sfe_single_model_gpt54/app/`.
- For the SFE split-model scenario, the generated app must live in `examples/NoteKeeper/30_sfe_split_gpt54_router_gpt54mini_executor/app/`.
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


## Full task sequence

# NoteKeeper task sequence

Use the same five tasks for every benchmark scenario. Each task should build on the previous task without changing the product brief or acceptance criteria.

## 1. Initial static scaffold

Create the initial static application files: `index.html`, `styles.css`, `app.js`, and `README.md`. Establish the NoteKeeper name, app shell, note creation form, placeholder card area, active/archive navigation controls, and baseline styling. The app should open directly in a browser without a server.

## 2. LocalStorage persistence and CRUD

Implement note creation, rendering, editing, deletion, and `localStorage` persistence for plain text notes. Use a NoteKeeper-specific storage key. Include safe startup behavior for missing or malformed stored data. Confirm notes survive a browser reload.

## 3. Labels, search, and archive

Add labels or categories, display labels on note cards, implement search across title, body, checklist text when present, and labels, and add archive and restore behavior. Active notes and archived notes should be separated by the view controls. Add empty states for no notes and no filtered results.

## 4. Checklist notes and pinning

Add checklist-style notes with multiple editable items, checked and unchecked states, item removal, and persistence. Add pinning and unpinning for active notes. Pinned notes should be visually distinguished and sorted before unpinned notes.

## 5. Responsive polish, accessibility pass, and README

Polish the responsive card layout for phone, tablet, and desktop widths. Improve keyboard navigation, visible focus states, labels, button names, and semantic structure. Finalize the README with run instructions, feature list, storage notes, and manual test steps.

## Current task

## 2. LocalStorage persistence and CRUD

Implement note creation, rendering, editing, deletion, and `localStorage` persistence for plain text notes. Use a NoteKeeper-specific storage key. Include safe startup behavior for missing or malformed stored data. Confirm notes survive a browser reload.

## Current generated app files

### index.html

```text
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>NoteKeeper</title>
  <link rel="stylesheet" href="styles.css">
</head>
<body>
  <div class="app-shell">
    <header class="site-header">
      <div>
        <p class="eyebrow">Local notes workspace</p>
        <h1>NoteKeeper</h1>
      </div>

      <div class="header-controls">
        <label class="search-field">
          <span class="sr-only">Search notes</span>
          <input
            id="searchInput"
            type="search"
            placeholder="Search notes, labels, or checklist items"
            aria-label="Search notes"
          >
        </label>

        <nav class="view-switcher" aria-label="Note views">
          <button type="button" class="view-button is-active" data-view="active" aria-pressed="true">
            Active notes
          </button>
          <button type="button" class="view-button" data-view="archive" aria-pressed="false">
            Archived
          </button>
        </nav>
      </div>
    </header>

    <main class="main-layout">
      <section class="composer card" aria-labelledby="composerTitle">
        <div class="section-heading">
          <h2 id="composerTitle">Create a note</h2>
          <p>Quickly capture plain text or checklist notes.</p>
        </div>

        <form id="noteForm" class="note-form">
          <div class="field-row">
            <label class="field">
              <span>Title</span>
              <input id="noteTitle" name="title" type="text" placeholder="Optional title">
            </label>
          </div>

          <div class="field-row two-column">
            <label class="field">
              <span>Note type</span>
              <select id="noteType" name="type">
                <option value="text">Plain text</option>
                <option value="checklist">Checklist</option>
              </select>
            </label>

            <label class="field">
              <span>Labels</span>
              <input id="noteLabels" name="labels" type="text" placeholder="work, ideas, personal">
            </label>
          </div>

          <label class="field" id="textBodyField">
            <span>Body</span>
            <textarea id="noteBody" name="body" rows="5" placeholder="Write your note here"></textarea>
          </label>

          <div id="checklistEditor" class="checklist-editor" hidden>
            <div class="field">
              <span>Checklist items</span>
              <div class="checklist-placeholder">
                <p>Checklist item controls will appear here in the next implementation step.</p>
                <button type="button" class="secondary-button" disabled>Add item</button>
              </div>
            </div>
          </div>

          <div class="form-actions">
            <button type="submit" class="primary-button">Save note</button>
            <button type="reset" class="secondary-button">Clear</button>
          </div>
        </form>
      </section>

      <section class="notes-panel">
        <div class="section-heading">
          <h2 id="notesSectionTitle">Notes</h2>
          <p id="notesSectionSubtitle">Your saved notes will appear here.</p>
        </div>

        <div id="notesGrid" class="notes-grid" aria-live="polite">
          <article class="note-card card placeholder-card">
            <div class="note-card-header">
              <div>
                <p class="note-meta">Sample text note</p>
                <h3>Welcome to NoteKeeper</h3>
              </div>
              <span class="pin-indicator" aria-hidden="true">Pinned</span>
            </div>
            <p>
              This baseline scaffold shows the app shell, creation form, view switcher, and responsive card layout.
            </p>
            <ul class="label-list" aria-label="Labels">
              <li>sample</li>
              <li>starter</li>
            </ul>
            <div class="card-actions">
              <button type="button" class="text-button" disabled>Edit</button>
              <button type="button" class="text-button" disabled>Archive</button>
              <button type="button" class="text-button" disabled>Delete</button>
            </div>
          </article>

          <article class="note-card card placeholder-card">
            <div class="note-card-header">
              <div>
                <p class="note-meta">Sample checklist note</p>
                <h3>Weekend errands</h3>
              </div>
            </div>
            <ul class="checklist-preview">
              <li><span aria-hidden="true">☐</span> Pick up groceries</li>
              <li><span aria-hidden="true">☑</span> Call the repair shop</li>
              <li><span aria-hidden="true">☐</span> Water the plants</li>
            </ul>
            <ul class="label-list" aria-label="Labels">
              <li>home</li>
              <li>todo</li>
            </ul>
            <div class="card-actions">
              <button type="button" class="text-button" disabled>Edit</button>
              <button type="button" class="text-button" disabled>Archive</button>
              <button type="button" class="text-button" disabled>Delete</button>
            </div>
          </article>
        </div>

        <div id="emptyState" class="empty-state card" hidden>
          <h3>No notes to show</h3>
          <p>Create a note or switch views to see archived items.</p>
        </div>
      </section>
    </main>
  </div>

  <script src="app.js"></script>
</body>
</html>

```

### styles.css

```text
:root {
  --bg: #f4f6fb;
  --surface: #ffffff;
  --surface-alt: #eef2f8;
  --border: #d8deea;
  --text: #1f2937;
  --muted: #5f6b7a;
  --accent: #2f6fed;
  --accent-soft: #e7efff;
  --danger: #b14242;
  --shadow: 0 10px 30px rgba(28, 39, 60, 0.08);
  --radius: 16px;
}

* {
  box-sizing: border-box;
}

html,
body {
  margin: 0;
  padding: 0;
}

body {
  font-family: Arial, Helvetica, sans-serif;
  background: linear-gradient(180deg, #f8faff 0%, var(--bg) 100%);
  color: var(--text);
  line-height: 1.5;
}

button,
input,
textarea,
select {
  font: inherit;
}

button,
input,
textarea,
select {
  border-radius: 12px;
}

button:focus-visible,
input:focus-visible,
textarea:focus-visible,
select:focus-visible {
  outline: 3px solid rgba(47, 111, 237, 0.35);
  outline-offset: 2px;
}

.app-shell {
  width: min(1200px, calc(100% - 2rem));
  margin: 0 auto;
  padding: 1rem 0 2rem;
}

.site-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 1rem;
  padding: 1rem 0 1.5rem;
}

.site-header h1,
.section-heading h2,
.note-card h3,
.empty-state h3 {
  margin: 0;
}

.eyebrow,
.section-heading p,
.note-meta {
  margin: 0;
  color: var(--muted);
}

.eyebrow {
  font-size: 0.85rem;
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

.header-controls {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 0.75rem;
  align-items: center;
}

.search-field input {
  width: min(360px, 100%);
  min-width: 220px;
  padding: 0.85rem 1rem;
  border: 1px solid var(--border);
  background: var(--surface);
}

.view-switcher {
  display: inline-flex;
  gap: 0.5rem;
  padding: 0.35rem;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 14px;
}

.view-button {
  border: 0;
  background: transparent;
  color: var(--muted);
  padding: 0.7rem 1rem;
  cursor: pointer;
}

.view-button.is-active {
  background: var(--accent-soft);
  color: var(--accent);
  font-weight: 700;
}

.main-layout {
  display: grid;
  grid-template-columns: minmax(280px, 360px) 1fr;
  gap: 1.25rem;
  align-items: start;
}

.card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
}

.composer,
.notes-panel {
  padding: 1rem;
}

.section-heading {
  margin-bottom: 1rem;
}

.note-form {
  display: grid;
  gap: 1rem;
}

.field-row.two-column {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 1rem;
}

.field {
  display: grid;
  gap: 0.45rem;
}

.field span {
  font-weight: 700;
}

.field input,
.field textarea,
.field select {
  width: 100%;
  padding: 0.8rem 0.9rem;
  border: 1px solid var(--border);
  background: #fff;
  color: var(--text);
}

.field textarea {
  resize: vertical;
  min-height: 130px;
}

.checklist-editor {
  padding: 0.85rem;
  border: 1px dashed var(--border);
  border-radius: 14px;
  background: var(--surface-alt);
}

.checklist-placeholder {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.checklist-placeholder p {
  margin: 0;
  color: var(--muted);
}

.form-actions,
.card-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
}

.primary-button,
.secondary-button,
.text-button {
  border: 1px solid var(--border);
  padding: 0.75rem 1rem;
  background: var(--surface);
  color: var(--text);
  cursor: pointer;
}

.primary-button {
  background: var(--accent);
  border-color: var(--accent);
  color: #fff;
}

.secondary-button {
  background: var(--surface-alt);
}

.text-button {
  padding: 0.55rem 0.85rem;
}

button:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.notes-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 1rem;
}

.note-card {
  padding: 1rem;
}

.note-card-header {
  display: flex;
  justify-content: space-between;
  gap: 0.75rem;
  align-items: flex-start;
  margin-bottom: 0.75rem;
}

.pin-indicator {
  display: inline-flex;
  align-items: center;
  padding: 0.3rem 0.6rem;
  border-radius: 999px;
  background: #fff3cd;
  color: #7a5a00;
  font-size: 0.85rem;
  white-space: nowrap;
}

.checklist-preview,
.label-list {
  margin: 0.75rem 0 0;
  padding-left: 1.1rem;
}

.label-list {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  padding: 0;
  list-style: none;
}

.label-list li {
  padding: 0.3rem 0.6rem;
  border-radius: 999px;
  background: var(--surface-alt);
  color: var(--muted);
  border: 1px solid var(--border);
  font-size: 0.85rem;
}

.placeholder-card {
  min-height: 220px;
}

.empty-state {
  margin-top: 1rem;
  padding: 1.25rem;
  text-align: center;
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

@media (max-width: 900px) {
  .main-layout {
    grid-template-columns: 1fr;
  }

  .site-header {
    flex-direction: column;
  }

  .header-controls {
    width: 100%;
    justify-content: stretch;
  }

  .search-field {
    flex: 1 1 100%;
  }

  .search-field input {
    width: 100%;
    min-width: 0;
  }
}

@media (max-width: 600px) {
  .app-shell {
    width: min(100% - 1rem, 1200px);
  }

  .field-row.two-column {
    grid-template-columns: 1fr;
  }

  .view-switcher,
  .form-actions,
  .card-actions {
    width: 100%;
  }

  .view-button,
  .primary-button,
  .secondary-button,
  .text-button {
    flex: 1 1 auto;
  }

  .notes-grid {
    grid-template-columns: 1fr;
  }
}

```

### app.js

```text
const noteTypeSelect = document.getElementById('noteType');
const textBodyField = document.getElementById('textBodyField');
const checklistEditor = document.getElementById('checklistEditor');
const viewButtons = document.querySelectorAll('.view-button');
const notesSectionTitle = document.getElementById('notesSectionTitle');
const notesSectionSubtitle = document.getElementById('notesSectionSubtitle');

function updateComposerMode() {
  const isChecklist = noteTypeSelect.value === 'checklist';
  textBodyField.hidden = isChecklist;
  checklistEditor.hidden = !isChecklist;
}

function updateViewButtons(selectedView) {
  viewButtons.forEach((button) => {
    const isActive = button.dataset.view === selectedView;
    button.classList.toggle('is-active', isActive);
    button.setAttribute('aria-pressed', String(isActive));
  });

  if (selectedView === 'archive') {
    notesSectionTitle.textContent = 'Archived notes';
    notesSectionSubtitle.textContent = 'Archived notes will appear here in a later step.';
  } else {
    notesSectionTitle.textContent = 'Notes';
    notesSectionSubtitle.textContent = 'Your saved notes will appear here.';
  }
}

noteTypeSelect.addEventListener('change', updateComposerMode);

viewButtons.forEach((button) => {
  button.addEventListener('click', () => {
    updateViewButtons(button.dataset.view);
  });
});

document.getElementById('noteForm').addEventListener('submit', (event) => {
  event.preventDefault();
  window.alert('This baseline scaffold sets up the interface. Saving notes will be implemented in the next step.');
});

updateComposerMode();
updateViewButtons('active');

```

### README.md

```text
# NoteKeeper

NoteKeeper is a small browser-only notes app scaffold designed to open directly from `index.html` with no server, build step, or external dependencies.

## Run

1. Download or copy the four app files into the same folder:
   - `index.html`
   - `styles.css`
   - `app.js`
   - `README.md`
2. Open `index.html` directly in a modern browser.

## Current baseline scaffold

This first step provides:

- NoteKeeper app shell and header
- Search input
- Active and archived view toggle buttons
- Note creation form
- Plain text vs checklist note type selector
- Placeholder checklist editor area
- Responsive sample note cards
- Baseline accessibility-friendly form labels and buttons

## Notes

- This is the initial static scaffold task.
- Note saving, editing, deletion, search behavior, archive behavior, checklist persistence, pinning, and `localStorage` support are planned for later steps in the benchmark sequence.
- The UI is intentionally original and lightweight, without external assets or frameworks.

## Manual review suggestions

Open `index.html` and verify:

1. The page loads directly from the file system.
2. The header shows the NoteKeeper name.
3. The search field and Active notes / Archived controls are visible.
4. The creation form includes title, note type, labels, and body fields.
5. Switching the note type to `Checklist` hides the text body area and shows the checklist placeholder.
6. The sample notes display in responsive cards.
7. The layout remains usable at narrow mobile widths and wider desktop widths.
8. Keyboard focus is visible when tabbing through controls.

```
