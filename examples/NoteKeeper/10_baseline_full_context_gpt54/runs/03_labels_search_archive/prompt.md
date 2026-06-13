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

## 3. Labels, search, and archive

Add labels or categories, display labels on note cards, implement search across title, body, checklist text when present, and labels, and add archive and restore behavior. Active notes and archived notes should be separated by the view controls. Add empty states for no notes and no filtered results.

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
          <p>Capture plain text notes and keep them stored in your browser.</p>
        </div>

        <form id="noteForm" class="note-form">
          <input id="editingNoteId" type="hidden" value="">

          <div class="field-row">
            <label class="field" for="noteTitle">
              <span>Title</span>
              <input id="noteTitle" name="title" type="text" placeholder="Optional title">
            </label>
          </div>

          <div class="field-row two-column">
            <label class="field" for="noteType">
              <span>Note type</span>
              <select id="noteType" name="type">
                <option value="text">Plain text</option>
                <option value="checklist" disabled>Checklist (coming next step)</option>
              </select>
            </label>

            <label class="field" for="noteLabels">
              <span>Labels</span>
              <input id="noteLabels" name="labels" type="text" placeholder="Labels will be enabled in the next step" disabled>
            </label>
          </div>

          <label class="field" id="textBodyField" for="noteBody">
            <span>Body</span>
            <textarea id="noteBody" name="body" rows="6" placeholder="Write your note here"></textarea>
          </label>

          <div id="checklistEditor" class="checklist-editor" hidden>
            <div class="field">
              <span>Checklist items</span>
              <div class="checklist-placeholder">
                <p>Checklist note editing will be added in a later step.</p>
                <button type="button" class="secondary-button" disabled>Add item</button>
              </div>
            </div>
          </div>

          <div class="form-actions">
            <button id="saveButton" type="submit" class="primary-button">Save note</button>
            <button id="cancelEditButton" type="button" class="secondary-button" hidden>Cancel edit</button>
            <button type="reset" class="secondary-button">Clear</button>
          </div>
        </form>
      </section>

      <section class="notes-panel">
        <div class="section-heading">
          <h2 id="notesSectionTitle">Notes</h2>
          <p id="notesSectionSubtitle">Your saved notes appear here and stay available after reloads.</p>
        </div>

        <div id="notesGrid" class="notes-grid" aria-live="polite"></div>

        <div id="emptyState" class="empty-state card" hidden>
          <h3>No notes yet</h3>
          <p>Create your first note using the form on the left.</p>
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
  --danger-soft: #fff1f1;
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
.note-meta,
.note-date,
.note-label-placeholder {
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

.field input:disabled,
.field select:disabled {
  background: #f4f6fa;
  color: var(--muted);
  cursor: not-allowed;
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

.checklist-placeholder p,
.note-body,
.empty-state p {
  margin: 0;
}

.form-actions,
.card-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
}

.primary-button,
.secondary-button,
.text-button,
.danger-button {
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

.text-button,
.danger-button {
  padding: 0.55rem 0.85rem;
}

.danger-button {
  color: var(--danger);
  background: var(--danger-soft);
  border-color: #efcaca;
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

.note-card-header h3 {
  word-break: break-word;
}

.note-meta {
  font-size: 0.9rem;
}

.note-date {
  font-size: 0.85rem;
  margin-top: 0.85rem;
}

.note-body {
  white-space: pre-wrap;
  word-break: break-word;
}

.note-body.is-empty {
  color: var(--muted);
  font-style: italic;
}

.note-label-placeholder {
  font-size: 0.9rem;
  margin-top: 0.75rem;
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
  .text-button,
  .danger-button {
    flex: 1 1 auto;
  }

  .notes-grid {
    grid-template-columns: 1fr;
  }
}

```

### app.js

```text
const STORAGE_KEY = 'notekeeper.notes';

const noteForm = document.getElementById('noteForm');
const editingNoteIdInput = document.getElementById('editingNoteId');
const noteTitleInput = document.getElementById('noteTitle');
const noteBodyInput = document.getElementById('noteBody');
const noteTypeSelect = document.getElementById('noteType');
const textBodyField = document.getElementById('textBodyField');
const checklistEditor = document.getElementById('checklistEditor');
const cancelEditButton = document.getElementById('cancelEditButton');
const saveButton = document.getElementById('saveButton');
const notesGrid = document.getElementById('notesGrid');
const emptyState = document.getElementById('emptyState');
const viewButtons = document.querySelectorAll('.view-button');
const notesSectionTitle = document.getElementById('notesSectionTitle');
const notesSectionSubtitle = document.getElementById('notesSectionSubtitle');

let notes = loadNotes();
let currentView = 'active';

function loadNotes() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);

    if (!raw) {
      return [];
    }

    const parsed = JSON.parse(raw);

    if (!Array.isArray(parsed)) {
      return [];
    }

    return parsed
      .filter((item) => item && typeof item === 'object')
      .map((item) => ({
        id: typeof item.id === 'string' ? item.id : createId(),
        title: typeof item.title === 'string' ? item.title : '',
        body: typeof item.body === 'string' ? item.body : '',
        type: item.type === 'text' ? 'text' : 'text',
        labels: Array.isArray(item.labels) ? item.labels : [],
        pinned: Boolean(item.pinned),
        archived: Boolean(item.archived),
        checklistItems: Array.isArray(item.checklistItems) ? item.checklistItems : [],
        createdAt: typeof item.createdAt === 'string' ? item.createdAt : new Date().toISOString(),
        updatedAt: typeof item.updatedAt === 'string' ? item.updatedAt : new Date().toISOString()
      }));
  } catch (error) {
    return [];
  }
}

