// What follows a person from phone to laptop: how cards look on each
// screen, the last query on each scope of the library, and their saved
// views. Kept on the account (/api/prefs, /api/views), never only in this
// browser.
//
// Writes are debounced -- a few clicks in the customizer are one save.
const Prefs = {
  data: { cards: {} , last_query: {} , default_view: {} , ui: {} },
  views: [],
  pending: {},
  timer: null,
  delayMs: 800,

  async load() {
    try {
      const [ prefs , views ] = await Promise.all( [ Api.prefs() , Api.views() ] );
      this.data = prefs;
      this.views = views;
    } catch ( error ) {
      // Prefs are a convenience; the library still works on the defaults.
    }
  },

  card( screen ) {
    const saved = this.data.cards[ screen ];
    const base = JSON.parse( JSON.stringify( screen === "discover" ? Vocab.DEFAULT_DISCOVER_CARD : Vocab.DEFAULT_CARD ) );
    if ( !saved ) return base;
    return {
      layout: Vocab.LAYOUTS.indexOf( saved.layout ) >= 0 ? saved.layout : base.layout,
      size: Vocab.SIZES.indexOf( saved.size ) >= 0 ? saved.size : base.size,
      fields: ( saved.fields || base.fields ).filter( ( id ) => Vocab.FIELDS[ id ] ),
      buttons: ( saved.buttons || base.buttons ).filter( ( id ) => Vocab.SCREEN_BUTTONS[ screen ].indexOf( id ) >= 0 ),
    };
  },

  setCard( screen , card ) {
    this.data.cards[ screen ] = card;
    this.queue( "cards" , screen , card );
  },

  lastQuery( scope ) {
    return this.data.last_query[ scope ] || "";
  },

  setLastQuery( scope , hash ) {
    if ( this.data.last_query[ scope ] === hash ) return;
    this.data.last_query[ scope ] = hash;
    this.queue( "last_query" , scope , hash );
  },

  ui( name , fallback ) {
    return name in this.data.ui ? this.data.ui[ name ] : fallback;
  },

  setUi( name , value ) {
    this.data.ui[ name ] = value;
    this.queue( "ui" , name , value );
  },

  queue( section , name , value ) {
    this.pending[ section ] = this.pending[ section ] || {};
    this.pending[ section ][ name ] = value;
    window.clearTimeout( this.timer );
    this.timer = window.setTimeout( () => this.flush() , this.delayMs );
  },

  async flush() {
    const changes = this.pending;
    this.pending = {};
    if ( !Object.keys( changes ).length ) return;
    try {
      await Api.savePrefs( changes );
    } catch ( error ) {
      // Not saved this time; the next change sends its own copy.
    }
  },

  // -- saved views --------------------------------------------------------

  async reloadViews() {
    this.views = await Api.views();
  },
};

window.addEventListener( "pagehide" , () => Prefs.flush() );
