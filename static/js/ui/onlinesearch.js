// The last step of a search: when neither the library nor Discover has what
// was typed, the same text goes to the online lookup (TMDB, IMDb, TVmaze,
// Wikipedia...) on its own, and what comes back shows as cards with the same
// Add and Watched corners as a Discover film. Discover is built from
// Wikipedia's film lists, so a film out this month is only ever found here.
//
// Used by the library's search box (SearchExtras) and Discover's.
//
// Whether it runs does not depend on the filters showing: what decides it is
// whether what was typed is already a title here (needed() below). A pasted
// IMDb link is looked up by its id, so it lands here when it is new.
const OnlineSearch = {
  // The lookup's answer per search text: { rows } once back, null while asked.
  found: new Map(),
  // A search box asks on every pause in typing; the lookup counts against a
  // per-person allowance, so it waits for a longer pause than Discover does.
  WAIT_MS: 700,
  MIN_CHARS: 3,
  timers: new Map(),

  wanted( text ) {
    return typeof text === "string" && text.trim().length >= this.MIN_CHARS;
  },

  // Every live library title, whatever list it is in or filter is showing.
  libraryRows() {
    return [ "all" , "watched" , "skipped" ].reduce( ( rows , list ) => rows.concat( Library.pool( "all" , list ) ) , [] );
  },

  // Go online unless the text is already a title here: one in the library
  // with those words in its name (or that IMDb id), or one in Discover's
  // catalogue (catalogueHit, from the server, filters aside). Words that only
  // match a cast member or a director do not count, and neither do the
  // filters. A search with operators (genre:, -word) is never a title.
  needed( text , catalogueHit ) {
    if ( !this.wanted( text ) || catalogueHit ) return false;
    const imdb = Search.imdbId( text );
    if ( imdb ) return !this.libraryRows().some( ( row ) => String( row.t.imdb_id || "" ).toLowerCase() === imdb );
    const parsed = Search.parse( text );
    if ( parsed.not.length || parsed.fields.length ) return false;
    const want = Search.fold( text );
    return Boolean( want ) && !this.libraryRows().some( ( row ) => Search.fold( row.t.title ).indexOf( want ) >= 0 );
  },

  // A lookup that failed (the server restarting, a provider timing out, the
  // allowance spent) is not an answer: the same text is asked again once
  // this long has passed, instead of showing nothing until a reload.
  RETRY_MS: 15000,

  // Ask once per text, after a pause; then() runs when the answer is in.
  ask( text , owner , then ) {
    if ( !this.wanted( text ) ) return;
    const known = this.found.get( text );
    if ( known === null || ( known && !( known.failed && Date.now() - known.at > this.RETRY_MS ) ) ) return;
    window.clearTimeout( this.timers.get( owner ) );
    this.timers.set( owner , window.setTimeout( () => this.fetch( text ).then( then ) , this.WAIT_MS ) );
  },

  async fetch( text ) {
    if ( this.found.get( text ) === null ) return;
    this.found.set( text , null );
    let result = null;
    try {
      const answer = await Api.post( "/api/resolve" , { lines: [ text ] , kind: "any" } );
      result = ( answer.results || [] )[ 0 ] || null;
    } catch ( error ) {
      this.found.set( text , { rows: [] , failed: true , at: Date.now() } );
      return;
    }
    this.found.set( text , { rows: result ? this.rows( result ) : [] } );
  },

  rows( result ) {
    const same = ( result.dupes || [] ).find( ( dupe ) => dupe.score >= 1 );
    const seen = new Set();
    // Titles the library already has (by IMDb id) are left out: the section
    // is for what is new.
    const owned = new Set( this.libraryRows().map( ( row ) => String( row.t.imdb_id || "" ).toLowerCase() ).filter( Boolean ) );
    return ( result.candidates || [] ).map( ( candidate , at ) => {
      const f = candidate.fields || {};
      if ( f.imdb_id && owned.has( String( f.imdb_id ).toLowerCase() ) ) return null;
      const key = "online:" + ( f.imdb_id || ( candidate.source || "" ) + ":" + ( f.source_id || f.title + ":" + ( f.year || "" ) ) );
      if ( seen.has( key ) ) return null;
      seen.add( key );
      return this.row( key , f , candidate , at === 0 && same ? same.id : null );
    } ).filter( Boolean );
  },

  row( key , f , candidate , titleId ) {
    const inLibrary = titleId ? Library.get( titleId ) : null;
    return {
      t: {
        id: key,
        title: f.title,
        year: f.year || null,
        type: Library.types.some( ( type ) => type.id === f.type ) ? f.type : "movie",
        genres: f.genres || [],
        creator: f.creator || "",
        cast: f.cast || [],
        certification: f.certification || "",
        runtime: f.runtime || null,
        ext_rating: null,
        imdb_id: f.imdb_id || "",
        wiki_url: f.wiki_url || "",
        apple_tv: "",
        poster: candidate.poster || "",
        overview: f.overview || "",
        rev: 0,
      },
      s: inLibrary ? inLibrary.s : Library.EMPTY_STATE,
      social: null,
      score: candidate.imdbScore || null,
      inLibrary: Boolean( inLibrary ),
      titleId: titleId,
      discover: true,
      online: true,
      fields: f,
      link: candidate.url || f.wiki_url || ( f.imdb_id ? "https://www.imdb.com/title/" + f.imdb_id + "/" : "" ),
    };
  },

  // The section: "Looking online…" while asked, the cards once back, nothing
  // when the lookup found nothing either.
  section( text , card , redraw ) {
    const found = this.found.get( text );
    if ( found === undefined ) return null;
    if ( found === null ) return Dom.el( "p" , { class: "search-extra-note text-body-secondary small" , text: I18n.get( "library.search_online_looking" ) } );
    if ( found.failed ) return Dom.el( "p" , { class: "search-extra-note text-body-secondary small" , text: I18n.get( "library.search_online_failed" ) } );
    const rows = found.rows.filter( ( row ) => !row.hidden );
    if ( !rows.length ) return null;
    const grid = Dom.el( "div" , { class: "media-grid layout-" + card.layout + " size-" + card.size } );
    rows.forEach( ( row ) => grid.appendChild( Card.build( row , card , { addCorner: true } ) ) );
    const section = Dom.el( "section" , { class: "search-extra search-extra-online" , children: [
      Dom.el( "div" , { class: "search-extra-head" , children: [
        Dom.el( "h2" , { class: "search-extra-title" , text: I18n.get( "library.search_online" ) } ),
        Dom.el( "span" , { class: "badge rounded-pill text-bg-light" , text: String( rows.length ) } ),
        Dom.el( "span" , { class: "search-extra-note text-body-secondary small" , text: I18n.get( "library.search_online_note" ) } ),
      ] } ),
      grid,
    ] } );
    section.addEventListener( "click" , ( event ) => {
      const article = event.target.closest( ".media-card" );
      if ( !article ) return;
      const row = rows.find( ( r ) => r.t.id === article.getAttribute( "data-id" ) );
      if ( !row || Card.clicked( event , article ) ) return;
      const control = event.target.closest( "[data-action]" );
      if ( !control ) return;
      event.stopPropagation();
      Dom.steady( control , () => this.act( control.getAttribute( "data-action" ) , row , article ).then( redraw ) );
    } );
    return section;
  },

  async act( action , row , article ) {
    try {
      if ( action === "expand" ) { Card.toggle( article ); return; }
      if ( action === "skip" ) { row.hidden = true; return; }
      if ( action === "edit" ) {
        if ( row.inLibrary ) Editor.open( Library.get( row.titleId ) );
        else if ( row.link ) window.open( row.link , "_blank" , "noopener" );
        return;
      }
      if ( action !== "add" && action !== "seen" && action !== "watched" ) return;
      if ( row.inLibrary ) {
        if ( action === "add" ) { Editor.open( Library.get( row.titleId ) ); return; }
        const current = Library.get( row.titleId ).s.status;
        const next = current === "watched" ? null : "watched";
        await Library.setState( row.titleId , { status: next } , I18n.fill( next ? "undo.watched" : "undo.unwatched" , { title: row.t.title } ) );
        row.s = Library.get( row.titleId ).s;
        return;
      }
      const status = action === "add" ? null : "watched";
      const fields = Object.assign( {} , row.fields , { type: row.t.type } );
      let created = null;
      await Undo.run( {
        label: I18n.fill( "undo.added_one" , { title: row.t.title } ),
        toast: true,
        do: async () => {
          created = await Api.createTitle( fields , { status: status } , true );
          row.titleId = created.title.id;
          await Library.refresh();
          row.inLibrary = true;
          row.s = ( Library.get( row.titleId ) || {} ).s || Library.EMPTY_STATE;
        },
        undo: async () => {
          if ( !created ) return;
          await Api.deleteTitle( created.title.id );
          row.titleId = null;
          row.inLibrary = false;
          row.s = Library.EMPTY_STATE;
          await Library.refresh();
        },
      } );
    } catch ( error ) {
      Dom.toast( I18n.get( "errors." + error.message ) || error.message , "error" );
    }
  },
};
