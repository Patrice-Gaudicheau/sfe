const STORAGE_KEY = 'notekeeper.notes';

const noteForm = document.getElementById('noteForm');
const editingNoteIdInput = document.getElementById('editingNoteId');
const noteTitleInput = document.getElementById('noteTitle');
const noteBodyInput = document.getElementById('noteBody');
const noteLabelsInput = document.getElementById('noteLabels');
const noteTypeSelect = document.getElementById('noteType');
const textBodyField = document.getElementById('textBodyField');
const checklistEditor = document.getElementById('checklistEditor');
const checklistItemsContainer = document.getElementById('checklistItemsContainer');
const addChecklistItemButton = document.getElementById('addChecklistItemButton');
const cancelEditButton = document.getElementById('cancelEditButton');
const saveButton = document.getElementById('saveButton');
const searchInput = document.getElementById('searchInput');
const notesGrid = document.getElementById('notesGrid');
const emptyState = document.getElementById('emptyState');
const viewButtons = document.querySelectorAll('.view-button');
const notesSectionTitle = document.getElementById('notesSectionTitle');
const notesSectionSubtitle = document.getElementById('notesSectionSubtitle');
const resultsSummary = document.getElementById('resultsSummary');
const formStatus = document.getElementById('formStatus');

let notes = loadNotes();
let currentView = 'active';
let currentSearchTerm = '';
let draftChecklistItems = [];

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
        type: item.type === 'checklist' ? 'checklist' : 'text',
        labels: normalizeLabels(Array.isArray(item.labels) ? item.labels : []),
        pinned: Boolean(item.pinned),
        archived: Boolean(item.archived),
        checklistItems: Array.isArray(item.checklistItems)
          ? item.checklistItems
              .filter((checklistItem) => checklistItem && typeof checklistItem === 'object')
              .map((checklistItem) => ({
                id: typeof checklistItem.id === 'string' ? checklistItem.id : createId(),
                text: typeof checklistItem.text === 'string' ? checklistItem.text : '',
                checked: Boolean(checklistItem.checked)
              }))
          : [],
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

function normalizeLabels(labelsValue) {
  const source = Array.isArray(labelsValue) ? labelsValue : [];
  const seen = new Set();

  return source
    .map((label) => String(label).trim())
    .filter((label) => {
      if (!label) {
        return false;
      }

      const key = label.toLowerCase();

      if (seen.has(key)) {
        return false;
      }

      seen.add(key);
      return true;
    });
}

function parseLabels(inputValue) {
  return normalizeLabels(inputValue.split(','));
}

function cloneChecklistItems(items) {
  return items.map((item) => ({
    id: typeof item.id === 'string' ? item.id : createId(),
    text: typeof item.text === 'string' ? item.text : '',
    checked: Boolean(item.checked)
  }));
}

function getSanitizedChecklistItems() {
  return draftChecklistItems
    .map((item) => ({
      id: item.id,
      text: item.text.trim(),
      checked: Boolean(item.checked)
    }))
    .filter((item) => item.text);
}

function setFormStatus(message) {
  formStatus.textContent = message || '';
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
    notesSectionSubtitle.textContent = 'Archived notes stay out of the main workspace until you restore them.';
  } else {
    notesSectionTitle.textContent = 'Notes';
    notesSectionSubtitle.textContent = 'Search your saved notes by title, body text, labels, and checklist items.';
  }

  renderNotes();
}

function renderChecklistEditor() {
  checklistItemsContainer.innerHTML = '';

  if (draftChecklistItems.length === 0) {
    const emptyMessage = document.createElement('p');
    emptyMessage.className = 'helper-text';
    emptyMessage.textContent = 'No checklist items yet. Add your first item.';
    checklistItemsContainer.appendChild(emptyMessage);
    return;
  }

  draftChecklistItems.forEach((item, index) => {
    const row = document.createElement('div');
    row.className = 'checklist-item-editor';

    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.checked = item.checked;
    checkbox.setAttribute('aria-label', `Mark checklist item ${index + 1} complete`);
    checkbox.addEventListener('change', () => {
      item.checked = checkbox.checked;
    });

    const textInput = document.createElement('input');
    textInput.type = 'text';
    textInput.value = item.text;
    textInput.placeholder = `Checklist item ${index + 1}`;
    textInput.setAttribute('aria-label', `Checklist item ${index + 1} text`);
    textInput.addEventListener('input', () => {
      item.text = textInput.value;
    });

    const removeButton = document.createElement('button');
    removeButton.type = 'button';
    removeButton.className = 'danger-button';
    removeButton.textContent = 'Remove';
    removeButton.setAttribute('aria-label', `Remove checklist item ${index + 1}`);
    removeButton.addEventListener('click', () => {
      draftChecklistItems = draftChecklistItems.filter((draftItem) => draftItem.id !== item.id);
      renderChecklistEditor();
    });

    row.append(checkbox, textInput, removeButton);
    checklistItemsContainer.appendChild(row);
  });
}

