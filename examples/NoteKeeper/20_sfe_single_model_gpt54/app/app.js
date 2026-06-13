const notesRegion = document.getElementById('notes-region');

const sampleNotes = [
  {
    title: 'Welcome to NoteKeeper',
    type: 'Text note',
    body: 'This static scaffold sets up the local-first notes workspace. Creating, editing, persistence, and search will be added in the next tasks.',
    labels: ['Welcome', 'Scaffold'],
    pinned: true,
    actions: ['Edit', 'Archive', 'Delete']
  },
  {
    title: 'Checklist preview',
    type: 'Checklist note',
    body: 'Milk\nProject outline\nCall mom',
    labels: ['Home', 'Preview'],
    pinned: false,
    actions: ['Edit', 'Pin', 'Archive', 'Delete']
  }
];

function createButton(label) {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'secondary-button';
  button.textContent = label;
  return button;
}

function renderTags(labels) {
  const tagRow = document.createElement('div');
  tagRow.className = 'tag-row';

  labels.forEach((label) => {
    const tag = document.createElement('span');
    tag.className = 'tag';
    tag.textContent = label;
    tagRow.appendChild(tag);
  });

  return tagRow;
}

function renderNoteCard(note) {
  const article = document.createElement('article');
  article.className = `note-card${note.pinned ? ' is-pinned' : ''}`;

  const title = note.title || 'Untitled note';
  const pinStatus = note.pinned ? 'Pinned' : 'Unpinned';

  article.innerHTML = `
    <header>
      <div>
        <h3>${title}</h3>
        <p class="note-meta">${note.type} · ${pinStatus}</p>
      </div>
    </header>
    <p>${note.body.replace(/\n/g, '<br>')}</p>
  `;

  article.appendChild(renderTags(note.labels));

  const actions = document.createElement('div');
  actions.className = 'card-actions';
  note.actions.forEach((label) => actions.appendChild(createButton(label)));
  article.appendChild(actions);

  return article;
}

function renderScaffold() {
  if (!notesRegion) {
    return;
  }

  notesRegion.innerHTML = '';

  if (sampleNotes.length === 0) {
    notesRegion.innerHTML = '<div class="empty-state"><p>No notes yet. Create your first note to get started.</p></div>';
    return;
  }

  sampleNotes.forEach((note) => notesRegion.appendChild(renderNoteCard(note)));
}

renderScaffold();
