// The library, in this browser: every title, the subject's own state for
// each, who else in the family has watched or loved what, and IMDb scores.
//
// One read (/api/library) loads it; after that, ?since=<rev> brings only what
// changed -- when the tab comes back into focus, and every minute while it is
// visible. Changes made here are applied at once and sent to the server; if
// the server refuses, they are put back and the reason is shown.
//
// Every change goes through Undo, so Ctrl+Z (or the toast's Undo) puts it
// back on the server too, and says so if someone changed it in the meantime.
//
// Rows -- { t: title , s: state , social , score } -- are kept as stable
// objects per title id, so a search's folded text is computed once per row
// and a re-render after a small change touches only what changed.
const Library = {
  rev: null,
  rows: new Map(),
  types: [],
  people: [],
  subject: null,
  loaded: false,
  listeners: [],
  pollMs: 60000,

  EMPTY_STATE: { status: null , rating: null , heart: false , note: "" , watched_at: null },

  on( listener ) {
    this.listeners.push( listener );
  },

  emit( change ) {
    this.listeners.forEach( ( listener ) => {
      try { listener( change ); } catch ( error ) { console.error( error ); }
    } );
  },

  async load() {
    const payload = await Api.library( null );
    this.apply( payload );
    this.loaded = true;
    this.emit( { kind: "load" } );
  },

  async refresh() {
    if ( !this.loaded ) return;
    try {
      const payload = await Api.library( this.rev );
      if ( payload.full || payload.rev !== this.rev ) {
        this.apply( payload );
        this.emit( { kind: payload.full ? "load" : "refresh" } );
      }
    } catch ( error ) {
      // Offline or the server restarting: the next poll tries again.
    }
  },

  startPolling() {
    document.addEventListener( "visibilitychange" , () => {
      if ( document.visibilityState === "visible" ) this.refresh();
    } );
    window.addEventListener( "focus" , () => this.refresh() );
    window.setInterval( () => {
      if ( document.visibilityState === "visible" ) this.refresh();
    } , this.pollMs );
  },

  apply( payload ) {
    if ( payload.genre_rules ) Genres.use( payload.genre_rules );
    if ( payload.full ) {
      this.rows = new Map();
    }
    this.rev = payload.rev;
    this.subject = payload.subject;
    this.types = payload.types || this.types;
    this.people = payload.people || this.people;
    const scores = payload.scores || {};
    ( payload.titles || [] ).forEach( ( title ) => {
      const row = this.rows.get( title.id );
      if ( title.deleted_at && title.merged_into ) {
        this.rows.delete( title.id );
        return;
      }
      if ( row ) row.t = title;
      else this.rows.set( title.id , { t: title , s: this.EMPTY_STATE , social: null , score: null } );
    } );
    Object.keys( payload.states || {} ).forEach( ( id ) => {
      const row = this.rows.get( id );
      if ( row ) row.s = payload.states[ id ];
    } );
    const social = payload.social || {};
    this.rows.forEach( ( row , id ) => {
      row.social = social[ id ] || null;
      if ( row.t.imdb_id && scores[ row.t.imdb_id ] ) row.score = scores[ row.t.imdb_id ];
      else if ( payload.full || ( payload.titles || [] ).some( ( title ) => title.id === id ) ) row.score = row.t.imdb_id ? scores[ row.t.imdb_id ] || null : null;
    } );
  },

  get( id ) {
    return this.rows.get( id ) || null;
  },

  // Which list a live title belongs to for me: Watched, Not for me
  // (skipped, status "dropped"), or Everything -- what is still ahead.
  listOf( row ) {
    const status = row.s && row.s.status;
    if ( status === "watched" ) return "watched";
    if ( status === "dropped" ) return "skipped";
    return "all";
  },

  // Rows in a scope ("all" or a type id) and list. Each live title is in
  // exactly one of all / watched / skipped.
  pool( scope , list ) {
    const out = [];
    this.rows.forEach( ( row ) => {
      const deleted = Boolean( row.t.deleted_at );
      if ( list === "trash" ) {
        if ( deleted ) out.push( row );
        return;
      }
      if ( deleted ) return;
      if ( scope !== "all" && row.t.type !== scope ) return;
      if ( this.listOf( row ) !== list ) return;
      out.push( row );
    } );
    return out;
  },

  // How many live titles a scope has on each list; total is all three.
  counts( scope ) {
    let all = 0;
    let queue = 0;
    let watched = 0;
    let skipped = 0;
    this.rows.forEach( ( row ) => {
      if ( row.t.deleted_at ) return;
      if ( scope !== "all" && row.t.type !== scope ) return;
      const list = this.listOf( row );
      if ( list === "watched" ) watched += 1;
      else if ( list === "skipped" ) skipped += 1;
      else all += 1;
      const status = row.s && row.s.status;
      if ( status === "queue" || status === "watching" ) queue += 1;
    } );
    return { all: all , queue: queue , watched: watched , skipped: skipped , total: all + watched + skipped };
  },

  trashCount() {
    let count = 0;
    this.rows.forEach( ( row ) => { if ( row.t.deleted_at ) count += 1; } );
    return count;
  },

  // -- my state ---------------------------------------------------------

  // Set fields of the subject's state for one title, undoably. The undo
  // sends the previous values and expects the new ones, so it is refused
  // (409) rather than overwriting a change made since on another device.
  async setState( id , changes , label ) {
    const row = this.get( id );
    if ( !row ) return;
    const before = Object.assign( {} , row.s );
    await Undo.run( {
      label: label || I18n.get( "undo.state" ),
      merge: null,
      do: () => this.writeState( id , changes , null ),
      // Expects what this browser last heard the server say, so a change
      // made since on another device is refused rather than overwritten.
      undo: () => this.writeState( id , this.pick( before , changes ) , this.pick( this.get( id ).s , changes ) ),
    } );
  },

  pick( source , fields ) {
    const out = {};
    Object.keys( fields ).forEach( ( name ) => { out[ name ] = source[ name ] == null ? null : source[ name ]; } );
    // A watched_at the server filled in comes back on undo too.
    if ( "status" in fields && !( "watched_at" in fields ) ) out.watched_at = source.watched_at == null ? null : source.watched_at;
    return out;
  },

  async writeState( id , changes , expect ) {
    const row = this.get( id );
    if ( !row ) return;
    const previous = row.s;
    row.s = Object.assign( {} , row.s , changes );
    this.touchSocial( row , previous , row.s );
    this.emit( { kind: "state" , id: id } );
    try {
      const result = await Api.setState( id , changes , expect );
      row.s = result.state;
      this.touchSocial( row , previous , row.s );
      this.emit( { kind: "state" , id: id } );
    } catch ( error ) {
      row.s = previous;
      this.touchSocial( row , row.s , previous );
      this.emit( { kind: "state" , id: id } );
      throw error;
    }
  },

  // Keep the family counts honest for the subject's own change without a
  // round trip; the next refresh brings the server's word on it.
  touchSocial( row , before , after ) {
    if ( !row.social ) row.social = { watched: [] , watching: [] , queued: [] , loved: [] , ratings: {} };
    const who = this.subject;
    const set = ( list , on ) => {
      const at = list.indexOf( who );
      if ( on && at < 0 ) list.push( who );
      if ( !on && at >= 0 ) list.splice( at , 1 );
    };
    set( row.social.watched , after.status === "watched" );
    set( row.social.watching , after.status === "watching" );
    set( row.social.queued , after.status === "queue" );
    set( row.social.loved , Boolean( after.heart ) );
    if ( after.rating ) row.social.ratings[ String( who ) ] = after.rating;
    else delete row.social.ratings[ String( who ) ];
  },

  // The same change to many titles, as one undo step.
  async setStates( ids , changes , label ) {
    const all = {};
    ids.forEach( ( id ) => { all[ id ] = changes; } );
    let previous = {};
    await Undo.run( {
      label: label,
      toast: true,
      do: async () => {
        const result = await Api.setStates( all );
        previous = result.previous || {};
        await this.refresh();
      },
      undo: async () => {
        await Api.setStates( previous );
        await this.refresh();
      },
    } );
  },

  // -- the shared title ---------------------------------------------------

  async updateTitle( id , changes ) {
    const row = this.get( id );
    if ( !row ) return null;
    const result = await Api.updateTitle( id , changes );
    row.t = Object.assign( {} , result.title , { poster: row.t.poster_url === result.title.poster_url ? row.t.poster : "" } );
    this.emit( { kind: "title" , id: id } );
    const previous = result.previous || {};
    if ( Object.keys( previous ).length ) {
      Undo.record( {
        label: I18n.get( "undo.title_edit" ),
        undo: async () => { await Api.updateTitle( id , previous , this.pick( result.title , previous ) ); await this.refresh(); },
        redo: async () => { await Api.updateTitle( id , changes , previous ); await this.refresh(); },
      } );
    }
    await this.refresh();
    return result.title;
  },

  async deleteTitle( id ) {
    const row = this.get( id );
    if ( !row ) return;
    await Undo.run( {
      label: I18n.fill( "undo.title_deleted" , { title: row.t.title } ),
      toast: true,
      do: async () => { await Api.deleteTitle( id ); await this.refresh(); },
      undo: async () => { await Api.restoreTitle( id ); await this.refresh(); },
    } );
  },

  async restoreTitle( id ) {
    const row = this.get( id );
    if ( !row ) return;
    await Undo.run( {
      label: I18n.fill( "undo.title_restored" , { title: row.t.title } ),
      toast: true,
      do: async () => { await Api.restoreTitle( id ); await this.refresh(); },
      undo: async () => { await Api.deleteTitle( id ); await this.refresh(); },
    } );
  },
};
