// Discover: films from Wikipedia's lists -- box-office number ones, award
// winners, every American film of a year, topics like Pre-Code Hollywood --
// that are not on your list yet. Filtered and sorted on the server (it is
// 27,000 films), with the same chips, the same Clear all and the same cards
// as the library. Add puts a film in the family library;
// Seen it marks it watched; Skip hides it from you (only you) and can be
// taken back from "Skipped". What you have watched, and library titles you
// skipped, are hidden too until you ask for them.
//
//   #discover?q=&from=1930&to=1949&genre=Comedy,Romance&genremode=all
//            &rating=PG&topic=&only=awarded&watched=only&skipped=all&sort=imdb
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

  DEFAULTS: { sort: "notable" , watched: "hide" , skipped: "hide" , genremode: "any" },
  FIELDS: [ "q" , "from" , "to" , "genre" , "genremode" , "rating" , "topic" , "only" , "actor" , "watched" , "skipped" , "sort" ],

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
      try { this.meta = await Api.request( "/api/discover/meta" ); this.fillTopics(); } catch ( error ) { this.meta = { topics: [] , coverage: { films: 0 } }; }
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
    // The facets first: they are where a chip learns how to spell its genre.
    this.renderFacets();
    this.renderChips();
    Dom.get( "discover-search" ).value = this.params.q || "";
    Dom.get( "discover-from" ).value = this.params.from || "";
    Dom.get( "discover-to" ).value = this.params.to || "";
    Dom.get( "discover-sort" ).value = this.value( "sort" );
    Dom.get( "discover-topic" ).value = this.params.topic || "";
    Dom.get( "discover-only" ).value = this.params.only || "";
    // On means "include them" (all); an old link's "only" also reads as on.
    Dom.get( "discover-show-watched" ).checked = this.value( "watched" ) !== "hide";
    Dom.get( "discover-show-skipped" ).checked = this.value( "skipped" ) !== "hide";
    Dom.text( Dom.get( "discover-show-watched-label" ) , I18n.fill( "discover.show_watched" , { n: this.watchedCount || 0 } ) );
    Dom.text( Dom.get( "discover-show-skipped-label" ) , I18n.fill( "discover.show_skipped" , { n: this.skippedCount || 0 } ) );
    Dom.all( "[data-discover-layout]" ).forEach( ( button ) => button.classList.toggle( "active" , button.getAttribute( "data-discover-layout" ) === this.card.layout ) );
    this.renderGrid();
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
    return want( "skipped" , skipped ) && want( "watched" , watched );
  },

  chip( text , onRemove ) {
    return FilterBar.chip( text , onRemove );
  },

  renderChips() {
    const box = Dom.get( "discover-chips" );
    Dom.clear( box );
    const p = this.params;
    if ( p.q ) box.appendChild( this.chip( I18n.fill( "filters.chip_search" , { text: p.q } ) , () => this.set( { q: "" } ) ) );
    if ( p.from || p.to ) box.appendChild( this.chip( I18n.get( "filters.name_year" ) + ": " + ( p.from || "…" ) + "–" + ( p.to || "…" ) , () => this.set( { from: "" , to: "" } ) ) );
    if ( p.genre ) box.appendChild( this.chip( I18n.get( "filters.name_genre" ) + ": " + this.list( "genre" ).map( ( g ) => ( this.labels || {} )[ g.toLowerCase() ] || g ).join( " " + I18n.get( this.value( "genremode" ) === "all" ? "filters.joiner_all" : "filters.joiner_any" ) + " " ) , () => this.set( { genre: "" } ) ) );
    if ( p.rating ) box.appendChild( this.chip( I18n.get( "filters.name_cert" ) + ": " + this.list( "rating" ).map( ( r ) => this.ratingLabel( r ) ).join( " " + I18n.get( "filters.joiner_any" ) + " " ) , () => this.set( { rating: "" } ) ) );
    if ( p.topic ) box.appendChild( this.chip( I18n.get( "discover.topic" ) + ": " + this.topicLabel( p.topic ) , () => this.set( { topic: "" } ) ) );
    if ( p.only ) box.appendChild( this.chip( I18n.get( "discover.only_" + p.only ) , () => this.set( { only: "" } ) ) );
    if ( p.actor ) box.appendChild( this.chip( I18n.get( "discover.actor" ) + ": " + p.actor , () => this.set( { actor: "" } ) ) );
    if ( p.watched ) box.appendChild( this.chip( I18n.get( "discover.watched_" + p.watched ) , () => this.set( { watched: "" } ) ) );
    if ( p.skipped ) box.appendChild( this.chip( I18n.get( "discover.skipped_" + p.skipped ) , () => this.set( { skipped: "" } ) ) );
    const any = Object.keys( p ).some( ( name ) => name !== "sort" );
    if ( any ) {
      box.appendChild( Dom.el( "button" , { class: "btn btn-sm btn-link filter-clear" , text: I18n.get( "filters.clear_all" ) , attrs: { type: "button" } , on: { click: () => this.set( Object.fromEntries( this.FIELDS.map( ( name ) => [ name , "" ] ) ) ) } } ) );
    }
    Dom.show( box , box.childNodes.length > 0 );
  },

  ratingLabel( id ) {
    return id === "none" ? I18n.get( "filters.cert_none" ) : id === "unknown" ? I18n.get( "discover.rating_unknown" ) : id;
  },

  topicLabel( id ) {
    const topic = ( this.meta.topics || [] ).find( ( entry ) => entry.id === id );
    return topic ? topic.label : id;
  },

  facetButtons( box , entries , name , label ) {
    Dom.clear( box );
    const chosen = this.list( name );
    entries.forEach( ( entry ) => {
      const on = this.find( chosen , entry.id ) >= 0;
      box.appendChild( Dom.el( "button" , {
        class: "btn btn-sm " + ( on ? "btn-soft-primary" : "btn-outline-secondary" ) + ( entry.count === 0 && !on ? " opacity-50" : "" ),
        attrs: { type: "button" , "aria-pressed": String( on ) },
        children: [ Dom.el( "span" , { text: label( entry ) + " " } ) , Dom.el( "span" , { class: "badge text-bg-light" , text: String( entry.count ) } ) ],
        on: { click: () => this.toggle( name , entry.id ) },
      } ) );
    } );
  },

  renderFacets() {
    const genres = ( this.facets.genres || [] ).filter( ( g ) => g.id );
    const short = Filters.defs.genre.short;
    this.labels = Object.fromEntries( genres.map( ( g ) => [ g.id.toLowerCase() , g.label || g.id ] ) );
    const chosen = this.list( "genre" );
    const shown = genres.filter( ( g , at ) => this.showAllGenres || at < short || this.find( chosen , g.id ) >= 0 );
    this.facetButtons( Dom.get( "discover-genres" ) , shown , "genre" , ( g ) => g.label || g.id );
    Dom.show( Dom.get( "discover-genres-more" ) , genres.length > short );
    Dom.text( Dom.get( "discover-genres-more" ) , this.showAllGenres ? I18n.get( "filters.show_fewer" ) : I18n.fill( "filters.show_all" , { n: genres.length } ) );
    const mode = Dom.get( "discover-genremode" );
    Dom.show( mode , this.list( "genre" ).length > 1 );
    Dom.all( "button" , mode ).forEach( ( button ) => {
      const on = button.getAttribute( "data-mode" ) === this.value( "genremode" );
      button.className = "btn btn-sm " + ( on ? "btn-soft-primary" : "btn-outline-secondary" );
    } );
    this.facetButtons( Dom.get( "discover-ratings" ) , ( this.facets.ratings || [] ) , "rating" , ( r ) => r.label || this.ratingLabel( r.id ) );
  },

  fillTopics() {
    const select = Dom.get( "discover-topic" );
    ( this.meta.topics || [] ).forEach( ( topic ) => select.appendChild( Dom.el( "option" , { text: topic.label , attrs: { value: topic.id } } ) ) );
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
    [ [ "discover-from" , "from" ] , [ "discover-to" , "to" ] , [ "discover-sort" , "sort" ] , [ "discover-topic" , "topic" ] , [ "discover-only" , "only" ] ].forEach( ( pair ) => {
      Dom.get( pair[ 0 ] ).addEventListener( "change" , ( event ) => this.set( { [ pair[ 1 ] ]: event.target.value.trim() } ) );
    } );
    Dom.all( "#discover-genremode button" ).forEach( ( button ) => Dom.onPress( button , () => this.set( { genremode: button.getAttribute( "data-mode" ) } ) ) );
    Dom.onPress( Dom.get( "discover-genres-more" ) , () => { this.showAllGenres = !this.showAllGenres; this.renderFacets(); } );
    Dom.get( "discover-more" ).addEventListener( "click" , () => this.load( true ) );
    [ "watched" , "skipped" ].forEach( ( name ) => {
      Dom.get( "discover-show-" + name ).addEventListener( "change" , ( event ) => this.set( { [ name ]: event.target.checked ? "all" : "" } ) );
    } );
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
