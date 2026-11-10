// How the page looks: light, dark, or another theme.
//
// Light is the default and stays it -- never the OS setting. Dark is
// Bootstrap's own dark mode (<html data-bs-theme="dark">). Light is the
// attribute being absent, and Bootstrap's colour-mode script, which would
// follow prefers-color-scheme, is deliberately not included.
//
// A theme is a mode and a few colours. colours() works out everything else
// the page needs from those -- text, links, borders, tints -- each pushed until
// it is readable. Its overrides replace any of the worked-out colours by name,
// and dropping one puts the readable colour back.
//
// Which themes there are, and which one someone uses, is kept on their
// account (models/themes.go): their own list, or until they change something,
// the defaults an admin set, or until an admin does, the built-in ones below.
// The Appearance screen (themes_editor.js) edits both lists.
//
// The theme in use is also kept in this browser, whole, so the first paint --
// and the pages before signing in -- are already in it. The account is the
// authority: load( me ) replaces what was kept as soon as /api/me answers.
//
// This file is loaded in <head>, before the stylesheet's first paint, so a
// saved dark theme never flashes light on the way in.
//
// Brand colours live in ThemePalettes, named, whether a theme uses them or not,
// so the rest are there for whoever needs them next.
const ThemePalettes = {
  // Wright State University. Primary: green and gold. The rest are its accents.
  wsu: {
    green: "#046a38",
    gold: "#cba052",
    dark_green: "#00482b",
    deep_gold: "#ae8643",
    yellow: "#f8e08e",
    leaf: "#719949",
    beige: "#dcd59a",
    black: "#101820",
    faded_gold: "#e7e3c6",
    off_white: "#f2f1f0",
  },
};

