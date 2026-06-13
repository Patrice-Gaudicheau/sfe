# NoteKeeper

NoteKeeper is a small browser-only notes app for quick local note capture. It runs directly from the filesystem with no server, build step, package manager, or external dependency.

## Run the app

1. Open the `app/` folder in your file browser.
2. Double-click `index.html`, or open `index.html` directly in a modern browser.
3. Use the note form to create text notes or checklist notes.
4. Use search, pinning, archiving, restoring, editing, and deleting directly in the page.
5. Reload the tab to verify that saved notes remain available in this browser.

No installation, package manager, or local server is required.

## Features

- Create text notes and checklist notes with an optional title, body, and comma-separated labels.
- Edit existing notes and save changes in place.
- Delete notes immediately.
- Pin and unpin active notes, with pinned notes shown before other active notes.
- Archive active notes and restore archived notes from the archived view.
- Search notes by title, body, labels, and checklist item text using case-insensitive substring matching.
- Add multiple checklist items, edit item text, toggle checked state, and remove items before saving.
- View clear empty states when there are no visible active notes, archived notes, or search matches.
- Use keyboard-accessible controls with semantic buttons, visible focus styles, labeled form fields, and live status updates.
- Use the app responsively at phone, tablet, and desktop widths without horizontal scrolling.

## Storage notes

NoteKeeper stores data locally in the current browser under the `notekeeper.notes` localStorage key.

Saved note data includes:

- title
- body
- note type
- labels
- checklist items and checked states
- pinned state
- archived state
- created and updated timestamps

If stored data is missing, blank, malformed, or not an array, the app safely falls back to an empty note list instead of crashing.

Because the app uses browser localStorage, saved notes stay in the same browser profile on the same device. Moving the files to another folder or opening them in a different browser will not automatically move saved notes with them.

## Accessibility and responsive behavior

- A skip link is available to jump directly to the main content.
- Search, note fields, and checklist controls have visible labels or accessible names.
- Action buttons on note cards are keyboard reachable and use descriptive names.
- Status text updates as views change, notes are edited, and checklist rows are added or removed.
- The layout is designed for small phones, tablet widths, and wider desktop screens without hover-only actions.

## Manual review steps

1. Open `index.html` and confirm the page title and visible app name are NoteKeeper.
2. Create a text note with a title and body, save it, and confirm a note card appears.
3. Create another text note with only a title or only body text and confirm empty fields do not break rendering.
4. Add comma-separated labels to a note and confirm they save and render on the note card.
5. Create a checklist note with multiple items, toggle some items checked, leave others unchecked, remove one item, save it, and confirm the checklist content renders correctly on the card.
6. Click Edit on that checklist note and confirm all checklist items and checked states are repopulated for editing.
7. Edit the same checklist note again, change item text, change checked states, save it, and confirm the card updates immediately.
8. Create at least one additional active note, click Pin on one note, and confirm it becomes visually distinct and moves ahead of unpinned active notes.
9. Click Unpin on that same note and confirm it loses the pinned styling and returns to normal active-note ordering.
10. Type into the search field and confirm notes filter by title, body, labels, and checklist item text.
11. Click Archive on an active note and confirm it disappears from Active notes.
12. Switch to Archived notes and confirm the archived note appears there, with Restore available and pinning not shown for archived notes.
13. Click Restore on an archived note and confirm it returns to Active notes without losing content, labels, or checklist items.
14. Click Delete on a note and confirm it disappears immediately.
15. Reload the browser tab or reopen `index.html` and confirm saved notes, checklist states, checked and unchecked item state, pinned state, and archived state persist.
16. Resize the browser to about 360px wide and confirm the page remains usable without horizontal scrolling.
17. Resize to around 768px and confirm the layout expands cleanly for tablet width.
18. Resize to a wider desktop viewport and confirm notes appear in a simple multi-column card grid.
19. Use only the keyboard to tab through search, view buttons, form fields, save actions, and note card actions, and confirm visible focus styles appear throughout.
20. Use the skip link at the top of the page and confirm it moves focus to the main content area.
21. Switch between Active notes and Archived notes and confirm the status message updates clearly.
22. Add and remove checklist rows using only the keyboard and confirm focus remains usable after each action.
23. Search for notes and confirm the empty-state messaging stays understandable when no results match.
