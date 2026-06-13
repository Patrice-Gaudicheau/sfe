# NoteKeeper

NoteKeeper is a small browser-only notes app built as a static application. It runs directly from local files with no server, build step, or external dependencies.

## Run locally

1. Open the `app/` folder.
2. Double-click `index.html`, or open it directly in a modern browser.

## Features

- Create text notes with an optional title and body
- Create checklist notes with multiple items
- Edit checklist item text, mark items complete or incomplete, and remove items before saving
- Edit existing notes
- Add comma-separated labels to notes
- Search across note titles, body text, checklist items, and labels
- Pin and unpin active notes
- Show pinned active notes before unpinned notes
- Delete notes
- Archive active notes and restore them from the archived view
- Switch between active and archived note views
- Visually distinguish pinned notes
- Display labels on note cards
- Persist notes in browser `localStorage` under the NoteKeeper-specific key `notekeeper.notes`
- Recover safely to an empty note list if stored data is missing, invalid, or malformed
- Open directly from `index.html` with no installation required
- Responsive layout that remains usable on smaller screens

## Storage behavior

Notes are stored locally in the current browser profile using `localStorage`. If you close the tab and reopen `index.html` in the same browser, saved notes should still be available.

Saved data includes title, body, note type, checklist items and checked state, labels, pin state, archive state, timestamps, and related note metadata needed by the app.

If stored data cannot be parsed, NoteKeeper resets to an empty list instead of crashing.

## Manual verification

1. Open `index.html` in a modern browser.
2. Create a text note with a title, body, and one or more labels, then save it.
3. Create a checklist note, add multiple checklist items, mark one complete, and save it.
4. Edit the checklist note, change item text, toggle checked states, remove an item, and save again.
5. Pin one active note and confirm it is visually highlighted and sorted before unpinned active notes.
6. Unpin the note and confirm it returns to the normal active ordering.
7. Confirm labels appear on note cards and checklist note content is displayed as a list.
8. Search by title text, body text, label text, and checklist item text, and confirm matching notes appear.
9. Try a search with no matches and confirm a helpful empty state appears.
10. Archive a note, confirm it disappears from the active view, then switch to the archived view and confirm it appears there.
11. Restore an archived note and confirm it returns to the active view.
12. Edit both a text note and a checklist note and confirm updates are saved.
13. Delete a note and confirm it is removed.
14. Reload the page and confirm previously saved notes remain available, including checklist state and pinned state.
