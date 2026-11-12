// Discover: films from Wikipedia's lists -- box-office number ones, award
// winners, every American film of a year, topics like Pre-Code Hollywood --
// that are not on your list yet. Filtered and sorted on the server (it is
// 27,000 films), with the library's toolbar: the same Filters sheet, the
// same Sort menu, the same chips, the same Clear all and the same cards.
// The hash keeps its own flat words (below); toQuery() turns them into a
// library-shaped query for the shared pieces, and apply() turns one back. Add puts a film in the family library;
// Seen it marks it watched; Skip hides it from you (only you) and can be
// taken back from "Skipped". What you have watched, and library titles you
// skipped, are hidden too until you ask for them.
//
//   #discover?q=&from=1930&to=1949&genre=Comedy,Romance&genremode=all
//            &rating=PG&norating=R&imdbfrom=7&votesfrom=10000&topic=&only=awarded
//            &watched=all&skipped=all&sort=-imdb_weighted,-year
const DiscoverScreen = {
  // Thrown when the person says no to adding a possible duplicate: stops the
  // add without an error toast or an Undo step.
  Cancelled: class extends Error {},
  card: null,
  params: {},
  films: [],
  total: 0,
  facets: { genres: [] , ratings: [] },
  meta: null,
  result: { rows: [] },
  PAGE: 60,
  token: 0,

  DEFAULTS: { sort: "-notable" , watched: "hide" , skipped: "hide" , genremode: "any" },
  FIELDS: [ "q" , "from" , "to" , "genre" , "genremode" , "rating" , "norating" , "imdbfrom" , "imdbto" , "votesfrom" , "votesto" , "topic" , "only" , "actor" , "library" , "watched" , "skipped" , "sort" ],

  // The sort keys the catalogue has data for (app/discover/catalogue.py).
  SORT_KEYS: [ "notable" , "imdb_weighted" , "imdb" , "votes" , "year" , "title" , "cert" , "random" ],
  // What the old sort select sent, still in saved links.
  LEGACY_SORTS: { notable: "-notable" , imdb: "-imdb_weighted" , year: "-year" , "year-asc": "year" , title: "title" },
  // The Filters sheet's sections, in order.
  SHEET: [ "genre" , "year" , "imdb" , "votes" , "cert" , "nocert" , "topic" , "only" , "hidelibrary" , "showwatched" , "showskipped" ],
  sheetOpen: false,

  async init() {
    Dom.show( Dom.get( "discover-panel" ) , true );
    this.card = Prefs.card( "discover" );
    this.grid = Dom.get( "discover-grid" );
    this.wire();
    window.addEventListener( "hashchange" , () => { if ( Nav.screen() === "discover" ) this.route(); } );
    if ( Nav.screen() === "discover" ) this.route();
  },

  // -- the query in the hash ---------------------------------------------

  route() {
    const raw = window.location.hash.replace( /^#/ , "" );
    const cut = raw.indexOf( "?" );
    // Only a remembered query brings anything back; a plain "#discover"
    // (everything cleared) would land here again and again.
    const remembered = Prefs.lastQuery( "discover" ) || "";
    if ( cut < 0 && remembered.indexOf( "?" ) >= 0 ) {
      window.history.replaceState( null , "" , remembered );
      this.route();
      return;
    }
    const params = new URLSearchParams( cut < 0 ? "" : raw.slice( cut + 1 ) );
    this.params = {};
    this.FIELDS.forEach( ( name ) => { if ( params.get( name ) ) this.params[ name ] = params.get( name ); } );
    if ( this.LEGACY_SORTS[ this.params.sort ] ) this.params.sort = this.LEGACY_SORTS[ this.params.sort ];
    if ( this.params.sort === this.DEFAULTS.sort ) delete this.params.sort;
    this.load( false );
  },

  set( changes ) {
    const next = Object.assign( {} , this.params , changes );
    Object.keys( next ).forEach( ( name ) => { if ( next[ name ] === "" || next[ name ] == null || next[ name ] === this.DEFAULTS[ name ] ) delete next[ name ]; } );
    const query = new URLSearchParams( next ).toString().replace( /%2C/g , "," );
    const hash = "#discover" + ( query ? "?" + query : "" );
    window.history.replaceState( null , "" , hash );
    Prefs.setLastQuery( "discover" , hash );
    this.params = next;
    this.load( false );
  },

  value( name ) {
    return this.params[ name ] || this.DEFAULTS[ name ] || "";
  },

  list( name ) {
    return ( this.params[ name ] || "" ).split( "," ).filter( Boolean );
  },

  // Where a value sits in a list, whatever case it came in: a link saved
  // before the facets had their capitals says genre=drama.
  find( values , value ) {
    const wanted = String( value ).toLowerCase();
    return values.findIndex( ( entry ) => entry.toLowerCase() === wanted );
  },

  toggle( name , value ) {
    const values = this.list( name );
    const at = this.find( values , value );
    if ( at >= 0 ) values.splice( at , 1 );
    else values.push( value );
    this.set( { [ name ]: values.join( "," ) } );
  },

  // -- loading ----------------------------------------------------------------

  async load( more ) {
    const token = ++this.token;
    if ( !this.meta ) {
      try { this.meta = await Api.request( "/api/discover/meta" ); } catch ( error ) { this.meta = { topics: [] , coverage: { films: 0 } }; }
    }
    const query = new URLSearchParams( Object.assign( {} , this.params , { limit: String( this.PAGE ) , offset: String( more ? this.films.length : 0 ) } ) );
    let data;
    try {
      data = await Api.request( Api.forSubject( "/api/discover?" + query.toString() ) );
    } catch ( error ) {
      Dom.toast( error.message , "error" );
      return;
    }
    if ( token !== this.token ) return;
    this.films = more ? this.films.concat( data.films ) : data.films;
    this.total = data.total;
    this.facets = data.facets;
    this.skippedCount = ( data.verdicts || {} ).skip || 0;
    this.watchedCount = ( data.verdicts || {} ).watched || 0;
    this.libraryCount = ( data.verdicts || {} ).library || 0;
    this.render();
    this.loadFacts( data.films );
  },

  // Posters and IMDb ids come a page at a time from Wikipedia and Wikidata
  // (cached on the server after the first time).
  async loadFacts( films ) {
    const articles = films.map( ( film ) => film.article ).filter( Boolean );
    for ( let i = 0; i < articles.length; i += 30 ) {
      const query = articles.slice( i , i + 30 ).map( ( a ) => "a=" + encodeURIComponent( a ) ).join( "&" );
      let facts;
      try { facts = await Api.request( "/api/discover/facts?" + query ); } catch ( error ) { return; }
      let changed = false;
      this.films.forEach( ( film ) => {
        const fact = facts[ film.article ];
        if ( !fact ) return;
        film.poster = fact.poster || film.poster;
        film.thumb = fact.thumb || film.thumb;
        film.imdb = film.imdb || fact.imdb;
        if ( !film.imdbScore && fact.imdbScore ) film.imdbScore = fact.imdbScore;
        if ( !film.rating && fact.rating ) film.rating = fact.rating;
        changed = true;
      } );
      if ( changed ) this.renderGrid();
    }
  },

  // -- drawing ------------------------------------------------------------------

  // A catalogue film as a card row. In the library already? Then it is that
  // title, with your state on it.
  row( film ) {
    const inLibrary = film.title_id ? Library.get( film.title_id ) : null;
    const t = {
      id: film.key,
      title: film.title,
      year: film.year,
      type: "movie",
      genres: film.genres || [],
      creator: film.director || "",
      cast: film.cast || [],
      certification: film.rating || "",
      imdb_id: film.imdb || "",
      wiki_url: film.url || "",
      // Apple TV ids are looked up for library titles only (appletv_job).
      apple_tv: inLibrary ? inLibrary.t.apple_tv || "" : "",
      poster: film.poster || "",
      overview: film.notes || "",
      rev: 0,
    };
    return {
      t: t,
      s: inLibrary ? inLibrary.s : Library.EMPTY_STATE,
      social: inLibrary ? inLibrary.social : null,
      score: film.imdbScore || null,
      inLibrary: Boolean( inLibrary ),
      verdict: film.verdict,
      discover: true,
      film: film,
    };
  },

  render() {
    Dom.text( Dom.get( "discover-count" ) , I18n.fill( "discover.count" , { n: this.total.toLocaleString() , all: ( this.meta.coverage.films || 0 ).toLocaleString() } ) );
    const query = this.toQuery();
    this.renderChips( query );
    const badge = Dom.get( "discover-filters-badge" );
    const active = Object.keys( query.filters ).length;
    Dom.text( badge , String( active ) );
    Dom.show( badge , active > 0 );
    SortControl.render( Dom.get( "discover-sort-button" ) , Dom.get( "discover-sort-menu" ) , query , ( next ) => this.apply( next ) , { keys: this.SORT_KEYS , group: false } );
    // Only when it says something else, so typing is never overwritten.
    const search = Dom.get( "discover-search" );
    if ( search.value.trim() !== ( this.params.q || "" ) ) search.value = this.params.q || "";
    Dom.all( "[data-discover-layout]" ).forEach( ( button ) => {
      const on = button.getAttribute( "data-discover-layout" ) === this.card.layout;
      button.classList.toggle( "active" , on );
      button.setAttribute( "aria-pressed" , String( on ) );
    } );
    if ( this.sheetOpen ) this.renderSheet();
    this.renderGrid();
  },

  // -- the hash as a library-shaped query, and back ---------------------------

  number( name ) {
    const value = this.params[ name ];
    return value == null || value === "" || isNaN( Number( value ) ) ? null : Number( value );
  },

  // Genres in the facet's spelling: an old link says genre=drama.
  genreValues() {
    const known = ( this.facets.genres || [] ).map( ( g ) => g.id );
    return this.list( "genre" ).map( ( g ) => { const at = this.find( known , g ); return at >= 0 ? known[ at ] : g; } );
  },

  toQuery() {
    const filters = {};
    const range = ( id , from , to ) => { const value = { from: this.number( from ) , to: this.number( to ) }; if ( value.from != null || value.to != null ) filters[ id ] = value; };
    if ( this.params.genre ) filters.genre = { mode: this.value( "genremode" ) , values: this.genreValues() };
    range( "year" , "from" , "to" );
    range( "imdb" , "imdbfrom" , "imdbto" );
    range( "votes" , "votesfrom" , "votesto" );
    if ( this.params.rating ) filters.cert = { mode: "any" , values: this.list( "rating" ) };
    if ( this.params.norating ) filters.nocert = { mode: "any" , values: this.list( "norating" ) };
    if ( this.params.topic ) filters.topic = { value: this.params.topic };
    if ( this.params.only ) filters.only = { value: this.params.only };
    if ( this.params.library === "hide" ) filters.hidelibrary = { value: true };
    if ( this.value( "watched" ) !== "hide" ) filters.showwatched = { value: true };
    if ( this.value( "skipped" ) !== "hide" ) filters.showskipped = { value: true };
    const sort = this.value( "sort" ).split( "," ).filter( Boolean ).map( ( part ) => ( { key: part.replace( /^-/ , "" ) , dir: part.charAt( 0 ) === "-" ? "desc" : "asc" } ) ).filter( ( step ) => this.SORT_KEYS.indexOf( step.key ) >= 0 );
    return { list: "all" , text: this.params.q || "" , filters: filters , sort: sort.length ? sort : [ { key: "notable" , dir: "desc" } ] , group: { by: "none" , dir: "asc" } };
  },

  // A query from the sheet, the sort menu or a chip, back into the hash.
  apply( next , sheetOnly ) {
    if ( sheetOnly ) {
      this.renderSheet();
      return;
    }
    const f = next.filters || {};
    const range = ( id , which ) => ( f[ id ] && f[ id ][ which ] != null ? String( f[ id ][ which ] ) : "" );
    const keep = ( name , on ) => ( on ? ( this.params[ name ] && this.params[ name ] !== "hide" ? this.params[ name ] : "all" ) : "" );
    this.set( {
      q: next.text || "",
      genre: f.genre ? f.genre.values.join( "," ) : "",
      genremode: f.genre ? f.genre.mode : "",
      from: range( "year" , "from" ),
      to: range( "year" , "to" ),
      imdbfrom: range( "imdb" , "from" ),
      imdbto: range( "imdb" , "to" ),
      votesfrom: range( "votes" , "from" ),
      votesto: range( "votes" , "to" ),
      rating: f.cert ? f.cert.values.join( "," ) : "",
      norating: f.nocert ? f.nocert.values.join( "," ) : "",
      topic: f.topic ? f.topic.value : "",
      only: f.only ? f.only.value : "",
      library: f.hidelibrary ? "hide" : "",
      watched: keep( "watched" , Boolean( f.showwatched ) ),
      skipped: keep( "skipped" , Boolean( f.showskipped ) ),
      sort: next.sort.map( ( step ) => ( step.dir === "desc" ? "-" : "" ) + step.key ).join( "," ),
    } );
  },

  // -- the chips and the sheet ----------------------------------------------

  chipText( id , value ) {
    switch ( id ) {
      case "cert": case "nocert": return value.values.map( ( r ) => this.ratingLabel( r ) ).join( " " + I18n.get( "filters.joiner_any" ) + " " );
      case "topic": return this.topicLabel( value.value );
      case "only": return I18n.get( "discover.only_" + value.value );
      default: return FilterBar.describe( id , value );
    }
  },

  renderChips( query ) {
    const box = Dom.get( "discover-chips" );
    Dom.clear( box );
    const without = ( id ) => { const next = Query.clone( query ); delete next.filters[ id ]; this.apply( next ); };
    if ( query.text ) box.appendChild( FilterBar.chip( I18n.fill( "filters.chip_search" , { text: query.text } ) , () => this.set( { q: "" } ) , "search" ) );
    this.SHEET.forEach( ( id ) => {
      const value = query.filters[ id ];
      if ( !value ) return;
      const text = id === "hidelibrary" ? I18n.get( "discover.library_hide" ) : id === "showwatched" || id === "showskipped"
        ? I18n.get( "discover." + ( id === "showwatched" ? "watched_" + this.value( "watched" ) : "skipped_" + this.value( "skipped" ) ) )
        : I18n.get( "filters.name_" + id ) + ": " + this.chipText( id , value );
      box.appendChild( FilterBar.chip( text , () => without( id ) ) );
    } );
    if ( this.params.actor ) box.appendChild( FilterBar.chip( I18n.get( "discover.actor" ) + ": " + this.params.actor , () => this.set( { actor: "" } ) ) );
    if ( Object.keys( this.params ).length ) {
      box.appendChild( Dom.el( "button" , { class: "btn btn-sm btn-link filter-clear" , text: I18n.get( "filters.clear_all" ) , attrs: { type: "button" } , on: { click: () => this.set( Object.fromEntries( this.FIELDS.map( ( name ) => [ name , "" ] ) ) ) } } ) );
    }
    Dom.show( box , box.childNodes.length > 0 );
  },

  // Filters the library does not have, for the shared sheet.
  sheetDefs() {
    return {
      year: { kind: "range" , step: 1 , noUnknown: true },
      imdb: { kind: "range" , step: 0.1 , noUnknown: true },
      votes: { kind: "range" , step: 100 , noUnknown: true },
      topic: { kind: "choice" , anyLabel: "discover.topic_any" , options: () => ( this.meta.topics || [] ).map( ( t ) => [ t.id , t.label ] ) },
      only: { kind: "choice" , anyLabel: "discover.only_any" , options: () => [ [ "boxoffice" , I18n.get( "discover.only_boxoffice" ) ] , [ "awarded" , I18n.get( "discover.only_awarded" ) ] ] },
      hidelibrary: { kind: "switch" , text: () => I18n.fill( "discover.hide_library" , { n: this.libraryCount.toLocaleString() } ) },
      showwatched: { kind: "switch" , text: () => I18n.fill( "discover.show_watched" , { n: this.watchedCount || 0 } ) },
      showskipped: { kind: "switch" , text: () => I18n.fill( "discover.show_skipped" , { n: this.skippedCount || 0 } ) },
    };
  },

  renderSheet() {
    const ratings = new Map( ( this.facets.ratings || [] ).map( ( r ) => [ r.id , r.count ] ) );
    this.ratingNames = Object.fromEntries( ( this.facets.ratings || [] ).map( ( r ) => [ r.id , r.label || this.ratingLabel( r.id ) ] ) );
    const counts = {
      genre: new Map( ( this.facets.genres || [] ).filter( ( g ) => g.id ).map( ( g ) => [ g.id , g.count ] ) ),
      cert: ratings,
      nocert: ratings,
    };
    Dom.text( Dom.get( "filter-sheet-show" ) , I18n.fill( "filters.show_n" , { n: this.total.toLocaleString() } ) );
    FilterSheet.render( Dom.get( "filter-sheet-body" ) , this.toQuery() , "movie" , [] , ( next , sheetOnly ) => this.apply( next , sheetOnly ) , {
      ids: this.SHEET,
      counts: counts,
      defs: this.sheetDefs(),
      // The scale reads G, PG, PG-13, R: kept in the server's order.
      ordered: [ "cert" , "nocert" ],
      label: ( id , value ) => ( id === "cert" || id === "nocert" ? this.ratingNames[ value ] || this.ratingLabel( value ) : FilterBar.valueLabel( id , value ) ),
    } );
  },

  renderGrid() {
    const shown = this.films.filter( ( film ) => this.visible( film ) );
    this.result = { rows: shown.map( ( film ) => this.row( film ) ) };
    const container = Dom.el( "div" , { class: "media-grid layout-" + this.card.layout + " size-" + this.card.size } );
    this.result.rows.forEach( ( row ) => container.appendChild( Card.build( row , this.card , {} ) ) );
    Dom.swap( this.grid , container );
    Dom.show( Dom.get( "discover-more" ) , this.films.length < this.total );
    Dom.show( Dom.get( "discover-empty" ) , shown.length === 0 );
  },

  // The server leaves out watched and skipped films unless a Show switch is
  // on; this does the same for a film marked on this page, so it goes at once. It
  // stays in this.films, so Undo brings it back and Load more's offset holds.
  visible( film ) {
    const inLibrary = film.title_id ? Library.get( film.title_id ) : null;
    const status = inLibrary ? inLibrary.s.status : film.my_status;
    const skipped = film.verdict === "skip" || status === "dropped";
    const watched = status === "watched";
    const want = ( name , on ) => {
      const mode = this.value( name );
      return mode === "all" || ( mode === "only" ) === on;
    };
    // Added on this page while "in my library" is hidden: it goes too.
    if ( this.params.library === "hide" && inLibrary ) return false;
    return want( "skipped" , skipped ) && want( "watched" , watched );
  },

  ratingLabel( id ) {
    return id === "none" ? I18n.get( "filters.cert_none" ) : id === "unknown" ? I18n.get( "discover.rating_unknown" ) : id;
  },

  topicLabel( id ) {
    const topic = ( this.meta.topics || [] ).find( ( entry ) => entry.id === id );
    return topic ? topic.label : id;
  },

  setCard( card ) {
    const before = this.card;
    Undo.run( {
      label: I18n.get( "undo.card_layout" ),
      merge: "card",
      do: () => { this.card = card; Prefs.setCard( "discover" , card ); this.renderGrid(); Customizer.refresh(); },
      undo: () => { this.card = before; Prefs.setCard( "discover" , before ); this.renderGrid(); Customizer.refresh(); },
    } );
  },

  // -- wiring -----------------------------------------------------------------

  wire() {
    let timer = null;
    Dom.get( "discover-search" ).addEventListener( "input" , ( event ) => {
      window.clearTimeout( timer );
      timer = window.setTimeout( () => this.set( { q: event.target.value.trim() } ) , 250 );
    } );
    Dom.get( "discover-more" ).addEventListener( "click" , () => this.load( true ) );
    // The Filters sheet is shared with the library: whichever screen is
    // showing draws it and takes its changes.
    const sheet = Dom.get( "filter-sheet" );
    sheet.addEventListener( "show.bs.offcanvas" , () => { if ( Nav.screen() !== "discover" ) return; this.sheetOpen = true; this.renderSheet(); } );
    sheet.addEventListener( "hidden.bs.offcanvas" , () => { this.sheetOpen = false; } );
    Dom.get( "filter-sheet-clear" ).addEventListener( "click" , () => {
      if ( Nav.screen() !== "discover" ) return;
      const next = this.toQuery();
      next.filters = {};
      this.apply( next );
    } );
    document.addEventListener( "keydown" , ( event ) => this.onKey( event ) );
    Dom.all( "[data-discover-layout]" ).forEach( ( button ) => Dom.onPress( button , () => this.setCard( Object.assign( {} , this.card , { layout: button.getAttribute( "data-discover-layout" ) } ) ) ) );
    this.grid.addEventListener( "click" , ( event ) => {
      const article = event.target.closest( ".media-card" );
      if ( !article ) return;
      const row = ( this.result.rows || [] ).find( ( r ) => r.t.id === article.getAttribute( "data-id" ) );
      if ( !row ) return;
      const chip = event.target.closest( "[data-filter]" );
      if ( chip && chip.getAttribute( "data-filter" ) === "genre" ) { this.toggle( "genre" , chip.getAttribute( "data-value" ) ); return; }
      if ( chip && chip.getAttribute( "data-filter" ) === "cert" ) { this.toggle( "rating" , chip.getAttribute( "data-value" ) ); return; }
      if ( Card.clicked( event , article ) ) return;
      const control = event.target.closest( "[data-action]" );
      if ( !control ) return;
      Dom.steady( control , () => this.act( control.getAttribute( "data-action" ) , row ) );
    } );
    CardMenu.wire( this.grid , {
      row: ( id ) => ( this.result.rows || [] ).find( ( r ) => r.t.id === id ),
      ids: () => CardMenu.discover(),
      run: ( id , row ) => this.act( id , row ),
    } );
  },

  onKey( event ) {
    if ( Nav.screen() !== "discover" || event.ctrlKey || event.metaKey || event.altKey || Undo.typing( event.target ) ) return;
    if ( document.querySelector( ".modal.show, .offcanvas.show" ) ) return;
    if ( event.key === "/" ) {
      event.preventDefault();
      Dom.get( "discover-search" ).focus();
    } else if ( event.key === "f" ) {
      bootstrap.Offcanvas.getOrCreateInstance( Dom.get( "filter-sheet" ) ).show();
    }
  },

  async act( action , row ) {
    const film = row.film;
    try {
      if ( action === "expand" ) {
        Card.toggle( this.grid.querySelector( '.media-card[data-id="' + CSS.escape( row.t.id ) + '"]' ) );
        return;
      }
      if ( action === "edit" ) {
        if ( row.inLibrary ) Editor.open( Library.get( film.title_id ) );
        else if ( film.url ) window.open( film.url , "_blank" , "noopener" );
        return;
      }
      if ( action === "skip" ) {
        const next = film.verdict === "skip" ? null : "skip";
        const before = film.verdict || null;
        await Undo.run( {
          label: I18n.fill( next ? "undo.skipped" : "undo.unskipped" , { title: film.title } ),
          toast: true,
          do: async () => { await Api.post( Api.forSubject( "/api/discover/verdict" ) , { key: film.key , verdict: next } ); film.verdict = next; this.renderGrid(); },
          undo: async () => { await Api.post( Api.forSubject( "/api/discover/verdict" ) , { key: film.key , verdict: before } ); film.verdict = before; this.renderGrid(); },
        } );
        return;
      }
      if ( action === "add" && row.inLibrary ) {
        // Already in the library: its Details, where everything else is.
        Editor.open( Library.get( film.title_id ) );
        return;
      }
      if ( action === "add" || action === "seen" ) {
        const status = action === "add" ? null : "watched";
        if ( row.inLibrary ) {
          const current = Library.get( film.title_id ).s.status;
          const next = current === status ? null : status;
          await Library.setState( film.title_id , { status: next } , I18n.fill( next ? "undo.watched" : "undo.unwatched" , { title: film.title } ) );
          this.renderGrid();
          return;
        }
        let created = null;
        await Undo.run( {
          label: I18n.fill( "undo.added_one" , { title: film.title } ),
          toast: true,
          do: async () => {
            const send = ( force ) => Api.post( Api.forSubject( "/api/discover/add" ) , { film: film , status: status , force: force } );
            try {
              created = await send( false );
            } catch ( error ) {
              if ( error.status !== 409 ) throw error;
              const dupes = error.payload.dupes || [];
              // Already in the library (perhaps under another name): put that
              // one on the list rather than adding a second copy -- back out
              // of Trash first, if that is where it is.
              const same = dupes.find( ( dupe ) => dupe.score >= 1 );
              if ( same ) {
                created = null;
                film.title_id = same.id;
                if ( same.title.deleted_at ) await Api.restoreTitle( same.id );
                await Library.refresh();
                if ( status ) await Library.setState( same.id , { status: status } , I18n.fill( "undo.watched" , { title: same.title.title } ) );
                this.renderGrid();
                return;
              }
              // Only something like it (a near spelling, a remake): ask.
              const near = dupes[ 0 ];
              const named = ( t ) => "“" + t.title + "”" + ( t.year ? " (" + t.year + ")" : "" );
              const question = I18n.fill( "discover.maybe_dupe" , { film: named( film ) , title: near ? named( near.title ) : "" } );
              if ( !( await Dom.confirm( question ) ) ) throw new DiscoverScreen.Cancelled();
              created = await send( true );
            }
            film.title_id = created.title.id;
            await Library.refresh();
            this.renderGrid();
          },
          undo: async () => {
            if ( !created ) return;
            await Api.deleteTitle( created.title.id );
            film.title_id = null;
            await Library.refresh();
            this.renderGrid();
          },
        } );
      }
    } catch ( error ) {
      if ( !( error instanceof DiscoverScreen.Cancelled ) ) Dom.toast( error.message , "error" );
    }
  },
};
