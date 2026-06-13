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