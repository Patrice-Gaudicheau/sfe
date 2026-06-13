# NoteKeeper

NoteKeeper is a small browser-only notes app that runs directly from `index.html`. It is local-first, stores data in `localStorage`, and uses only plain HTML, CSS, and JavaScript.

## Run the app

1. Place these files in the same folder:
   - `index.html`
   - `styles.css`
   - `app.js`
   - `README.md`
2. Open `index.html` directly in a modern browser.
3. No server, build step, package manager, or external dependency is required.

## Main features

- Create plain text notes with optional title and body
- Create checklist notes with multiple items
- Edit existing notes
- Delete notes permanently
- Add labels as comma-separated text
- Search by title, body, labels, and checklist item text
- Pin and unpin notes
- Show pinned notes before unpinned notes in the active view
- Archive notes from the main view
- Switch between active and archived note views
- Restore archived notes
- Store notes locally in the browser with `localStorage`
- Recover safely if stored note data is missing or malformed
- Show helpful empty states when there are no visible notes
- Use a responsive layout that works on phone, tablet, and desktop widths
- Support keyboard access with visible focus states and semantic controls

## Storage details

- Storage key: `notekeeper.notes`
- Saved note data includes:
  - id
  - title
  - body
  - type
  - labels
  - pinned state
  - archived state
  - checklist items and checked states
  - created and updated timestamps
- Search is case-insensitive and uses simple substring matching.
- If stored JSON is invalid or malformed, the app falls back to an empty note list.

## Manual verification steps

Open `index.html` and test the following:

1. Create a plain text note with a title, body, and labels.
2. Create a plain text note with only a title or only a body.
3. Create a checklist note with multiple items.
4. Edit a plain text note and save the changes.
5. Edit a checklist note, change item text, and save.
6. Mark a checklist item complete, save, reload the page, and confirm the checked state persists.
7. Remove a checklist item while editing and save.
8. Search by note title.
9. Search by body text.
10. Search by label text.
11. Search by checklist item text.
12. Pin a note and confirm it appears before unpinned notes in the active view.
13. Unpin the note and confirm ordering returns to normal.
14. Archive a note and confirm it disappears from the active view.
15. Switch to the archived view and confirm the archived note appears there.
16. Restore the archived note and confirm it returns to the active view.
17. Delete a note and confirm it is removed immediately.
18. Reload the page and confirm notes are still present.
19. Try a search that matches nothing and confirm a helpful empty state appears.
20. Resize the browser to around 360px, 768px, and desktop width to confirm the layout remains usable without horizontal scrolling.
21. Tab through the search field, view buttons, note form, checklist controls, and card action buttons to confirm keyboard access and visible focus states.

## Notes

- The app is intentionally small and reviewable.
- It does not include accounts, sync, collaboration, rich text, reminders, images, or server storage.
- The app runs entirely in the browser and is designed to be opened directly from a local folder.