function saveNotes() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(notes));
}

function createId() {
  return 'note-' + Date.now() + '-' + Math.random().toString(16).slice(2);
}

function updateComposerMode() {
  const isChecklist = noteTypeSelect.value === 'checklist';
  textBodyField.hidden = isChecklist;
  checklistEditor.hidden = !isChecklist;
}

function updateViewButtons(selectedView) {
  currentView = selectedView;

  viewButtons.forEach((button) => {
    const isActive = button.dataset.view === selectedView;
    button.classList.toggle('is-active', isActive);
    button.setAttribute('aria-pressed', String(isActive));
  });

  if (selectedView === 'archive') {
    notesSectionTitle.textContent = 'Archived notes';
    notesSectionSubtitle.textContent = 'Archive actions will be added in a later step.';
  } else {
    notesSectionTitle.textContent = 'Notes';
    notesSectionSubtitle.textContent = 'Your saved notes appear here and stay available after reloads.';
  }

  renderNotes();
}

function resetForm() {
  noteForm.reset();
  editingNoteIdInput.value = '';
  saveButton.textContent = 'Save note';
  cancelEditButton.hidden = true;
  noteTypeSelect.value = 'text';
  updateComposerMode();
}

function populateForm(note) {
  editingNoteIdInput.value = note.id;
  noteTitleInput.value = note.title;
  noteBodyInput.value = note.body;
  noteTypeSelect.value = 'text';
  saveButton.textContent = 'Update note';
  cancelEditButton.hidden = false;
  updateComposerMode();
  noteTitleInput.focus();
}

function formatDate(isoString) {
  const date = new Date(isoString);

  if (Number.isNaN(date.getTime())) {
    return 'Saved recently';
  }

  return date.toLocaleString([], {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit'
  });
}

function createNoteCard(note) {
  const article = document.createElement('article');
  article.className = 'note-card card';

  const header = document.createElement('div');
  header.className = 'note-card-header';

  const headingWrap = document.createElement('div');

  const meta = document.createElement('p');
  meta.className = 'note-meta';
  meta.textContent = 'Plain text note';

  const title = document.createElement('h3');
  title.textContent = note.title.trim() || 'Untitled note';

  headingWrap.append(meta, title);
  header.appendChild(headingWrap);

  const body = document.createElement('p');
  body.className = 'note-body';

  if (note.body.trim()) {
    body.textContent = note.body;
  } else {
    body.textContent = 'No body text';
    body.classList.add('is-empty');
  }

  const labelsPlaceholder = document.createElement('p');
  labelsPlaceholder.className = 'note-label-placeholder';
  labelsPlaceholder.textContent = 'Labels and archive tools will be added in the next step.';

  const dateText = document.createElement('p');
  dateText.className = 'note-date';
  dateText.textContent = `Last updated: ${formatDate(note.updatedAt)}`;

  const actions = document.createElement('div');
  actions.className = 'card-actions';

  const editButton = document.createElement('button');
  editButton.type = 'button';
  editButton.className = 'text-button';
  editButton.textContent = 'Edit';
  editButton.setAttribute('aria-label', `Edit note ${note.title.trim() || 'Untitled note'}`);
  editButton.addEventListener('click', () => {
    populateForm(note);
  });

  const deleteButton = document.createElement('button');
  deleteButton.type = 'button';
  deleteButton.className = 'danger-button';
  deleteButton.textContent = 'Delete';
  deleteButton.setAttribute('aria-label', `Delete note ${note.title.trim() || 'Untitled note'}`);
  deleteButton.addEventListener('click', () => {
    const confirmed = window.confirm('Delete this note permanently?');

    if (!confirmed) {
      return;
    }

    notes = notes.filter((item) => item.id !== note.id);
    saveNotes();

    if (editingNoteIdInput.value === note.id) {
      resetForm();
    }

    renderNotes();
  });

  actions.append(editButton, deleteButton);
  article.append(header, body, labelsPlaceholder, dateText, actions);

  return article;
}

