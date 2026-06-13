# NoteKeeper

NoteKeeper is a small browser-only notes app. Open `index.html` directly in a browser and use it without any server, build step, or external dependency.

## Run

1. Open `index.html` in a modern browser.
2. Create notes, edit them, archive them, and refresh the page to confirm local persistence.

## Features

- Plain text note creation and editing
- Checklist note creation with editable items, checked states, and item removal
- Note deletion
- LocalStorage persistence with a NoteKeeper-specific key
- Safe startup when stored data is missing, empty, or malformed
- Active and archive views
- Search across title, body, labels, and checklist content
- Labels shown on cards
- Pin and unpin active notes
- Pinned active notes are visually distinguished and sorted before unpinned notes
- Responsive card layout

## Manual test steps

1. Open `index.html` directly.
2. Create a plain text note with a title and body.
3. Create a checklist note, add multiple items, check and uncheck items, remove an item, and save.
4. Save both notes, refresh the page, and confirm they remain visible with their current states.
5. Edit each note, pin and unpin a note, archive a note, and restore it from the archive view.
6. Search by title, body, label, and checklist item text, then clear the search to confirm notes return.
7. Delete a note and confirm it is removed.
8. Verify the page still works when the browser storage is empty or cleared.
