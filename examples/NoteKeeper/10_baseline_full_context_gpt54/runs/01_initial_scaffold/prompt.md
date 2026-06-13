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

## 1. Initial static scaffold

Create the initial static application files: `index.html`, `styles.css`, `app.js`, and `README.md`. Establish the NoteKeeper name, app shell, note creation form, placeholder card area, active/archive navigation controls, and baseline styling. The app should open directly in a browser without a server.

## Current generated app files

### index.html

File does not exist yet.

### styles.css

File does not exist yet.

### app.js

File does not exist yet.

### README.md

File does not exist yet.
