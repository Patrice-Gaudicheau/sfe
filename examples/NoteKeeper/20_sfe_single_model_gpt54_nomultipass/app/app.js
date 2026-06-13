(function () {
  "use strict";

  const form = document.querySelector(".note-form");
  const editingNoteIdInput = document.getElementById("editing-note-id");
  const noteTypeInput = document.getElementById("note-type");
  const titleInput = document.getElementById("note-title");
  const bodyInput = document.getElementById("note-body");
  const bodyGroup = document.getElementById("note-body-group");
  const labelsInput = document.getElementById("note-labels");
  const searchInput = document.getElementById("search-input");
  const checklistEditor = document.getElementById("checklist-editor");
  const checklistItemsEditor = document.getElementById("checklist-items-editor");
  const newChecklistItemInput = document.getElementById("new-checklist-item");
  const addChecklistItemButton = document.getElementById("add-checklist-item-button");
  const viewButtons = document.querySelectorAll(".view-button");
  const notesGrid = document.getElementById("notes-grid");
  const noteTemplate = document.getElementById("note-card-template");
  const notesSummary = document.getElementById("notes-summary");
  const storageStatus = document.getElementById("storage-status");
  const cancelEditButton = document.getElementById("cancel-edit-button");
  const STORAGE_KEY = "notekeeper.notes";

  const state = {
    notes: [],
    currentView: "active",
    storageRecovered: false,
    searchTerm: "",
    draftChecklistItems: []
  };

  function createId() {
    return "note-" + Date.now() + "-" + Math.random().toString(36).slice(2, 8);
  }

  function normalizeChecklistItems(items) {
    if (!Array.isArray(items)) {
      return [];
    }

    return items
      .filter(function (item) {
        return item && typeof item === "object";
      })
      .map(function (item) {
        return {
          id: typeof item.id === "string" ? item.id : createId(),
          text: typeof item.text === "string" ? item.text : "",
          checked: Boolean(item.checked)
        };
      });
  }

  function parseLabels(value) {
    if (typeof value !== "string") {
      return [];
    }

    const seen = Object.create(null);

    return value
      .split(",")
      .map(function (label) {
        return label.trim();
      })
      .filter(function (label) {
        const key = label.toLowerCase();

        if (!label || seen[key]) {
          return false;
        }

        seen[key] = true;
        return true;
      });
  }

  function loadNotes() {
    const storedValue = window.localStorage.getItem(STORAGE_KEY);

    if (!storedValue) {
      return [];
    }

    try {
      const parsed = JSON.parse(storedValue);

      if (!Array.isArray(parsed)) {
        state.storageRecovered = true;
        return [];
      }

      return parsed
        .filter(function (note) {
          return note && typeof note === "object";
        })
        .map(function (note) {
          const type = note.type === "checklist" ? "checklist" : "text";

          return {
            id: typeof note.id === "string" ? note.id : createId(),
            title: typeof note.title === "string" ? note.title : "",
            body: typeof note.body === "string" ? note.body : "",
            type: type,
            checklistItems: normalizeChecklistItems(note.checklistItems),
            labels: Array.isArray(note.labels)
              ? note.labels.filter(function (label) {
                  return typeof label === "string" && label.trim();
                })
              : [],
            archived: Boolean(note.archived),
            createdAt:
              typeof note.createdAt === "string" ? note.createdAt : new Date().toISOString(),
            updatedAt:
              typeof note.updatedAt === "string" ? note.updatedAt : new Date().toISOString(),
            pinned: Boolean(note.pinned)
          };
        });
    } catch (error) {
      state.storageRecovered = true;
      return [];
    }
  }

  function saveNotes() {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state.notes));
  }

  function setStorageStatus(message, type) {
    if (!storageStatus) {
      return;
    }

    if (!message) {
      storageStatus.hidden = true;
      storageStatus.textContent = "";
      storageStatus.classList.remove("is-success");
      return;
    }

    storageStatus.hidden = false;
    storageStatus.textContent = message;
    storageStatus.classList.toggle("is-success", type === "success");
  }

  function formatUpdatedLabel(value) {
    const date = new Date(value);

    if (Number.isNaN(date.getTime())) {
      return "Saved recently";
    }

    return "Updated " + date.toLocaleString();
  }

  function updateComposerForType() {
    const isChecklist = noteTypeInput.value === "checklist";

    if (bodyGroup) {
      bodyGroup.hidden = isChecklist;
    }

    if (checklistEditor) {
      checklistEditor.hidden = !isChecklist;
    }
  }

  function renderChecklistEditor() {
    if (!checklistItemsEditor) {
      return;
    }

    checklistItemsEditor.innerHTML = "";

    state.draftChecklistItems.forEach(function (item) {
      const row = document.createElement("div");
      const toggleLabel = document.createElement("label");
      const checkbox = document.createElement("input");
      const textInput = document.createElement("input");
      const removeButton = document.createElement("button");

      row.className = "checklist-item-editor";
      row.dataset.itemId = item.id;

      checkbox.type = "checkbox";
      checkbox.checked = item.checked;
      checkbox.className = "checklist-item-toggle";
      checkbox.setAttribute("aria-label", "Mark checklist item complete");

      toggleLabel.appendChild(checkbox);
      toggleLabel.appendChild(document.createTextNode("Done"));

      textInput.type = "text";
      textInput.value = item.text;
      textInput.className = "checklist-item-text";
      textInput.setAttribute("aria-label", "Checklist item text");

      removeButton.type = "button";
      removeButton.className = "danger-button remove-checklist-item-button";
      removeButton.textContent = "Remove";

      row.appendChild(toggleLabel);
      row.appendChild(textInput);
      row.appendChild(removeButton);
      checklistItemsEditor.appendChild(row);
    });
  }

  function getVisibleNotes() {
    const searchTerm = state.searchTerm.trim().toLowerCase();

    return state.notes
      .filter(function (note) {
        return state.currentView === "archived" ? note.archived : !note.archived;
      })
      .filter(function (note) {
        if (!searchTerm) {
          return true;
        }

        const haystacks = [
          note.title,
          note.body,
          Array.isArray(note.labels) ? note.labels.join(" ") : "",
          Array.isArray(note.checklistItems)
            ? note.checklistItems
                .map(function (item) {
                  return item.text;
                })
                .join(" ")
            : ""
        ];

        return haystacks.some(function (value) {
          return typeof value === "string" && value.toLowerCase().includes(searchTerm);
        });
      })
      .sort(function (left, right) {
        if (state.currentView === "active" && Boolean(left.pinned) !== Boolean(right.pinned)) {
          return left.pinned ? -1 : 1;
        }

        return new Date(right.updatedAt).getTime() - new Date(left.updatedAt).getTime();
      });
  }

  function createEmptyState(title, description) {
    const article = document.createElement("article");
    const heading = document.createElement("h3");
    const copy = document.createElement("p");

    article.className = "empty-state";
    heading.textContent = title;
    copy.textContent = description;

    article.appendChild(heading);
    article.appendChild(copy);

    return article;
  }

  function renderNotes() {
    if (!notesGrid || !noteTemplate) {
      return;
    }

    const visibleNotes = getVisibleNotes();
    notesGrid.innerHTML = "";

    if (notesSummary) {
      if (state.currentView === "archived") {
        notesSummary.textContent = state.searchTerm
          ? "Search results from your archived notes."
          : "Archived notes are stored locally in this browser.";
      } else {
        notesSummary.textContent = state.searchTerm
          ? "Search results from your active notes."
          : "Pinned notes appear first and all notes persist after a reload.";
      }
    }

    if (visibleNotes.length === 0) {
      const hasSearch = Boolean(state.searchTerm.trim());

      notesGrid.appendChild(
        createEmptyState(
          hasSearch
            ? "No matching notes found"
            : state.currentView === "archived"
              ? "No archived notes yet"
              : "No saved notes yet",
          hasSearch
            ? "Try a different search term or switch between active and archived notes."
            : state.currentView === "archived"
              ? "Archived notes will appear here once you archive them from the active view."
              : "Create a note with a title, body, checklist items, or labels. Your notes are saved in localStorage."
        )
      );
      return;
    }

    visibleNotes.forEach(function (note) {
      const fragment = noteTemplate.content.cloneNode(true);
      const card = fragment.querySelector(".note-card");
      const stateBadge = fragment.querySelector(".note-state-badge");
      const pinBadge = fragment.querySelector(".pin-badge");
      const typeBadge = fragment.querySelector(".note-type-badge");
      const updatedBadge = fragment.querySelector(".note-updated-badge");
      const title = fragment.querySelector(".note-card-title");
      const body = fragment.querySelector(".note-card-body");
      const checklist = fragment.querySelector(".note-card-checklist");
      const labels = fragment.querySelector(".note-card-labels");
      const editButton = fragment.querySelector(".edit-note-button");
      const pinButton = fragment.querySelector(".pin-note-button");
      const archiveButton = fragment.querySelector(".archive-note-button");
      const deleteButton = fragment.querySelector(".delete-note-button");

      card.dataset.noteId = note.id;
      stateBadge.textContent = note.archived ? "Archived" : "Active";
      card.classList.toggle("is-pinned", Boolean(note.pinned) && !note.archived);
      pinBadge.hidden = !(note.pinned && !note.archived);
      typeBadge.textContent = note.type === "checklist" ? "Checklist" : "Text note";
      updatedBadge.textContent = formatUpdatedLabel(note.updatedAt);

      if (note.title.trim()) {
        title.textContent = note.title;
        title.classList.remove("is-untitled");
      } else {
        title.textContent = "Untitled note";
        title.classList.add("is-untitled");
      }

      if (note.type === "checklist") {
        body.hidden = true;
        checklist.hidden = false;
        checklist.innerHTML = "";

        if (Array.isArray(note.checklistItems) && note.checklistItems.length > 0) {
          note.checklistItems.forEach(function (item) {
            const listItem = document.createElement("li");
            listItem.textContent = item.text || "Untitled checklist item";
            if (item.checked) {
              listItem.classList.add("is-complete");
            }
            checklist.appendChild(listItem);
          });
        } else {
          const listItem = document.createElement("li");
          listItem.textContent = "No checklist items";
          checklist.appendChild(listItem);
        }
      } else {
        checklist.hidden = true;
        body.hidden = false;
        body.textContent = note.body.trim() ? note.body : "No body text";
      }

      labels.hidden = !(Array.isArray(note.labels) && note.labels.length > 0);
      labels.innerHTML = "";
      (note.labels || []).forEach(function (label) {
        const chip = document.createElement("span");
        chip.className = "label-chip";
        chip.textContent = label;
        labels.appendChild(chip);
      });

      pinButton.hidden = note.archived;
      if (!note.archived) {
        pinButton.textContent = note.pinned ? "Unpin" : "Pin";
        pinButton.setAttribute(
          "aria-label",
          (note.pinned ? "Unpin" : "Pin") + " note " + (note.title.trim() || "Untitled note")
        );
      }

      archiveButton.textContent = note.archived ? "Restore" : "Archive";
      archiveButton.setAttribute(
        "aria-label",
        (note.archived ? "Restore" : "Archive") + " note " + (note.title.trim() || "Untitled note")
      );
      editButton.setAttribute("aria-label", "Edit note " + (note.title.trim() || "Untitled note"));
      deleteButton.setAttribute(
        "aria-label",
        "Delete note " + (note.title.trim() || "Untitled note")
      );

      notesGrid.appendChild(fragment);
    });
  }

  function resetForm() {
    form.reset();
    editingNoteIdInput.value = "";
    state.draftChecklistItems = [];
    renderChecklistEditor();
    updateComposerForType();
    cancelEditButton.hidden = true;
  }

  function addDraftChecklistItem(text) {
    state.draftChecklistItems.push({
      id: createId(),
      text: typeof text === "string" ? text : "",
      checked: false
    });
    renderChecklistEditor();
  }

  function handleSubmit(event) {
    event.preventDefault();

    const noteType = noteTypeInput.value === "checklist" ? "checklist" : "text";
    const title = titleInput.value.trim();
    const body = bodyInput.value.trim();
    const labels = parseLabels(labelsInput.value);
    const checklistItems = state.draftChecklistItems
      .map(function (item) {
        return {
          id: item.id,
          text: item.text.trim(),
          checked: Boolean(item.checked)
        };
      })
      .filter(function (item) {
        return item.text;
      });
    const hasContent =
      Boolean(title) ||
      Boolean(body) ||
      labels.length > 0 ||
      checklistItems.length > 0;

    if (!hasContent) {
      setStorageStatus("Add note content before saving.", "warning");
      if (noteType === "checklist") {
        newChecklistItemInput.focus();
      } else {
        titleInput.focus();
      }
      return;
    }

    const now = new Date().toISOString();
    const existingId = editingNoteIdInput.value;

    if (existingId) {
      state.notes = state.notes.map(function (note) {
        if (note.id !== existingId) {
          return note;
        }

        return {
          id: note.id,
          title: title,
          body: noteType === "checklist" ? "" : body,
          type: noteType,
          checklistItems: checklistItems,
          labels: labels,
          archived: note.archived,
          createdAt: note.createdAt,
          updatedAt: now,
          pinned: Boolean(note.pinned)
        };
      });
      saveNotes();
      setStorageStatus("Note updated and saved in this browser.", "success");
    } else {
      state.notes.unshift({
        id: createId(),
        title: title,
        body: noteType === "checklist" ? "" : body,
        type: noteType,
        checklistItems: checklistItems,
        labels: labels,
        archived: false,
        createdAt: now,
        updatedAt: now,
        pinned: false
      });
      saveNotes();
      setStorageStatus("Note saved in this browser.", "success");
    }

    resetForm();
    renderNotes();
  }

  function startEditing(noteId) {
    const note = state.notes.find(function (item) {
      return item.id === noteId;
    });

    if (!note) {
      return;
    }

    editingNoteIdInput.value = note.id;
    noteTypeInput.value = note.type === "checklist" ? "checklist" : "text";
    titleInput.value = note.title;
    bodyInput.value = note.body;
    labelsInput.value = Array.isArray(note.labels) ? note.labels.join(", ") : "";
    state.draftChecklistItems = normalizeChecklistItems(note.checklistItems);
    updateComposerForType();
    renderChecklistEditor();
    cancelEditButton.hidden = false;
    titleInput.focus();
    setStorageStatus("Editing note. Save to keep your changes.", "success");
  }

  function toggleArchive(noteId) {
    state.notes = state.notes.map(function (note) {
      if (note.id !== noteId) {
        return note;
      }

      return {
        id: note.id,
        title: note.title,
        body: note.body,
        type: note.type,
        checklistItems: normalizeChecklistItems(note.checklistItems),
        labels: Array.isArray(note.labels) ? note.labels.slice() : [],
        archived: !note.archived,
        createdAt: note.createdAt,
        updatedAt: new Date().toISOString(),
        pinned: Boolean(note.pinned)
      };
    });

    saveNotes();
    renderNotes();
    setStorageStatus("Note status updated and saved.", "success");
  }

  function togglePin(noteId) {
    state.notes = state.notes.map(function (note) {
      if (note.id !== noteId || note.archived) {
        return note;
      }

      return {
        id: note.id,
        title: note.title,
        body: note.body,
        type: note.type,
        checklistItems: normalizeChecklistItems(note.checklistItems),
        labels: Array.isArray(note.labels) ? note.labels.slice() : [],
        archived: note.archived,
        createdAt: note.createdAt,
        updatedAt: new Date().toISOString(),
        pinned: !note.pinned
      };
    });

    saveNotes();
    renderNotes();
    setStorageStatus("Pin status updated and saved.", "success");
  }

  function deleteNote(noteId) {
    state.notes = state.notes.filter(function (note) {
      return note.id !== noteId;
    });

    if (editingNoteIdInput.value === noteId) {
      resetForm();
    }

    saveNotes();
    renderNotes();
    setStorageStatus("Note deleted from this browser.", "success");
  }

  function handleCardAction(event) {
    const target = event.target;
    const card = target.closest(".note-card");

    if (!card) {
      return;
    }

    const noteId = card.dataset.noteId;

    if (target.classList.contains("edit-note-button")) {
      startEditing(noteId);
    } else if (target.classList.contains("pin-note-button")) {
      togglePin(noteId);
    } else if (target.classList.contains("archive-note-button")) {
      toggleArchive(noteId);
    } else if (target.classList.contains("delete-note-button")) {
      deleteNote(noteId);
    }
  }

  function handleSearchInput(event) {
    state.searchTerm = event.target.value || "";
    renderNotes();
  }

  function handleChecklistEditorClick(event) {
    const target = event.target;

    if (target.id === "add-checklist-item-button") {
      const text = newChecklistItemInput.value.trim();
      addDraftChecklistItem(text);
      newChecklistItemInput.value = "";
      newChecklistItemInput.focus();
      return;
    }

    if (target.classList.contains("remove-checklist-item-button")) {
      const row = target.closest(".checklist-item-editor");

      if (!row) {
        return;
      }

      state.draftChecklistItems = state.draftChecklistItems.filter(function (item) {
        return item.id !== row.dataset.itemId;
      });
      renderChecklistEditor();
    }
  }

  function handleChecklistEditorInput(event) {
    const target = event.target;
    const row = target.closest(".checklist-item-editor");

    if (!row) {
      return;
    }

    const item = state.draftChecklistItems.find(function (entry) {
      return entry.id === row.dataset.itemId;
    });

    if (!item) {
      return;
    }

    if (target.classList.contains("checklist-item-text")) {
      item.text = target.value;
    } else if (target.classList.contains("checklist-item-toggle")) {
      item.checked = target.checked;
    }
  }

  function handleChecklistNewItemKeydown(event) {
    if (event.key !== "Enter") {
      return;
    }

    event.preventDefault();
    const text = newChecklistItemInput.value.trim();
    addDraftChecklistItem(text);
    newChecklistItemInput.value = "";
  }

  function setupViewButtons() {
    viewButtons.forEach(function (button) {
      button.addEventListener("click", function () {
        state.currentView = button.dataset.view || "active";

        viewButtons.forEach(function (item) {
          item.classList.remove("is-active");
          item.setAttribute("aria-pressed", "false");
        });

        button.classList.add("is-active");
        button.setAttribute("aria-pressed", "true");
        renderNotes();
      });
    });
  }

  state.notes = loadNotes();
  state.draftChecklistItems = [];

  if (state.storageRecovered) {
    setStorageStatus(
      "Saved notes could not be read, so NoteKeeper started with an empty list.",
      "warning"
    );
    saveNotes();
  }

  if (form) {
    form.addEventListener("submit", handleSubmit);
  }

  if (cancelEditButton) {
    cancelEditButton.addEventListener("click", function () {
      resetForm();
      setStorageStatus("", "");
    });
  }

  if (notesGrid) {
    notesGrid.addEventListener("click", handleCardAction);
  }

  if (searchInput) {
    searchInput.addEventListener("input", handleSearchInput);
  }

  if (noteTypeInput) {
    noteTypeInput.addEventListener("change", updateComposerForType);
  }

  if (checklistEditor) {
    checklistEditor.addEventListener("click", handleChecklistEditorClick);
    checklistEditor.addEventListener("input", handleChecklistEditorInput);
  }

  if (newChecklistItemInput) {
    newChecklistItemInput.addEventListener("keydown", handleChecklistNewItemKeydown);
  }

  setupViewButtons();
  updateComposerForType();
  renderChecklistEditor();
  renderNotes();
})();
