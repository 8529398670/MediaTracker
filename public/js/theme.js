/* How the page looks: light, dark, or one of ten ready-made themes.
 *
 * Light is the default and stays it — never the phone's own setting. Picking
 * a theme is remembered in this browser only; nothing goes to the server.
 *
 * A preset is a mode plus, optionally, three colours. The mode sets two
 * attributes on <html>: `data-theme`, which this app's own stylesheet reads,
 * and `data-bs-theme`, which Bootstrap reads. Both, or half the page would
 * change and the other half would not. Bootstrap's own colour-mode script,
 * which follows prefers-color-scheme, is deliberately not included.
 *
 * The colours are written as the same custom properties app.css declares, so
 * every rule in the app already follows them; the shades between (--bg-2,
 * --line, …) are mixed from them rather than listed, so a preset stays three
 * numbers.
 *
 * This file is a plain script loaded in <head>, before the stylesheets paint,
 * so a saved dark theme never flashes light on the way in. It is not a module
 * on purpose: a module is deferred, and deferred is after the first paint.
 */
const Theme = {
  storageKey: 'mt.theme.v1',

  presets: [
    { key: 'light', label: 'Light', mode: 'light' },
    { key: 'dark', label: 'Dark', mode: 'dark' },
    { key: 'ocean', label: 'Ocean', mode: 'light', accent: '#0b7285', background: '#eef6f8', surface: '#ffffff' },
    { key: 'forest', label: 'Forest', mode: 'light', accent: '#2b8a3e', background: '#f1f6ef', surface: '#ffffff' },
    { key: 'sepia', label: 'Sepia', mode: 'light', accent: '#9c5a1c', background: '#f6f0e4', surface: '#fbf7ef' },
    { key: 'grape', label: 'Grape', mode: 'light', accent: '#7048c8', background: '#f5f2fc', surface: '#ffffff' },
    { key: 'pink', label: 'Pink', mode: 'light', accent: '#c2255c', background: '#fdf0f5', surface: '#ffffff' },
    // Wright State: green on off white, and gold on black over dark green.
    { key: 'wsu', label: 'WSU', mode: 'light', accent: '#046a38', background: '#f2f1f0', surface: '#ffffff' },
    { key: 'midnight', label: 'Midnight', mode: 'dark', accent: '#8c7cff', background: '#0e1020', surface: '#171a30' },
    { key: 'slate', label: 'Slate', mode: 'dark', accent: '#4fb3a9', background: '#15191e', surface: '#1d232a' },
    { key: 'dark_pink', label: 'Dark pink', mode: 'dark', accent: '#f06595', background: '#1f0d16', surface: '#2a1220' },
    { key: 'wsu_dark', label: 'WSU dark', mode: 'dark', accent: '#cba052', background: '#101820', surface: '#00482b' },
  ],

  current: 'light',

  find(key) {
    return this.presets.find((preset) => preset.key === key) || this.presets[0];
  },

  restore() {
    let saved = '';
    try { saved = window.localStorage.getItem(this.storageKey) || ''; }
    catch { /* storage blocked (private window): stay light */ }
    this.current = this.find(saved).key;
    this.apply(this.find(this.current));
  },

  set(key) {
    this.current = this.find(key).key;
    try {
      if (this.current === 'light') window.localStorage.removeItem(this.storageKey);
      else window.localStorage.setItem(this.storageKey, this.current);
    } catch { /* not remembered for next time, but applied now */ }
    this.apply(this.find(this.current));
  },

  apply(preset) {
    const root = document.documentElement;
    const style = root.style;

    root.setAttribute('data-theme', preset.mode);
    if (preset.mode === 'dark') root.setAttribute('data-bs-theme', 'dark');
    else root.removeAttribute('data-bs-theme');

    // No colours of its own: plain light or plain dark, as app.css declares
    // them. Clear anything a previous preset left inline.
    const own = ['--accent', '--on-accent', '--bg', '--bg-2', '--surface',
      '--surface-2', '--line', '--line-soft'];
    own.forEach((name) => style.removeProperty(name));

    if (preset.accent) {
      style.setProperty('--accent', preset.accent);
      // Whatever the accent is, the text sitting on it has to stay readable.
      style.setProperty('--on-accent',
        this.contrast(preset.accent, '#ffffff') >= this.contrast(preset.accent, '#0b0d10')
          ? '#ffffff' : '#0b0d10');
    }
    if (preset.background) {
      style.setProperty('--bg', preset.background);
      style.setProperty('--bg-2', `color-mix(in srgb, var(--text) 7%, ${preset.background})`);
      style.setProperty('--line', `color-mix(in srgb, var(--text) 16%, ${preset.background})`);
      style.setProperty('--line-soft', `color-mix(in srgb, var(--text) 9%, ${preset.background})`);
    }
    if (preset.surface) {
      style.setProperty('--surface', preset.surface);
      style.setProperty('--surface-2', `color-mix(in srgb, var(--text) 7%, ${preset.surface})`);
    }

    // The browser's own chrome, so the phone's status bar matches the page.
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) {
      meta.setAttribute('content',
        preset.background || (preset.mode === 'dark' ? '#0a0e14' : '#f6f7fb'));
    }
  },

  /* The picker: one button per preset, each drawn in its own colours. */
  render(root, onPick) {
    while (root.firstChild) root.firstChild.remove();
    const made = [];

    const update = () => made.forEach(({ button, key }) => {
      button.classList.toggle('active', key === this.current);
      button.setAttribute('aria-pressed', String(key === this.current));
    });

    this.presets.forEach((preset) => {
      const swatch = document.createElement('span');
      swatch.className = `theme-swatch${preset.mode === 'dark' ? ' theme-swatch-dark' : ''}`;
      if (preset.background) swatch.style.setProperty('--swatch-bg', preset.background);
      if (preset.accent) swatch.style.setProperty('--swatch-accent', preset.accent);

      const name = document.createElement('span');
      name.textContent = preset.label;

      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'btn btn-outline-secondary theme-choice';
      button.append(swatch, name);
      button.addEventListener('click', () => {
        this.set(preset.key);
        update();
        if (onPick) onPick(preset.key);
      });

      root.append(button);
      made.push({ button, key: preset.key });
    });

    update();
    return root;
  },

  /* Relative luminance (WCAG) of #rrggbb, and the ratio between two. */
  luminance(hex) {
    const channel = (offset) => {
      const value = parseInt(hex.slice(offset, offset + 2), 16) / 255;
      return value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
    };
    return 0.2126 * channel(1) + 0.7152 * channel(3) + 0.0722 * channel(5);
  },

  contrast(first, second) {
    const a = this.luminance(first);
    const b = this.luminance(second);
    return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
  },
};

Theme.restore();

// The modules reach it through the window; this file runs before they do.
window.Theme = Theme;