function addChecklistItem(text = '', checked = false) {
  draftChecklistItems.push({
    id: createId(),
    text,
    checked
  });
  renderChecklistEditor();
}

function resetForm() {
  noteForm.reset();
  editingNoteIdInput.value = '';
  saveButton.textContent = 'Save note';
  cancelEditButton.hidden = true;
  noteTypeSelect.value = 'text';
  draftChecklistItems = [];
  setFormStatus('');
  renderChecklistEditor();
  updateComposerMode();
}

function populateForm(note) {
  editingNoteIdInput.value = note.id;
  noteTitleInput.value = note.title;
  noteBodyInput.value = note.body;
  noteLabelsInput.value = note.labels.join(', ');
  noteTypeSelect.value = note.type === 'checklist' ? 'checklist' : 'text';
  draftChecklistItems = cloneChecklistItems(note.checklistItems);
  saveButton.textContent = 'Update note';
  cancelEditButton.hidden = false;
  setFormStatus(`Editing ${note.title.trim() || 'Untitled note'}.`);
  renderChecklistEditor();
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

function noteMatchesSearch(note, searchTerm) {
  if (!searchTerm) {
    return true;
  }

  const haystacks = [
    note.title,
    note.body,
    ...note.labels,
    ...note.checklistItems.map((item) => item.text)
  ];

  return haystacks.some((value) => String(value).toLowerCase().includes(searchTerm));
}

function createLabelsElement(labels) {
  const wrap = document.createElement('div');
  wrap.className = 'note-labels';
  wrap.setAttribute('aria-label', 'Labels');

  labels.forEach((label) => {
    const chip = document.createElement('span');
    chip.className = 'note-label';
    chip.textContent = label;
    wrap.appendChild(chip);
  });

  return wrap;
}

function toggleNotePinned(note) {
  const now = new Date().toISOString();

  notes = notes.map((item) => {
    if (item.id !== note.id) {
      return item;
    }

    return {
      ...item,
      pinned: !item.pinned,
      updatedAt: now
    };
  });

  saveNotes();
  renderNotes();
}

function createNoteCard(note) {
  const article = document.createElement('article');
  article.className = 'note-card card';

  if (note.pinned && !note.archived) {
    article.classList.add('is-pinned');
  }

  const header = document.createElement('div');
  header.className = 'note-card-header';

  const headingWrap = document.createElement('div');

  const meta = document.createElement('p');
  meta.className = 'note-meta';
  meta.textContent = note.type === 'checklist' ? 'Checklist note' : 'Plain text note';

  const title = document.createElement('h3');
  title.textContent = note.title.trim() || 'Untitled note';

  headingWrap.append(meta, title);
  header.appendChild(headingWrap);

  if (note.pinned && !note.archived) {
    const pinBadge = document.createElement('p');
    pinBadge.className = 'note-pin';
    pinBadge.textContent = 'Pinned';
    header.appendChild(pinBadge);
  }

  let contentElement;

  if (note.type === 'checklist' && note.checklistItems.length > 0) {
    const checklist = document.createElement('ul');
    checklist.className = 'note-checklist-preview';

    note.checklistItems.forEach((item) => {
      const listItem = document.createElement('li');
      listItem.textContent = item.text.trim() || 'Untitled item';

      if (item.checked) {
        listItem.classList.add('is-complete');
      }

      checklist.appendChild(listItem);
    });

    contentElement = checklist;
  } else {
    const body = document.createElement('p');
    body.className = 'note-body';

    if (note.body.trim()) {
      body.textContent = note.body;
    } else {
      body.textContent = note.type === 'checklist' ? 'No checklist items' : 'No body text';
      body.classList.add('is-empty');
    }

    contentElement = body;
  }

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

  const pinButton = document.createElement('button');
  pinButton.type = 'button';
  pinButton.className = 'pin-button';
  pinButton.textContent = note.pinned ? 'Unpin' : 'Pin';
  if (note.pinned) {
    pinButton.classList.add('is-pinned');
  }
  pinButton.setAttribute('aria-label', `${note.pinned ? 'Unpin' : 'Pin'} note ${note.title.trim() || 'Untitled note'}`);
  pinButton.addEventListener('click', () => {
    toggleNotePinned(note);
  });

  const archiveButton = document.createElement('button');
  archiveButton.type = 'button';
  archiveButton.className = 'secondary-button';
  archiveButton.textContent = note.archived ? 'Restore' : 'Archive';
  archiveButton.setAttribute(
    'aria-label',
    `${note.archived ? 'Restore' : 'Archive'} note ${note.title.trim() || 'Untitled note'}`
  );
  archiveButton.addEventListener('click', () => {
    const now = new Date().toISOString();

    notes = notes.map((item) => {
      if (item.id !== note.id) {
        return item;
      }

      return {
        ...item,
        archived: !item.archived,
        updatedAt: now
      };
    });

    saveNotes();

    if (editingNoteIdInput.value === note.id) {
      resetForm();
    }

    renderNotes();
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

  actions.append(editButton, pinButton, archiveButton, deleteButton);
  article.append(header, contentElement);

  if (note.labels.length > 0) {
    article.appendChild(createLabelsElement(note.labels));
  }

  article.append(dateText, actions);

  return article;
}

function renderEmptyState(visibleCount, baseCount) {
  if (visibleCount > 0) {
    emptyState.hidden = true;
    return;
  }

  emptyState.hidden = false;
  const heading = emptyState.querySelector('h3');
  const body = emptyState.querySelector('p');

  if (baseCount === 0) {
    if (currentView === 'archive') {
      heading.textContent = 'No archived notes';
      body.textContent = 'Archive a note from the active view to see it here.';
    } else {
      heading.textContent = 'No notes yet';
      body.textContent = 'Create your first note using the form on this page.';
    }

    return;
  }

  heading.textContent = 'No matching notes';
  body.textContent = currentView === 'archive'
    ? 'Try a different search term or restore notes from the archive when needed.'
    : 'Try a different search term or clear the search field to see your notes.';
}

function updateResultsSummary(visibleCount, baseCount) {
  const viewLabel = currentView === 'archive' ? 'archived notes' : 'active notes';

  if (baseCount === 0) {
    resultsSummary.textContent = `0 ${viewLabel}`;
    return;
  }

  if (currentSearchTerm) {
    resultsSummary.textContent = `${visibleCount} of ${baseCount} ${viewLabel}`;
    return;
  }

  resultsSummary.textContent = `${visibleCount} ${viewLabel}`;
}

function renderNotes() {
  notesGrid.innerHTML = '';

  const notesInView = notes
    .filter((note) => currentView === 'archive' ? note.archived : !note.archived)
    .sort((a, b) => {
      if (currentView === 'active' && a.pinned !== b.pinned) {
        return a.pinned ? -1 : 1;
      }

      return new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime();
    });

  const visibleNotes = notesInView.filter((note) => noteMatchesSearch(note, currentSearchTerm));

  updateResultsSummary(visibleNotes.length, notesInView.length);
  renderEmptyState(visibleNotes.length, notesInView.length);

  visibleNotes.forEach((note) => {
    notesGrid.appendChild(createNoteCard(note));
  });
}

noteTypeSelect.addEventListener('change', updateComposerMode);

addChecklistItemButton.addEventListener('click', () => {
  addChecklistItem();
});

searchInput.addEventListener('input', () => {
  currentSearchTerm = searchInput.value.trim().toLowerCase();
  renderNotes();
});

viewButtons.forEach((button) => {
  button.addEventListener('click', () => {
    updateViewButtons(button.dataset.view);
  });
});

cancelEditButton.addEventListener('click', () => {
  resetForm();
  noteTitleInput.focus();
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
  const labels = parseLabels(noteLabelsInput.value);
  const type = noteTypeSelect.value === 'checklist' ? 'checklist' : 'text';
  const checklistItems = getSanitizedChecklistItems();
  const now = new Date().toISOString();
  const editingId = editingNoteIdInput.value;

  if (type === 'checklist') {
    if (!title && checklistItems.length === 0) {
      window.alert('Please enter a title, at least one checklist item, or both before saving.');
      noteTitleInput.focus();
      return;
    }
  } else if (!title && !body) {
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
        body: type === 'checklist' ? '' : body,
        type,
        labels,
        checklistItems: type === 'checklist' ? checklistItems : [],
        updatedAt: now
      };
    });

    setFormStatus(`Updated ${title || 'Untitled note'}.`);
  } else {
    notes.unshift({
      id: createId(),
      title,
      body: type === 'checklist' ? '' : body,
      type,
      labels,
      pinned: false,
      archived: false,
      checklistItems: type === 'checklist' ? checklistItems : [],
      createdAt: now,
      updatedAt: now
    });

    setFormStatus(`Saved ${title || 'Untitled note'}.`);
  }

  saveNotes();
  renderNotes();
  noteForm.reset();
  editingNoteIdInput.value = '';
  saveButton.textContent = 'Save note';
  cancelEditButton.hidden = true;
  noteTypeSelect.value = 'text';
  draftChecklistItems = [];
  renderChecklistEditor();
  updateComposerMode();
  noteTitleInput.focus();
});

renderChecklistEditor();
updateComposerMode();
updateViewButtons('active');
renderNotes();
