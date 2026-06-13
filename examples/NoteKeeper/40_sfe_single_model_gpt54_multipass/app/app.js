document.addEventListener('DOMContentLoaded', () => {
  const state = {
    currentView: 'active',
    noteType: 'text'
  };

  const elements = {
    viewButtons: Array.from(document.querySelectorAll('[data-view]')),
    noteTypeSelect: document.querySelector('#note-type'),
    checklistEditor: document.querySelector('#checklist-editor'),
    checklistItems: document.querySelector('#checklist-items'),
    addChecklistItemButton: document.querySelector('#add-checklist-item'),
    notesHeading: document.querySelector('#notes-heading'),
    notesDescription: document.querySelector('#notes-description'),
    notesList: document.querySelector('#notes-list'),
    emptyState: document.querySelector('#empty-state')
  };

  const placeholderNotes = {
    active: [
      {
        title: 'Project outline',
        body: 'Capture goals, milestones, and quick references for the week.',
        labels: ['work', 'planning']
      },
      {
        title: 'Weekend errands',
        body: 'Switch to checklist mode to sketch out shopping and chores.',
        labels: ['home']
      }
    ],
    archive: [
      {
        title: 'Archived reference',
        body: 'Older notes will appear here when archived from the active view.',
        labels: ['archive']
      }
    ]
  };

  function updateViewButtons() {
    elements.viewButtons.forEach((button) => {
      const isActive = button.dataset.view === state.currentView;
      button.classList.toggle('is-active', isActive);
      button.setAttribute('aria-pressed', String(isActive));
    });
  }

  function renderPlaceholderNotes() {
    const notes = placeholderNotes[state.currentView] || [];
    elements.notesList.innerHTML = '';

    if (notes.length === 0) {
      elements.emptyState.hidden = false;
      return;
    }

    elements.emptyState.hidden = true;

    notes.forEach((note) => {
      const article = document.createElement('article');
      article.className = 'note-card placeholder-note';

      const labels = note.labels && note.labels.length
        ? `<ul class="card-labels">${note.labels.map((label) => `<li>${label}</li>`).join('')}</ul>`
        : '';

      article.innerHTML = `
        <div class="card-content">
          <p class="card-eyebrow">Placeholder note</p>
          <h3>${note.title}</h3>
          <p>${note.body}</p>
          ${labels}
        </div>
        <div class="card-actions" aria-label="Placeholder note actions">
          <button type="button" disabled>Edit</button>
          <button type="button" disabled>${state.currentView === 'active' ? 'Archive' : 'Restore'}</button>
        </div>
      `;

      elements.notesList.appendChild(article);
    });
  }

  function updateNotesCopy() {
    const isActiveView = state.currentView === 'active';
    elements.notesHeading.textContent = isActiveView ? 'Active notes' : 'Archived notes';
    elements.notesDescription.textContent = isActiveView
      ? 'Scaffold cards for your current notes appear here.'
      : 'Archived placeholders appear here until storage and CRUD arrive in the next pass.';
  }

  function setView(view) {
    state.currentView = view;
    updateViewButtons();
    updateNotesCopy();
    renderPlaceholderNotes();
  }

  function syncChecklistEditor() {
    const showChecklist = state.noteType === 'checklist';
    elements.checklistEditor.hidden = !showChecklist;
    elements.checklistEditor.setAttribute('aria-hidden', String(!showChecklist));
  }

  function createChecklistItem(value = '') {
    const item = document.createElement('div');
    item.className = 'checklist-edit-row';
    item.innerHTML = `
      <label>
        <span class="sr-only">Checklist item</span>
        <input type="text" name="checklist-item" placeholder="Checklist item" value="${value}">
      </label>
      <button type="button" class="button button-secondary checklist-remove">Remove</button>
    `;
    return item;
  }

  function ensureChecklistHasItems() {
    const itemCount = elements.checklistItems.querySelectorAll('.checklist-edit-row').length;
    if (itemCount === 0) {
      elements.checklistItems.appendChild(createChecklistItem());
    }
    updateChecklistRemoveButtons();
  }

  function updateChecklistRemoveButtons() {
    const rows = Array.from(elements.checklistItems.querySelectorAll('.checklist-edit-row'));
    rows.forEach((row) => {
      const removeButton = row.querySelector('.checklist-remove');
      if (removeButton) {
        removeButton.disabled = rows.length === 1;
      }
    });
  }

  elements.viewButtons.forEach((button) => {
    button.addEventListener('click', () => {
      const { view } = button.dataset;
      if (view && view !== state.currentView) {
        setView(view);
      }
    });
  });

  if (elements.noteTypeSelect) {
    state.noteType = elements.noteTypeSelect.value || 'text';

    elements.noteTypeSelect.addEventListener('change', (event) => {
      state.noteType = event.target.value;
      syncChecklistEditor();

      if (state.noteType === 'checklist') {
        ensureChecklistHasItems();
      }
    });
  }

  if (elements.addChecklistItemButton) {
    elements.addChecklistItemButton.addEventListener('click', () => {
      elements.checklistItems.appendChild(createChecklistItem());
      updateChecklistRemoveButtons();

      const newestInput = elements.checklistItems.lastElementChild?.querySelector('input');
      if (newestInput) {
        newestInput.focus();
      }
    });
  }

  if (elements.checklistItems) {
    elements.checklistItems.addEventListener('click', (event) => {
      const removeButton = event.target.closest('.checklist-remove');
      if (!removeButton) return;

      removeButton.closest('.checklist-edit-row')?.remove();
      ensureChecklistHasItems();
    });
  }

  syncChecklistEditor();
  ensureChecklistHasItems();
  setView(state.currentView);
});
