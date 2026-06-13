(() => {
  const STORAGE_KEY = 'NoteKeeper.notes.v1';

  const state = {
    view: 'active',
    search: '',
    notes: [],
    editingId: null,
  };

  const elements = {
    form: document.getElementById('note-form'),
    saveButton: document.getElementById('save-note-button'),
    cancelEditButton: document.getElementById('cancel-edit-button'),
    noteType: document.getElementById('note-type'),
    checklistItems: document.getElementById('checklist-items'),
    addChecklistItem: document.getElementById('add-checklist-item'),
    searchInput: document.getElementById('search-input'),
    notesList: document.getElementById('notes-list'),
    viewState: document.getElementById('view-state'),
    viewButtons: Array.from(document.querySelectorAll('.view-button')),
    cardTemplate: document.getElementById('note-card-template'),
    checklistItemTemplate: document.getElementById('checklist-item-template'),
    emptyStateTemplate: document.getElementById('empty-state-template'),
  };

  function uid() {
    return `note-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }

  function readNotes() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return [];
      const parsed = JSON.parse(raw);
      if (!Array.isArray(parsed)) return [];
      return parsed
        .filter((note) => note && typeof note === 'object')
        .map((note) => ({
          id: String(note.id || uid()),
          title: String(note.title || ''),
          body: String(note.body || ''),
          noteType: note.noteType === 'checklist' ? 'checklist' : 'text',
          labels: Array.isArray(note.labels) ? note.labels.map((label) => String(label).trim()).filter(Boolean) : [],
          pinned: Boolean(note.pinned),
          archived: Boolean(note.archived),
          createdAt: Number(note.createdAt) || Date.now(),
          updatedAt: Number(note.updatedAt) || Date.now(),
          checklistItems: Array.isArray(note.checklistItems)
            ? note.checklistItems.map((item) => ({
              id: String(item.id || uid()),
              text: String(item.text || ''),
              checked: Boolean(item.checked),
            }))
            : [],
        }));
    } catch {
      return [];
    }
  }

  function saveNotes() {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state.notes));
  }

  function normalizeLabels(value) {
    return value.split(',').map((part) => part.trim()).filter(Boolean);
  }

  function getFormData() {
    const formData = new FormData(elements.form);
    return {
      id: String(formData.get('id') || ''),
      title: String(formData.get('title') || '').trim(),
      body: String(formData.get('body') || '').trim(),
      noteType: formData.get('noteType') === 'checklist' ? 'checklist' : 'text',
      labels: normalizeLabels(String(formData.get('labels') || '')),
      checklistItems: Array.from(elements.checklistItems.querySelectorAll('.checklist-item-row')).map((row) => ({
        id: row.dataset.itemId || uid(),
        checked: row.querySelector('.checklist-complete').checked,
        text: row.querySelector('.checklist-text').value.trim(),
      })).filter((item) => item.text || item.checked),
    };
  }

  function setFormMode(note) {
    state.editingId = note ? note.id : null;
    elements.saveButton.textContent = note ? 'Save changes' : 'Save note';
    elements.cancelEditButton.hidden = !note;
  }

  function clearChecklist() {
    elements.checklistItems.innerHTML = '';
  }

  function renderChecklistEditor(items = []) {
    clearChecklist();
    if (!items.length) return;
    items.forEach((item) => addChecklistRow(item));
  }

  function addChecklistRow(item = { text: '', checked: false }) {
    const node = elements.checklistItemTemplate.content.firstElementChild.cloneNode(true);
    node.dataset.itemId = item.id || uid();
    node.querySelector('.checklist-complete').checked = Boolean(item.checked);
    node.querySelector('.checklist-complete').addEventListener('change', persistDraftState);
    node.querySelector('.checklist-text').value = item.text || '';
    node.querySelector('.checklist-text').addEventListener('input', persistDraftState);
    node.querySelector('.checklist-remove').addEventListener('click', () => {
      node.remove();
      persistDraftState();
    });
    elements.checklistItems.appendChild(node);
  }

  function persistDraftState() {
    // Intentionally left simple; the editable form is local and not persisted until save.
  }

  function resetForm() {
    elements.form.reset();
    elements.form.elements.id.value = '';
    elements.noteType.value = 'text';
    clearChecklist();
    setFormMode(null);
  }

  function fillForm(note) {
    elements.form.elements.id.value = note.id;
    elements.form.elements.title.value = note.title;
    elements.form.elements.body.value = note.body;
    elements.form.elements.labels.value = note.labels.join(', ');
    elements.noteType.value = note.noteType;
    renderChecklistEditor(note.checklistItems);
    setFormMode(note);
  }

  function matchesSearch(note, query) {
    if (!query) return true;
    const haystack = [
      note.title,
      note.body,
      note.labels.join(' '),
      note.checklistItems.map((item) => item.text).join(' '),
    ].join(' ').toLowerCase();
    return haystack.includes(query.toLowerCase());
  }

  function visibleNotes() {
    return state.notes
      .filter((note) => note.archived === (state.view === 'archived'))
      .filter((note) => matchesSearch(note, state.search))
      .sort((a, b) => (b.pinned - a.pinned) || (b.updatedAt - a.updatedAt));
  }

  function noteSummary(note) {
    if (note.noteType === 'checklist') {
      const completed = note.checklistItems.filter((item) => item.checked).length;
      return `${completed}/${note.checklistItems.length || 0} checklist items complete`;
    }
    return note.body || 'No body text';
  }

  function createTextNode(text, className) {
    const el = document.createElement('p');
    if (className) el.className = className;
    el.textContent = text;
    return el;
  }

  function renderNoteCard(note) {
    const card = elements.cardTemplate.content.firstElementChild.cloneNode(true);
    card.dataset.noteId = note.id;
    if (state.editingId === note.id) card.classList.add('card-editing');
    card.classList.toggle('pinned', note.pinned);
    card.querySelector('.note-title').textContent = note.title || 'Untitled note';
    card.querySelector('.note-meta').textContent = noteSummary(note);
    const pinBadge = card.querySelector('.pin-badge');
    pinBadge.hidden = !note.pinned;

    const body = card.querySelector('.note-body');
    body.replaceChildren();
    if (note.noteType === 'checklist') {
      const list = document.createElement('ul');
      list.className = 'checklist-display';
      note.checklistItems.forEach((item) => {
        const li = document.createElement('li');
        const mark = document.createElement('input');
        mark.type = 'checkbox';
        mark.checked = item.checked;
        mark.disabled = true;
        const text = document.createElement('span');
        text.textContent = item.text;
        if (item.checked) text.style.textDecoration = 'line-through';
        li.append(mark, text);
        list.appendChild(li);
      });
      body.appendChild(list);
    } else {
      body.appendChild(createTextNode(note.body || 'No body text'));
    }

    const labels = card.querySelector('.label-list');
    labels.replaceChildren();
    note.labels.forEach((label) => {
      const li = document.createElement('li');
      li.textContent = label;
      labels.appendChild(li);
    });

    const actions = card.querySelector('.note-actions');
    actions.replaceChildren();
    actions.append(
      actionButton('Edit', () => fillForm(note)),
      actionButton(note.pinned ? 'Unpin' : 'Pin', () => togglePin(note.id)),
      actionButton(note.archived ? 'Restore' : 'Archive', () => toggleArchive(note.id)),
      actionButton('Delete', () => deleteNote(note.id), true),
    );

    return card;
  }

  function actionButton(label, onClick, danger = false) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = `icon-button${danger ? ' danger' : ''}`;
    button.textContent = label;
    button.addEventListener('click', onClick);
    return button;
  }

  function renderEmptyState() {
    const empty = elements.emptyStateTemplate.content.firstElementChild.cloneNode(true);
    const hasSearch = Boolean(state.search.trim());
    empty.querySelector('.empty-title').textContent = hasSearch ? 'No matching notes' : (state.view === 'archived' ? 'Archive is empty' : 'No notes yet');
    empty.querySelector('.empty-body').textContent = hasSearch
      ? 'Try a different search term or clear the search field.'
      : (state.view === 'archived'
        ? 'Archived notes will appear here after you archive them.'
        : 'Create your first note above. It will stay in your browser on this device.');
    return empty;
  }

  function render() {
    elements.viewButtons.forEach((button) => {
      const isActive = button.dataset.view === state.view;
      button.classList.toggle('is-active', isActive);
      button.setAttribute('aria-pressed', String(isActive));
    });
    elements.viewState.textContent = state.view === 'archived' ? 'Showing archived notes' : 'Showing active notes';
    const notes = visibleNotes();
    elements.notesList.replaceChildren();
    if (!notes.length) {
      elements.notesList.appendChild(renderEmptyState());
      return;
    }
    notes.forEach((note) => elements.notesList.appendChild(renderNoteCard(note)));
  }

  function persistAndRender() {
    saveNotes();
    render();
  }

  function upsertNote(data) {
    const now = Date.now();
    if (data.id) {
      state.notes = state.notes.map((note) => note.id === data.id ? {
        ...note,
        title: data.title,
        body: data.body,
        noteType: data.noteType,
        labels: data.labels,
        checklistItems: data.checklistItems,
        updatedAt: now,
      } : note);
    } else {
      state.notes.unshift({
        id: uid(),
        title: data.title,
        body: data.body,
        noteType: data.noteType,
        labels: data.labels,
        checklistItems: data.checklistItems,
        pinned: false,
        archived: false,
        createdAt: now,
        updatedAt: now,
      });
    }
  }

  function togglePin(id) {
    state.notes = state.notes.map((note) => note.id === id ? { ...note, pinned: !note.pinned, updatedAt: Date.now() } : note);
    persistAndRender();
  }

  function toggleArchive(id) {
    state.notes = state.notes.map((note) => note.id === id ? { ...note, archived: !note.archived, updatedAt: Date.now() } : note);
    persistAndRender();
  }

  function deleteNote(id) {
    state.notes = state.notes.filter((note) => note.id !== id);
    if (state.editingId === id) resetForm();
    persistAndRender();
  }

  elements.form.addEventListener('submit', (event) => {
    event.preventDefault();
    const data = getFormData();
    upsertNote(data);
    saveNotes();
    resetForm();
    render();
  });

  elements.form.addEventListener('reset', () => {
    window.setTimeout(resetForm, 0);
  });

  elements.cancelEditButton.addEventListener('click', () => {
    resetForm();
  });

  elements.noteType.addEventListener('change', () => {
    if (elements.noteType.value !== 'checklist') {
      clearChecklist();
    }
  });

  elements.addChecklistItem.addEventListener('click', () => {
    addChecklistRow();
  });

  elements.searchInput.addEventListener('input', (event) => {
    state.search = event.target.value;
    render();
  });

  elements.viewButtons.forEach((button) => {
    button.addEventListener('click', () => {
      state.view = button.dataset.view === 'archived' ? 'archived' : 'active';
      render();
    });
  });

  state.notes = readNotes();
  render();
  document.documentElement.dataset.appReady = 'true';
})();