const Theme = {
  storageKey: "theme",
  // What redraws when the theme changes: the Appearance screen.
  onChange: [],

  // The built-in themes: what everyone has until an admin saves defaults. accent
  // is the main colour: what you can press. second says where you are: the
  // active nav item, headings, progress, info. background and surface are the
  // page and the cards, when the mode's will not do. Names come from
  // language.yaml (theme.preset_<id>) until a list is saved; a saved list keeps
  // its own names.
  builtIn: [
    { id: "light" , mode: "light" , accent: "#1f5fd6" , second: "#0b7a75" },
    { id: "dark" , mode: "dark" , accent: "#6ea0ff" , second: "#5fd3c4" },
    { id: "ocean" , mode: "light" , accent: "#0b7285" , second: "#bd5418" , background: "#eef6f8" , surface: "#ffffff" },
    { id: "forest" , mode: "light" , accent: "#28843b" , second: "#8a6a12" , background: "#f1f6ef" , surface: "#ffffff" },
    { id: "sepia" , mode: "light" , accent: "#9c5a1c" , second: "#2f6f6a" , background: "#f6f0e4" , surface: "#fbf7ef" },
    { id: "grape" , mode: "light" , accent: "#7048c8" , second: "#c0267e" , background: "#f5f2fc" , surface: "#ffffff" },
    { id: "pink" , mode: "light" , accent: "#c2255c" , second: "#6b3fc0" , background: "#fdf0f5" , surface: "#ffffff" },
    // Wright State University: Green on Off White, and Gold on Black with Dark Green panels.
    { id: "wsu" , mode: "light" , accent: ThemePalettes.wsu.green , second: ThemePalettes.wsu.gold , background: ThemePalettes.wsu.off_white , surface: "#ffffff" },
    { id: "midnight" , mode: "dark" , accent: "#8c7cff" , second: "#ffb86b" , background: "#0e1020" , surface: "#171a30" },
    { id: "slate" , mode: "dark" , accent: "#4fb3a9" , second: "#e6b450" , background: "#15191e" , surface: "#1d232a" },
    { id: "cerise" , mode: "dark" , accent: "#f06595" , second: "#ffa8d0" , background: "#1f0d16" , surface: "#2a1220" },
    { id: "wsu_dark" , mode: "dark" , accent: ThemePalettes.wsu.gold , second: ThemePalettes.wsu.yellow , background: ThemePalettes.wsu.black , surface: ThemePalettes.wsu.dark_green },
  ],

  // What a theme leaves out.
  modes: {
    light: { background: "#f7f8fa" , surface: "#ffffff" , text: "#212529" },
    dark: { background: "#101215" , surface: "#191c21" , text: "#dee2e6" },
  },

  // How much of the second colour goes into each layer, in percent, so a nested
  // card stands off its card and the card off the page.
  tints: { page: 3.5 , surface: 1.75 , nested: 8.75 , chrome: 10 , info: 14 , infoBorder: 45 },

  // Field of colours() -> custom property in style.css, which hands them on to
  // Bootstrap. Every one of them can be overridden.
  vars: {
    text: "--app-text",
    accent: "--app-accent",
    accentFg: "--app-accent-fg",
    second: "--app-second",
    secondFg: "--app-second-fg",
    secondText: "--app-second-text",
    link: "--app-link",
    navLink: "--app-nav-link",
    background: "--app-bg",
    surface: "--app-surface",
    nested: "--app-nested",
    chrome: "--app-chrome",
    info: "--app-info",
    infoBorder: "--app-info-border",
    border: "--app-border",
  },

  // Pairs that must stay readable: [ front , back ] fields of colours(). check()
  // and scripts/check_themes.js both use them. Names are language.yaml keys
  // (theme.check_<name>).
  pairs: {
    text_card: [ "text" , "surface" ],
    text_nested: [ "text" , "nested" ],
    text_info: [ "text" , "info" ],
    link: [ "link" , "nested" ],
    button: [ "accentFg" , "accent" ],
    heading: [ "secondText" , "nested" ],
    active_nav: [ "secondFg" , "second" ],
    sidebar_link: [ "navLink" , "chrome" ],
  },

  // The themes on offer, and the one in use (its id).
  list: [],
  // Whether list is the person's own rather than the defaults.
  custom: false,
  current: "light",
  // WCAG AA for text.
  minContrast: 4.5,

  // A built-in theme with its name filled in, ready to be saved in a list.
  named( theme ) {
    const copy = this.copy( theme );
    if ( !copy.name ) copy.name = ( typeof I18n === "undefined" ? "" : I18n.get( "theme.preset_" + theme.id ) ) || theme.id;
    return copy;
  },

  copy( theme ) {
    const copy = Object.assign( {} , theme );
    copy.overrides = Object.assign( {} , theme.overrides || {} );
    return copy;
  },

  find( id ) {
    return this.list.find( function ( theme ) { return theme.id === id; } ) || this.list[ 0 ] || this.builtIn[ 0 ];
  },

  // What was kept in this browser: a whole theme, or (from before themes could
  // be edited) a built-in one's id.
  restore() {
    let saved = null;
    try {
      const raw = window.localStorage.getItem( this.storageKey ) || "";
      if ( raw.charAt( 0 ) === "{" ) saved = JSON.parse( raw );
      else if ( raw !== "" ) saved = this.builtIn.find( function ( theme ) { return theme.id === raw; } ) || null;
    } catch ( error ) {
      // Storage blocked (private window, previews) or unreadable: stay light.
    }
    if ( !this.valid( saved ) ) saved = this.builtIn[ 0 ];
    this.list = this.builtIn.slice();
    this.current = saved.id;
    this.apply( saved );
  },

  // Enough of a theme to paint, so a broken stored value never breaks the page.
  valid( theme ) {
    const hex = /^#[0-9a-f]{6}$/i;
    return Boolean( theme && typeof theme === "object" && ( theme.mode === "light" || theme.mode === "dark" )
      && hex.test( theme.accent || "" ) && hex.test( theme.second || "" ) );
  },

  // Keeps the theme in use for the next first paint. Plain Light is kept as
  // nothing at all, which is what a new browser starts with anyway.
  keep( theme ) {
    try {
      const plain = theme.id === "light" && JSON.stringify( this.colours( theme ) ) === JSON.stringify( this.colours( this.builtIn[ 0 ] ) );
      if ( plain ) window.localStorage.removeItem( this.storageKey );
      else window.localStorage.setItem( this.storageKey , JSON.stringify( theme ) );
    } catch ( error ) {
      // Not remembered for next time, but still applied now.
    }
  },

  apply( theme ) {
    const root = document.documentElement;
    if ( theme.mode === "dark" ) root.setAttribute( "data-bs-theme" , "dark" );
    else root.removeAttribute( "data-bs-theme" );
    const colours = this.colours( theme );
    Object.keys( this.vars ).forEach( ( field ) => root.style.setProperty( this.vars[ field ] , colours[ field ] ) );
  },

  changed() {
    this.onChange.forEach( ( listener ) => listener() );
  },

  // The account's themes, from /api/me (or a save's reply). A person who never
  // picked one on their account keeps what this browser had, if it is on offer.
  load( me ) {
    const kept = this.current;
    this.custom = Boolean( me.themes_custom );
    this.list = Array.isArray( me.themes ) && me.themes.length > 0
      ? me.themes.map( ( theme ) => this.copy( theme ) )
      : this.builtIn.map( ( theme ) => this.named( theme ) );
    this.current = this.find( me.theme_id || kept ).id;
    this.show();
  },

  // Paints the theme in use and keeps it for next time.
  show() {
    const theme = this.find( this.current );
    this.apply( theme );
    this.keep( theme );
    this.changed();
  },

  // Picking is undoable, and quick picks merge into one step.
  pick( id ) {
    const previous = this.current;
    if ( previous === id ) return Promise.resolve();
    const choose = async ( chosen ) => {
      this.current = this.find( chosen ).id;
      this.show();
      await Api.setTheme( this.current );
    };
    return Undo.run( {
      label: I18n.get( "undo.theme" ),
      merge: "theme",
      screen: null,
      do: () => choose( id ),
      undo: () => choose( previous ),
    } );
  },

  // Saves someone's whole list (null: back to the defaults) and which one they
  // use, and takes the server's answer as the new state.
  async store( list , id ) {
    const reply = await Api.setThemes( list , id );
    this.load( reply );
  },

  // Every colour the page needs, from a theme's few, before its overrides.
  // Fills keep the colour as chosen. Anything read as text is pushed until it
  // is readable, on the nested card, the most tinted place it can land: WSU's
  // gold is gold on a progress bar and darker in a heading.
  derived( theme ) {
    const mode = this.modes[ theme.mode ] || this.modes.light;
    const background = theme.background || mode.background;
    const surface = theme.surface || mode.surface;
    const second = theme.second;
    const card = this.mix( second , surface , this.tints.surface );
    const nested = this.mix( second , surface , this.tints.nested );
    const chrome = this.mix( second , surface , this.tints.chrome );
    return {
      text: mode.text,
      accent: theme.accent,
      accentFg: this.readableOn( theme.accent ),
      second: second,
      secondFg: this.readableOn( second ),
      secondText: this.asText( second , nested ),
      link: this.asText( theme.accent , nested ),
      navLink: this.asText( theme.accent , chrome ),
      background: this.mix( second , background , this.tints.page ),
      surface: card,
      nested: nested,
      chrome: chrome,
      info: this.mix( second , card , this.tints.info ),
      infoBorder: this.mix( second , card , this.tints.infoBorder ),
      // From the card, not the page: most borders sit on a card, and a card can be
      // a long way from its page (WSU dark's green on black).
      border: this.mix( mode.text , card , 20 ),
    };
  },

  // What the page uses: the worked-out colours, with the theme's overrides on top.
  colours( theme ) {
    const colours = this.derived( theme );
    Object.keys( theme.overrides || {} ).forEach( ( field ) => {
      if ( field in colours ) colours[ field ] = theme.overrides[ field ];
    } );
    return colours;
  },

  // The pairs that are too hard to read in this theme, worst first:
  // [ { name , front , back , ratio } ]. Only an override can cause one; the
  // built-in themes are held to none by scripts/check_themes.js.
  check( theme ) {
    const colours = this.colours( theme );
    return Object.keys( this.pairs ).map( ( name ) => {
      const [ front , back ] = this.pairs[ name ];
      return { name: name , front: front , back: back , ratio: this.contrast( colours[ front ] , colours[ back ] ) };
    } ).filter( ( pair ) => pair.ratio < this.minContrast ).sort( ( a , b ) => a.ratio - b.ratio );
  },

  // percent of over, the rest under.
  mix( over , under , percent ) {
    const channel = function ( color , offset ) { return parseInt( color.slice( offset , offset + 2 ) , 16 ); };
    return "#" + [ 1 , 3 , 5 ].map( function ( offset ) {
      const mixed = channel( over , offset ) * percent / 100 + channel( under , offset ) * ( 100 - percent ) / 100;
      return Math.round( mixed ).toString( 16 ).padStart( 2 , "0" );
    } ).join( "" );
  },

  // Black or white, for a label on this colour.
  readableOn( color ) {
    return this.contrast( color , "#ffffff" ) >= this.contrast( color , "#0b0d10" ) ? "#ffffff" : "#0b0d10";
  },

  // This colour, moved toward black or white until text in it reads on ground.
  asText( color , ground ) {
    const away = this.luminance( ground ) > 0.4 ? "#000000" : "#ffffff";
    for ( let step = 0 ; step <= 100 ; step += 2 ) {
      const tried = this.mix( away , color , step );
      if ( this.contrast( tried , ground ) >= this.minContrast ) return tried;
    }
    return away;
  },

  // Relative luminance (WCAG) of #rrggbb.
  luminance( hex ) {
    const channel = function ( offset ) {
      const value = parseInt( hex.slice( offset , offset + 2 ) , 16 ) / 255;
      return value <= 0.03928 ? value / 12.92 : Math.pow( ( value + 0.055 ) / 1.055 , 2.4 );
    };
    return 0.2126 * channel( 1 ) + 0.7152 * channel( 3 ) + 0.0722 * channel( 5 );
  },

  contrast( first , second ) {
    const a = this.luminance( first ) , b = this.luminance( second );
    return ( Math.max( a , b ) + 0.05 ) / ( Math.min( a , b ) + 0.05 );
  },
};

Theme.restore();
