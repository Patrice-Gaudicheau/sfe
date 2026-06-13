(function () {
  const STORAGE_KEY = "notekeeper.notes";

  const noteForm = document.querySelector("#note-form");
  const noteTitleField = document.querySelector("#note-title");
  const noteBodyField = document.querySelector("#note-body");
  const noteLabelsField = document.querySelector("#note-labels");
  const noteTypeField = document.querySelector("#note-type");
  const composerDescription = document.querySelector("#composer-description");
  const checklistBuilder = document.querySelector("#checklist-builder");
  const checklistItems = document.querySelector("#checklist-items");
  const addChecklistItemButton = document.querySelector("#add-checklist-item");
  const viewButtons = document.querySelectorAll(".view-button");
  const searchInput = document.querySelector("#search-input");
  const noteTypeLabel = document.querySelector('label[for="note-type"]');
  const composerTitle = document.querySelector("#composer-title");
  const notesStatus = document.querySelector("#notes-status");
  const notesArea = document.querySelector("#notes-area");
  const submitButton = noteForm ? noteForm.querySelector('button[type="submit"]') : null;

  const state = {
    activeView: "active",
    editingNoteId: null,
    notes: loadNotes()
  };

  function setStatus(message) {
    if (notesStatus) {
      notesStatus.textContent = message;
    }
  }

  function updateChecklistVisibility() {
    if (!noteTypeField || !checklistBuilder || !noteBodyField) {
      return;
    }

    const isChecklist = noteTypeField.value === "checklist";
    checklistBuilder.hidden = !isChecklist;
    noteBodyField.placeholder = isChecklist
      ? "Optional checklist summary or context"
      : "Write a quick note, reminder, or checklist summary";
    noteBodyField.setAttribute("aria-describedby", isChecklist ? "composer-description checklist-helper-text" : "composer-description");
  }

  function createChecklistItemId() {
    return "item-" + Date.now() + "-" + Math.random().toString(16).slice(2, 8);
  }

  function createNoteId() {
    return "note-" + Date.now() + "-" + Math.random().toString(16).slice(2, 10);
  }

  function getChecklistPositionLabel(row) {
    if (!row || !row.parentElement) {
      return "Checklist item";
    }

    const rows = Array.from(row.parentElement.querySelectorAll(".checklist-item-row"));
    const position = rows.indexOf(row) + 1;
    return "Checklist item " + position;
  }

  function refreshChecklistAccessibility() {
    if (!checklistItems) {
      return;
    }

    const rows = Array.from(checklistItems.querySelectorAll(".checklist-item-row"));
    rows.forEach(function (row, index) {
      row.setAttribute("role", "listitem");

      const checkbox = row.querySelector(".checklist-item-checkbox");
      const textInput = row.querySelector('.checklist-item-text');
      const removeButton = row.querySelector(".checklist-item-remove");
      const positionLabel = "Checklist item " + (index + 1);

      if (checkbox) {
        checkbox.setAttribute("aria-label", "Mark " + positionLabel.toLowerCase() + " complete");
      }

      if (textInput) {
        textInput.setAttribute("aria-label", positionLabel + " text");
      }

      if (removeButton) {
        removeButton.setAttribute("aria-label", "Remove " + positionLabel.toLowerCase());
      }
    });
  }

  function createChecklistRow(item, options) {
    const settings = options || {};
    const row = document.createElement("div");
    row.className = "checklist-item-row";
    row.dataset.checklistItemId =
      item && typeof item.id === "string" && item.id.trim() !== ""
        ? item.id
        : createChecklistItemId();

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.className = "checklist-item-checkbox";
    checkbox.checked = Boolean(item && item.checked);

    const textInput = document.createElement("input");
    textInput.type = "text";
    textInput.className = "checklist-item-text";
    textInput.autocomplete = "off";
    textInput.placeholder = "Checklist item text";
    textInput.value = item && typeof item.text === "string" ? item.text : "";

    const removeButton = document.createElement("button");
    removeButton.type = "button";
    removeButton.className = "secondary-button checklist-item-remove";
    removeButton.textContent = "Remove";
    removeButton.addEventListener("click", function () {
      if (!checklistItems) {
        return;
      }

      if (checklistItems.children.length === 1) {
        checkbox.checked = false;
        textInput.value = "";
        textInput.focus();
        setStatus("Checklist item cleared.");
        return;
      }

      checklistItems.removeChild(row);
      refreshChecklistAccessibility();
      setStatus(getChecklistPositionLabel(row) + " removed.");
    });

    row.appendChild(checkbox);
    row.appendChild(textInput);
    row.appendChild(removeButton);
    refreshChecklistAccessibility();

    if (settings.focusTextInput) {
      window.setTimeout(function () {
        textInput.focus();
      }, 0);
    }

    return row;
  }

  function ensureChecklistRow() {
    if (!checklistItems) {
      return;
    }

    if (!checklistItems.children.length) {
      checklistItems.appendChild(createChecklistRow());
      refreshChecklistAccessibility();
    }
  }

  function renderChecklistBuilder(items) {
    if (!checklistItems) {
      return;
    }

    checklistItems.innerHTML = "";

    if (Array.isArray(items) && items.length) {
      items.forEach(function (item) {
        checklistItems.appendChild(createChecklistRow(item));
      });
    } else {
      checklistItems.appendChild(createChecklistRow());
    }

    refreshChecklistAccessibility();
  }

  function normalizeLabels(rawLabels) {
    if (!Array.isArray(rawLabels)) {
      return [];
    }

    return rawLabels
      .map(function (label) {
        return typeof label === "string" ? label.trim() : "";
      })
      .filter(function (label, index, labels) {
        return label !== "" && labels.indexOf(label) === index;
      });
  }

  function normalizeChecklist(rawChecklist) {
    if (!Array.isArray(rawChecklist)) {
      return [];
    }

    return rawChecklist
      .map(function (item, index) {
        const text =
          item && typeof item.text === "string"
            ? item.text
            : typeof item === "string"
              ? item
              : "";

        return {
          id:
            item && typeof item.id === "string" && item.id.trim() !== ""
              ? item.id
              : "item-" + index + "-" + Math.random().toString(16).slice(2, 6),
          text: text.trim(),
          checked: Boolean(item && item.checked)
        };
      })
      .filter(function (item) {
        return item.text !== "";
      });
  }

  function sanitizeStoredNote(note) {
    if (!note || typeof note !== "object") {
      return null;
    }

    const id =
      typeof note.id === "string" && note.id.trim() !== ""
        ? note.id
        : createNoteId();
    const createdAt =
      typeof note.createdAt === "string" && note.createdAt.trim() !== ""
        ? note.createdAt
        : new Date().toISOString();
    const updatedAt =
      typeof note.updatedAt === "string" && note.updatedAt.trim() !== ""
        ? note.updatedAt
        : createdAt;
    const type = note.type === "checklist" ? "checklist" : "text";

    return {
      id: id,
      title: typeof note.title === "string" ? note.title : "",
      body: typeof note.body === "string" ? note.body : "",
      type: type,
      labels: normalizeLabels(note.labels),
      checklistItems: normalizeChecklist(note.checklistItems),
      archived: Boolean(note.archived),
      pinned: Boolean(note.pinned) && !Boolean(note.archived),
      createdAt: createdAt,
      updatedAt: updatedAt
    };
  }

  function loadNotes() {
    let rawValue;

    try {
      rawValue = window.localStorage.getItem(STORAGE_KEY);
    } catch (error) {
      return [];
    }

    if (!rawValue || rawValue.trim() === "") {
      return [];
    }

    try {
      const parsedValue = JSON.parse(rawValue);

      if (!Array.isArray(parsedValue)) {
        return [];
      }

      return parsedValue
        .map(sanitizeStoredNote)
        .filter(function (note) {
          return note !== null;
        });
    } catch (error) {
      return [];
    }
  }

  function getCurrentSearchQuery() {
    return searchInput ? searchInput.value.trim().toLowerCase() : "";
  }

  function saveNotes() {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state.notes));
      return true;
    } catch (error) {
      return false;
    }
  }

  function resetChecklistBuilder() {
    if (!checklistItems) {
      return;
    }

    renderChecklistBuilder();
  }

  function updateComposerMode() {
    if (composerTitle) {
      composerTitle.textContent = state.editingNoteId ? "Edit note" : "Create a note";
    }

    if (composerDescription) {
      composerDescription.textContent = state.editingNoteId
        ? "Update the note details, labels, or checklist items, then save your changes to this browser."
        : "Create a text or checklist note, organize it with labels, and keep everything saved locally in this browser.";
    }

    if (submitButton) {
      submitButton.textContent = state.editingNoteId ? "Update note" : "Save note";
    }

    if (noteForm) {
      noteForm.setAttribute("aria-label", state.editingNoteId ? "Edit existing note" : "Create a new note");
    }
  }

  function focusNotesRegion() {
    if (notesArea) {
      notesArea.focus();
    }
  }

  function resetForm() {
    if (!noteForm) {
      return;
    }

    noteForm.reset();
    state.editingNoteId = null;
    resetChecklistBuilder();
    updateChecklistVisibility();
    updateComposerMode();
  }

  function collectChecklistItemsFromForm() {
    if (!checklistItems) {
      return [];
    }

    ensureChecklistRow();
    return Array.from(checklistItems.querySelectorAll(".checklist-item-row"))
      .map(function (row, index) {
        const checkbox = row.querySelector('input[type="checkbox"]');
        const textInput = row.querySelector('input[type="text"]');
        const text = textInput ? textInput.value.trim() : "";

        return {
          id: row.dataset.checklistItemId || "item-" + index,
          text: text,
          checked: Boolean(checkbox && checkbox.checked)
        };
      })
      .filter(function (item) {
        return item.text !== "";
      });
  }

  function getFormData() {
    const labels =
      noteLabelsField && noteLabelsField.value
        ? noteLabelsField.value
            .split(",")
            .map(function (label) {
              return label.trim();
            })
            .filter(function (label, index, labelsList) {
              return label !== "" && labelsList.indexOf(label) === index;
            })
        : [];
    const noteType = noteTypeField ? noteTypeField.value : "text";
    const checklistItemsFromForm = noteType === "checklist" ? collectChecklistItemsFromForm() : [];
    const normalizedType =
      noteType === "checklist" && checklistItemsFromForm.length ? "checklist" : noteType;
    const normalizedBody =
      normalizedType === "checklist"
        ? noteBodyField
          ? noteBodyField.value.trim()
          : ""
        : noteBodyField
          ? noteBodyField.value.trim()
          : "";

    return {
      title: noteTitleField ? noteTitleField.value.trim() : "",
      body: normalizedBody,
      type: normalizedType,
      labels: labels,
      checklistItems: normalizedType === "checklist" ? checklistItemsFromForm : []
    };
  }

  function formatDate(dateValue) {
    const date = new Date(dateValue);
    if (Number.isNaN(date.getTime())) {
      return "Saved recently";
    }

    return "Updated " + date.toLocaleString();
  }

  function sortNotes(notes) {
    function getTimestamp(value) {
      const time = new Date(value).getTime();
      return Number.isNaN(time) ? 0 : time;
    }

    return notes.slice().sort(function (first, second) {
      if (!first.archived && !second.archived && first.pinned !== second.pinned) {
        return first.pinned ? -1 : 1;
      }

      return getTimestamp(second.updatedAt) - getTimestamp(first.updatedAt);
    });
  }

  function matchesSearch(note) {
    const query = getCurrentSearchQuery();

    if (query === "") {
      return true;
    }

    const labelText = note.labels.join(" ").toLowerCase();
    const checklistText = note.checklistItems
      .map(function (item) {
        return item.text;
      })
      .join(" ")
      .toLowerCase();

    return [note.title, note.body, labelText, checklistText].some(function (value) {
      return String(value || "").toLowerCase().indexOf(query) !== -1;
    });
  }

  function getVisibleNotes() {
    return sortNotes(state.notes).filter(function (note) {
      const matchesView = state.activeView === "archived" ? note.archived : !note.archived;
      return matchesView && matchesSearch(note);
    });
  }

  function renderEmptyState() {
    const emptyState = document.createElement("article");
    emptyState.className = "empty-state";
    emptyState.setAttribute("role", "status");

    const hasSearch = getCurrentSearchQuery() !== "";
    const headline = document.createElement("strong");
    const description = document.createElement("p");

    if (hasSearch) {
      headline.textContent = "No matching notes";
      description.textContent = "Try a different search term or switch views to find saved notes.";
    } else if (state.activeView === "archived") {
      headline.textContent = "No archived notes yet";
      description.textContent = "Archived notes you save for later will appear here, ready to restore when needed.";
    } else {
      headline.textContent = "No active notes yet";
      description.textContent = "Create your first note and it will appear here right away.";
    }

    notesArea.innerHTML = "";
    emptyState.appendChild(headline);
    emptyState.appendChild(description);
    notesArea.appendChild(emptyState);
  }

  function createActionButton(label, className, handler, accessibleLabel) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = className;
    button.textContent = label;
    if (accessibleLabel) {
      button.setAttribute("aria-label", accessibleLabel);
      button.title = accessibleLabel;
    }
    button.addEventListener("click", handler);
    return button;
  }

  function renderNotes() {
    if (!notesArea || !notesStatus) {
      return;
    }

    const visibleNotes = getVisibleNotes();
    const hasSearch = getCurrentSearchQuery() !== "";

    if (hasSearch) {
      setStatus(
        "Showing " +
        visibleNotes.length +
        " matching " +
        (visibleNotes.length === 1 ? "note" : "notes") +
        " in " +
        (state.activeView === "archived" ? "archived notes." : "active notes.") +
        " view."
      );
    } else {
      setStatus(
        state.activeView === "archived"
          ? "Showing archived notes saved in this browser."
          : "Showing active notes saved in this browser, with pinned notes first."
      );
    }

    notesArea.innerHTML = "";
    notesArea.setAttribute("data-view", state.activeView);

    if (!visibleNotes.length) {
      renderEmptyState();
      return;
    }

    visibleNotes.forEach(function (note) {
      const card = document.createElement("article");
      const noteTitle = note.title || "Untitled note";
      card.className = "note-card";
      card.dataset.noteType = note.type;
      card.dataset.noteArchived = String(Boolean(note.archived));
      card.dataset.notePinned = String(Boolean(note.pinned && !note.archived));
      card.setAttribute("aria-label", noteTitle);
      card.setAttribute("tabindex", "-1");

      const header = document.createElement("div");
      header.className = "note-card-header";

      const headingGroup = document.createElement("div");
      const cardHeadingId = "note-heading-" + note.id;
      const cardMetaId = "note-meta-" + note.id;

      const title = document.createElement("h3");
      title.id = cardHeadingId;
      title.textContent = noteTitle;
      headingGroup.appendChild(title);

      const meta = document.createElement("p");
      meta.className = "note-meta";
      meta.id = cardMetaId;
      meta.textContent = formatDate(note.updatedAt);
      headingGroup.appendChild(meta);

      const badge = document.createElement("p");
      badge.className = "note-badge";
      badge.textContent = note.type === "checklist" ? "Checklist" : "Text note";
      headingGroup.appendChild(badge);

      if (note.archived) {
        const archivedBadge = document.createElement("p");
        archivedBadge.className = "note-badge";
        archivedBadge.textContent = "Archived";
        headingGroup.appendChild(archivedBadge);
      }

      if (note.pinned && !note.archived) {
        const pinnedBadge = document.createElement("p");
        pinnedBadge.className = "note-badge";
        pinnedBadge.textContent = "Pinned";
        headingGroup.appendChild(pinnedBadge);
      }

      header.appendChild(headingGroup);

      const actions = document.createElement("div");
      actions.className = "note-actions";
      actions.setAttribute("role", "group");
      actions.setAttribute("aria-label", "Actions for " + noteTitle);

      const editButton = createActionButton(
        "Edit",
        "secondary-button",
        function () {
          startEditing(note.id);
        },
        "Edit note " + noteTitle
      );

      actions.appendChild(editButton);

      if (!note.archived) {
        const pinButton = createActionButton(
          note.pinned ? "Unpin" : "Pin",
          "secondary-button is-pin-toggle",
          function () {
            togglePinned(note.id);
          },
          note.pinned ? "Unpin note " + noteTitle : "Pin note " + noteTitle
        );
        pinButton.setAttribute("aria-pressed", String(Boolean(note.pinned)));
        actions.appendChild(pinButton);
      }

      const archiveButton = createActionButton(
        note.archived ? "Restore" : "Archive",
        "secondary-button is-archive",
        function () {
          if (note.archived) {
            restoreNote(note.id);
          } else {
            archiveNote(note.id);
          }
        },
        (note.archived ? "Restore note " : "Archive note ") + noteTitle
      );

      const deleteButton = createActionButton(
        "Delete",
        "secondary-button is-danger",
        function () {
          deleteNote(note.id);
        },
        "Delete note " + noteTitle
      );

      actions.appendChild(archiveButton);
      actions.appendChild(deleteButton);
      header.appendChild(actions);
      card.appendChild(header);

      const body = document.createElement("p");
      body.className = "note-body";
      body.textContent = note.type === "checklist" ? note.body || "" : note.body || "No body text";

      if (note.type === "checklist") {
        const checklistPreview = document.createElement("ul");
        checklistPreview.className = "checklist-preview";
        checklistPreview.setAttribute("aria-label", "Checklist preview");

        note.checklistItems.forEach(function (item) {
          const itemElement = document.createElement("li");
          itemElement.dataset.checked = String(Boolean(item.checked));
          itemElement.textContent = (item.checked ? "[x] " : "[ ] ") + item.text;
          checklistPreview.appendChild(itemElement);
        });

        if (note.body) {
          card.appendChild(body);
        }

        card.appendChild(checklistPreview);
      } else {
        card.appendChild(body);
      }

      if (note.labels.length) {
        const labelList = document.createElement("ul");
        labelList.className = "label-list";
        labelList.setAttribute("aria-label", "Labels");

        note.labels.forEach(function (label) {
          const labelItem = document.createElement("li");
          labelItem.textContent = label;
          labelList.appendChild(labelItem);
        });

        card.appendChild(labelList);
      }

      if (!note.title && !note.body && note.type !== "checklist") {
        const fallback = document.createElement("p");
        fallback.textContent = "This note is empty. Use Edit to add content.";
        card.appendChild(fallback);
      }

      notesArea.appendChild(card);
    });
  }

  function startEditing(noteId) {
    const note = state.notes.find(function (item) {
      return item.id === noteId;
    });

    if (!note || !noteForm) {
      return;
    }

    state.editingNoteId = note.id;
    if (noteForm) {
      noteForm.scrollIntoView({ block: "start", behavior: "smooth" });
    }

    if (noteTitleField) {
      noteTitleField.value = note.title;
    }

    if (noteBodyField) {
      noteBodyField.value = note.body;
    }

    if (noteLabelsField) {
      noteLabelsField.value = note.labels.join(", ");
    }

    if (noteTypeField) {
      noteTypeField.value = note.type;
    }

    if (checklistItems) {
      renderChecklistBuilder(note.type === "checklist" ? note.checklistItems : []);
    }

    updateChecklistVisibility();
    updateComposerMode();

    if (noteTitleField) {
      noteTitleField.focus();
    }

    setStatus("Editing " + (note.title || "untitled note") + ". Update the fields and save your changes.");

    if (submitButton) {
      submitButton.setAttribute("aria-label", "Save changes to " + (note.title || "untitled note"));
    }
  }

  function upsertNote(noteData) {
    const timestamp = new Date().toISOString();

    if (state.editingNoteId) {
      state.notes = state.notes.map(function (note) {
        if (note.id !== state.editingNoteId) {
          return note;
        }

        return {
          id: note.id,
          title: noteData.title,
          body: noteData.body,
          type: noteData.type === "checklist" ? "checklist" : "text",
          labels: noteData.labels,
          checklistItems: noteData.type === "checklist" ? noteData.checklistItems : [],
          archived: note.archived,
          pinned: note.archived ? false : Boolean(note.pinned),
          createdAt: note.createdAt,
          updatedAt: timestamp
        };
      });

      setStatus("Note updated and saved to this browser.");
    } else {
      state.notes.unshift({
        id: createNoteId(),
        title: noteData.title,
        body: noteData.body,
        type: noteData.type === "checklist" ? "checklist" : "text",
        labels: noteData.labels,
        checklistItems: noteData.type === "checklist" ? noteData.checklistItems : [],
        archived: false,
        pinned: false,
        createdAt: timestamp,
        updatedAt: timestamp
      });

      setStatus("Note saved to this browser.");
    }
  }

  function persistAndRender(successMessage, failureMessage) {
    const didSave = saveNotes();
    renderNotes();
    setStatus(didSave ? successMessage : failureMessage);
  }

  function togglePinned(noteId) {
    let changedNote = null;

    state.notes = state.notes.map(function (note) {
      if (note.id !== noteId || note.archived) {
        return note;
      }

      changedNote = {
        id: note.id,
        title: note.title,
        body: note.body,
        type: note.type,
        labels: note.labels,
        checklistItems: note.checklistItems,
        archived: note.archived,
        pinned: !note.pinned,
        createdAt: note.createdAt,
        updatedAt: new Date().toISOString()
      };

      return changedNote;
    });

    const successMessage =
      changedNote && changedNote.pinned ? "Note pinned to the top of active notes." : "Note unpinned.";

    persistAndRender(
      successMessage,
      "Pinned state updated in memory, but local storage was not available."
    );
  }

  function archiveNote(noteId) {
    state.notes = state.notes.map(function (note) {
      if (note.id !== noteId) {
        return note;
      }

      return {
        id: note.id,
        title: note.title,
        body: note.body,
        type: note.type,
        labels: note.labels,
        checklistItems: note.checklistItems,
        archived: true,
        pinned: false,
        createdAt: note.createdAt,
        updatedAt: new Date().toISOString()
      };
    });

    persistAndRender("Note archived.", "Note archived in memory, but local storage was not available.");
  }

  function restoreNote(noteId) {
    state.notes = state.notes.map(function (note) {
      if (note.id !== noteId) {
        return note;
      }

      return {
        id: note.id,
        title: note.title,
        body: note.body,
        type: note.type,
        labels: note.labels,
        checklistItems: note.checklistItems,
        archived: false,
        pinned: false,
        createdAt: note.createdAt,
        updatedAt: new Date().toISOString()
      };
    });

    persistAndRender(
      "Note restored to active notes.",
      "Note restored in memory, but local storage was not available."
    );
  }

  function clearEditingState() {
    state.editingNoteId = null;
    updateComposerMode();
  }

  function findEditingNote() {
    return (
      state.notes.find(function (note) {
        return note.id === state.editingNoteId;
      }) || null
    );
  }

  function syncEditingStateAfterSave() {
    if (!state.editingNoteId) {
      return;
    }

    if (!findEditingNote()) {
      clearEditingState();
    }
  }

  function deleteNote(noteId) {
    state.notes = state.notes.filter(function (note) {
      return note.id !== noteId;
    });

    if (state.editingNoteId === noteId) {
      resetForm();
    }

    if (!saveNotes()) {
      setStatus("Note deleted in memory, but local storage was not available.");
      renderNotes();
      focusNotesRegion();
      return;
    }

    renderNotes();
    setStatus("Note deleted.");
    focusNotesRegion();
  }

  function setActiveView(viewName) {
    state.activeView = viewName;

    viewButtons.forEach(function (button) {
      const isActive = button.dataset.view === viewName;
      button.classList.toggle("is-active", isActive);
      button.setAttribute("aria-pressed", String(isActive));
    });

    renderNotes();
    setStatus(viewName === "archived" ? "Archived notes view selected." : "Active notes view selected.");
    focusNotesRegion();
  }

  if (noteTypeField && checklistBuilder) {
    noteTypeField.addEventListener("change", updateChecklistVisibility);
    updateChecklistVisibility();
  }

  if (addChecklistItemButton && checklistItems) {
    addChecklistItemButton.addEventListener("click", function () {
      const row = createChecklistRow(null, { focusTextInput: true });
      checklistItems.appendChild(row);
      refreshChecklistAccessibility();
      setStatus(getChecklistPositionLabel(row) + " added.");
    });
  }

  viewButtons.forEach(function (button) {
    button.addEventListener("click", function () {
      setActiveView(button.dataset.view || "active");
    });
  });

  if (searchInput) {
    searchInput.addEventListener("input", renderNotes);
  }

  if (noteForm) {
    noteForm.addEventListener("submit", function (event) {
      event.preventDefault();
      const noteData = getFormData();
      const wasEditing = Boolean(state.editingNoteId);
      upsertNote(noteData);
      const didSave = saveNotes();

      if (!didSave) {
        setStatus(
          wasEditing
          ? "Note updated in memory, but saving to local storage was not available."
          : "Note saved in memory, but local storage was not available."
        );
      } else {
        setStatus(wasEditing ? "Note updated and saved to this browser." : "Note saved to this browser.");
      }
      renderNotes();
      resetForm();
    });

    noteForm.addEventListener("reset", function () {
      window.setTimeout(function () {
        resetChecklistBuilder();
        if (noteBodyField) {
          noteBodyField.placeholder = "Write a quick note, reminder, or checklist summary";
          noteBodyField.setAttribute("aria-describedby", "composer-description");
        }
        if (noteTypeLabel) {
          noteTypeLabel.textContent = "Note type";
        }
        updateChecklistVisibility();
        state.editingNoteId = null;
        updateComposerMode();
        if (submitButton) {
          submitButton.removeAttribute("aria-label");
        }
        setStatus("Form cleared. Create a new note or choose an existing note to edit.");
      }, 0);
    });
  }

  ensureChecklistRow();

  if (noteTypeLabel) {
    noteTypeLabel.textContent = "Note type";
  }

  updateComposerMode();
  renderNotes();
  setActiveView("active");
})();
