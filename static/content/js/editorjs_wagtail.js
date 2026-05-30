/**
 * Initialise Editor.js dans les panels Wagtail.
 * Chaque widget `.editorjs-wrapper` est auto-découvert et initialisé.
 * S'adapte au rechargement dynamique (panels Wagtail via AJAX).
 */

// ── Outils héritage (GalleryTool, FileTool) ──────────────────────────────────
// Ces outils affichent du contenu importé de WordPress.
// Pas de toolbox() → ils n'apparaissent pas dans la barre d'outils,
// mais ils rendent correctement les blocs existants.

class GalleryTool {
  // Pas de toolbox() : rendu uniquement, pas de création depuis la barre
  static get isReadOnlySupported() { return true; }
  constructor({ data, readOnly }) {
    this.data = { images: data.images || [], columns: data.columns || 3 };
    this.readOnly = readOnly;
  }
  render() {
    const wrap = document.createElement('div');
    const images = this.data.images;
    const cols = this.data.columns || 3;
    wrap.innerHTML = `
      <div style="border:1px solid #d1d5db;border-radius:8px;padding:.75rem;background:#f9fafb;">
        <div style="font-size:.75rem;color:#6b7280;font-weight:600;margin-bottom:.5rem;">
          📷 Galerie — ${images.length} image(s)
        </div>
        <div style="display:grid;grid-template-columns:repeat(${cols},1fr);gap:4px;">
          ${images.map(img => `<img src="${img.url || ''}" style="width:100%;aspect-ratio:1;object-fit:cover;border-radius:3px;" alt="">`).join('')}
        </div>
      </div>`;
    return wrap;
  }
  save() { return this.data; }
  static get sanitize() { return { images: true, columns: {} }; }
}

class FileTool {
  // Pas de toolbox() : rendu uniquement, pas de création depuis la barre
  static get isReadOnlySupported() { return true; }
  constructor({ data }) { this.data = data || {}; }
  render() {
    const wrap = document.createElement('div');
    if (this.data.url) {
      const title = this.data.title || this.data.name || this.data.url;
      wrap.innerHTML = `<a href="" style="color:#2563eb;text-decoration:underline;pointer-events:none;">📎 ${title}</a>`;
      wrap.querySelector('a').setAttribute('href', this.data.url);
    } else {
      wrap.innerHTML = `<span style="color:#9ca3af;font-size:.85rem;">📎 Fichier (aucune URL)</span>`;
    }
    return wrap;
  }
  save() { return this.data; }
}

// ── Initialisation ─────────────────────────────────────────────────────────────

function initEditorJsWidget(wrapper) {
  if (wrapper.dataset.editorjsInit === '1') return;
  wrapper.dataset.editorjsInit = '1';

  const fieldId = wrapper.dataset.fieldId;
  const hiddenInput = wrapper.querySelector('input[type=hidden]');
  const container = wrapper.querySelector('.editorjs-container');

  if (!hiddenInput || !container || typeof EditorJS === 'undefined') return;

  const raw = hiddenInput.value.trim();
  let initialData = { blocks: [] };
  if (raw) {
    if (raw.startsWith('{')) {
      try { initialData = JSON.parse(raw); } catch (e) {}
    } else if (raw.length > 0) {
      initialData = { blocks: [{ type: 'paragraph', data: { text: raw } }] };
    }
  }

  const uploadUrl = window.EDITORJS_UPLOAD_URL || '/upload/image/';
  const csrfToken = document.cookie.match(/csrftoken=([^;]+)/)?.[1] || '';

  const editor = new EditorJS({
    holder: container,
    placeholder: 'Cliquez ici pour commencer à rédiger…',
    data: initialData,
    tools: {
      header: { class: Header, config: { levels: [2, 3, 4], defaultLevel: 2 } },
      list: { class: List, inlineToolbar: true, config: { defaultStyle: 'unordered' } },
      quote: { class: Quote, inlineToolbar: true, config: { quotePlaceholder: 'Citation…', captionPlaceholder: 'Source' } },
      code: { class: CodeTool },
      delimiter: Delimiter,
      table: { class: Table, inlineToolbar: true, config: { rows: 2, cols: 3 } },
      inlineCode: { class: InlineCode },
      gallery: { class: GalleryTool },
      file: { class: FileTool },
      image: {
        class: ImageTool,
        config: {
          endpoints: { byFile: uploadUrl },
          additionalRequestHeaders: { 'X-CSRFToken': csrfToken },
          captionPlaceholder: "Légende de l'image",
          buttonContent: 'Choisir une image',
        },
      },
      embed: {
        class: Embed,
        config: { services: { youtube: true, vimeo: true, instagram: true, twitter: true } },
      },
    },
    i18n: {
      messages: {
        toolNames: {
          Text: 'Paragraphe', Heading: 'Titre', List: 'Liste',
          Quote: 'Citation', Code: 'Code', Delimiter: 'Séparateur',
          Table: 'Tableau', Image: 'Image', Bold: 'Gras',
          Italic: 'Italique', InlineCode: 'Code inline', Embed: 'Vidéo / Embed',
          Gallery: 'Galerie', File: 'Fichier',
        },
        ui: {
          blockTunes: { toggler: { 'Click to tune': 'Options', 'or drag to move': 'ou glisser' } },
          toolbar: { toolbox: { Add: 'Ajouter un bloc' } },
          popover: { Filter: 'Rechercher…', 'Nothing found': 'Aucun résultat' },
        },
        blockTunes: {
          delete: { Delete: 'Supprimer', 'Click to delete': 'Confirmer' },
          moveUp: { 'Move up': 'Monter' },
          moveDown: { 'Move down': 'Descendre' },
        },
      },
    },
  });

  // Sauvegarde avant soumission du formulaire Wagtail
  const form = wrapper.closest('form');
  if (form && !form.dataset.editorjsBound) {
    form.dataset.editorjsBound = '1';
    form.addEventListener('submit', async function (e) {
      // Récupère tous les éditeurs du formulaire
      const wrappers = form.querySelectorAll('.editorjs-wrapper[data-editorjs-init="1"]');
      for (const w of wrappers) {
        if (w._editor) {
          try {
            const saved = await w._editor.save();
            w.querySelector('input[type=hidden]').value = JSON.stringify(saved);
          } catch (err) { console.error('EditorJS save error:', err); }
        }
      }
    }, { capture: true });
  }

  wrapper._editor = editor;
}

function initAllEditorJsWidgets(root) {
  const wrappers = (root || document).querySelectorAll('.editorjs-wrapper:not([data-editorjs-init="1"])');
  wrappers.forEach(initEditorJsWidget);
}

// Init au chargement de la page
document.addEventListener('DOMContentLoaded', () => initAllEditorJsWidgets());

// Observe les ajouts dynamiques de DOM (tabs Wagtail, panels inline)
if (typeof MutationObserver !== 'undefined') {
  const observer = new MutationObserver(() => initAllEditorJsWidgets());
  observer.observe(document.body, { childList: true, subtree: true });
}