function renderNotes() {
  notesGrid.innerHTML = '';

  const visibleNotes = notes
    .filter((note) => currentView === 'archive' ? note.archived : !note.archived)
    .sort((a, b) => new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime());

  if (visibleNotes.length === 0) {
    emptyState.hidden = false;
    emptyState.querySelector('h3').textContent = currentView === 'archive' ? 'No archived notes' : 'No notes yet';
    emptyState.querySelector('p').textContent = currentView === 'archive'
      ? 'Archive support is coming in the next step, so there is nothing here yet.'
      : 'Create your first note using the form on the left.';
    return;
  }

  emptyState.hidden = true;

  visibleNotes.forEach((note) => {
    notesGrid.appendChild(createNoteCard(note));
  });
}

noteTypeSelect.addEventListener('change', updateComposerMode);

viewButtons.forEach((button) => {
  button.addEventListener('click', () => {
    updateViewButtons(button.dataset.view);
  });
});

cancelEditButton.addEventListener('click', () => {
  resetForm();
});

noteForm.addEventListener('reset', () => {
  window.setTimeout(() => {
    resetForm();
  }, 0);
});

noteForm.addEventListener('submit', (event) => {
  event.preventDefault();

  const title = noteTitleInput.value.trim();
  const body = noteBodyInput.value.trim();
  const now = new Date().toISOString();
  const editingId = editingNoteIdInput.value;

  if (!title && !body) {
    window.alert('Please enter a title, a body, or both before saving.');
    noteTitleInput.focus();
    return;
  }

  if (editingId) {
    notes = notes.map((note) => {
      if (note.id !== editingId) {
        return note;
      }

      return {
        ...note,
        title,
        body,
        updatedAt: now
      };
    });
  } else {
    notes.unshift({
      id: createId(),
      title,
      body,
      type: 'text',
      labels: [],
      pinned: false,
      archived: false,
      checklistItems: [],
      createdAt: now,
      updatedAt: now
    });
  }

  saveNotes();
  resetForm();
  renderNotes();
});

updateComposerMode();
updateViewButtons('active');
renderNotes();

```

### README.md

```text
# NoteKeeper

NoteKeeper is a small browser-only notes app that runs directly from `index.html`. This step adds working plain text note creation, editing, deletion, and browser storage with `localStorage`.

## Run

1. Place these four files in the same folder:
   - `index.html`
   - `styles.css`
   - `app.js`
   - `README.md`
2. Open `index.html` directly in a modern browser.
3. No server, build tool, package manager, or external dependency is required.

## Features in this step

- Create plain text notes with an optional title and body
- Edit an existing note
- Delete a note permanently
- Notes render as responsive cards
- Notes persist in `localStorage`
- Safe startup when no saved data exists
- Safe recovery to an empty list if stored JSON is malformed
- Active and archived view controls remain visible as part of the app shell

## Storage

- Notes are stored in the browser under the key `notekeeper.notes`.
- Saved note data includes id, title, body, type, labels, pinned state, archived state, checklist placeholder data, and timestamps.
- In this step, only plain text notes are editable. Labels, archive behavior, search, checklist workflows, and pinning are planned for later steps.

## Manual verification

Open `index.html` and verify the following:

1. Create a note with a title and body, then save it.
2. Create a note with only a title, then save it.
3. Create a note with only body text, then save it.
4. Edit an existing note and confirm the card updates.
5. Delete a note and confirm it disappears.
6. Reload the page and confirm saved notes remain.
7. If desired, inspect browser storage and confirm notes are saved under `notekeeper.notes`.
8. Confirm the app still loads if there are no saved notes.
9. Confirm the layout remains usable on narrow and wide browser widths.
10. Tab through the form and note action buttons to confirm keyboard access and visible focus states.

## Notes

- The checklist option is shown for product direction but disabled until a later benchmark step.
- The labels field is also intentionally disabled for now and will be activated in a later step.
- The archive view is present in the interface, but archive/restore actions are not implemented yet in this step.

```
