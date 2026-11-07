// A search does not stop at the list that is open. Under the results: the
// rest of the library (other lists, other types), then Discover -- a film
// that is not in the library yet is exactly the one worth finding from the
// search box. Nothing found by name anywhere? Close spellings ("forest gump"
// for Forrest Gump), here and in Discover.
//
// The cards are the same cards: library ones act through CardActions,
// Discover ones through DiscoverScreen.act, just as on their own screens.
const SearchExtras = {
  box: null,
  text: "",
  token: 0,
  timer: null,
  // Discover's answer per search text: { films , fuzzy }, or null while asked.
  found: new Map(),
  rows: [],
  DISCOVER_LIMIT: 12,
  ELSEWHERE_LIMIT: 24,

  init( box , screen ) {
    this.box = box;
    CardActions.wire( box , screen );
    box.addEventListener( "click" , ( event ) => {
      const article = event.target.closest( ".search-extra-discover .media-card" );
      if ( !article ) return;
      const row = this.rows.find( ( r ) => r.t.id === article.getAttribute( "data-id" ) );
      if ( !row ) return;
      if ( Card.clicked( event , article ) ) return;
      const control = event.target.closest( "[data-action]" );
      if ( !control ) return;
      const action = control.getAttribute( "data-action" );
      if ( action === "expand" ) {
        Card.toggle( article );
        return;
      }
      DiscoverScreen.act( action , row ).then( () => this.draw() );
    } );
  },

  render( text , result ) {
    this.text = text;
    this.result = result;
    window.clearTimeout( this.timer );
    if ( text && !this.found.has( text ) ) this.timer = window.setTimeout( () => this.ask( text ) , 250 );
    this.draw();
  },

  async ask( text ) {
    const token = ++this.token;
    this.found.set( text , null );
    const query = new URLSearchParams( { q: text , limit: String( this.DISCOVER_LIMIT ) , skipped: "hide" } );
    let data;
    try {
      data = await Api.request( Api.forSubject( "/api/discover?" + query.toString() ) );
    } catch ( error ) {
      this.found.set( text , { films: [] , fuzzy: false } );
      return;
    }
    this.found.set( text , { films: data.films || [] , fuzzy: Boolean( data.fuzzy ) } );
    if ( token === this.token && text === this.text ) this.draw();
    this.loadFacts( text , data.films || [] );
  },

  // Posters and IMDb ids, the way the Discover screen fetches them.
  async loadFacts( text , films ) {
    const articles = films.map( ( film ) => film.article ).filter( Boolean );
    if ( !articles.length ) return;
    let facts;
    try { facts = await Api.request( "/api/discover/facts?" + articles.map( ( a ) => "a=" + encodeURIComponent( a ) ).join( "&" ) ); } catch ( error ) { return; }
    films.forEach( ( film ) => {
      const fact = facts[ film.article ];
      if ( !fact ) return;
      film.poster = fact.poster || film.poster;
      film.imdb = film.imdb || fact.imdb;
      if ( !film.imdbScore && fact.imdbScore ) film.imdbScore = fact.imdbScore;
      if ( !film.rating && fact.rating ) film.rating = fact.rating;
    } );
    if ( text === this.text ) this.draw();
  },

  draw() {
    const box = this.box;
    if ( !box ) return;
    Dom.clear( box );
    const text = this.text;
    if ( !text || !this.result || LibraryScreen.query.list === "trash" ) {
      Dom.show( box , false );
      return;
    }
    const shown = new Set( this.result.rows.map( ( row ) => row.t.id ) );
    const everywhere = Library.pool( "all" , "all" );
    const match = Search.matcher( text );
    const elsewhere = match ? everywhere.filter( ( row ) => !shown.has( row.t.id ) && match( row ) ) : [];
    const card = LibraryScreen.card;
    if ( elsewhere.length ) {
      box.appendChild( this.section( "library.search_elsewhere" , "library.search_elsewhere_note" , elsewhere.slice( 0 , this.ELSEWHERE_LIMIT ) , card , "" ) );
    }
    // Nothing anywhere by those words: what is spelled nearly like them.
    if ( !this.result.rows.length && !elsewhere.length ) {
      const close = Search.closeMatcher( text );
      const near = close ? everywhere.filter( close ).slice( 0 , this.ELSEWHERE_LIMIT ) : [];
      if ( near.length ) box.appendChild( this.section( "library.search_close" , "library.search_close_note" , near , card , "" ) );
    }
    const found = this.found.get( text );
    if ( found === undefined || found === null ) {
      box.appendChild( Dom.el( "p" , { class: "search-extra-note text-body-secondary small" , text: I18n.get( "library.search_looking" ) } ) );
    } else {
      const films = found.films.filter( ( film ) => !film.title_id || !Library.get( film.title_id ) );
      this.rows = films.map( ( film ) => DiscoverScreen.row( film ) );
      if ( this.rows.length ) {
        const discoverCard = Object.assign( {} , Prefs.card( "discover" ) , { layout: card.layout , size: card.size } );
        const section = this.section( "library.search_discover" , found.fuzzy ? "library.search_discover_close_note" : "library.search_discover_note" , this.rows , discoverCard , "search-extra-discover" );
        section.querySelector( ".search-extra-head" ).appendChild( Dom.el( "a" , {
          class: "btn btn-sm btn-outline-primary ms-auto",
          attrs: { href: "#discover?q=" + encodeURIComponent( text ) },
          children: [ Card.icon( "compass" ) , Dom.el( "span" , { text: " " + I18n.get( "library.search_discover_open" ) } ) ],
        } ) );
        box.appendChild( section );
      }
    }
    Dom.show( box , box.childNodes.length > 0 );
  },

  section( headingKey , noteKey , rows , card , extra ) {
    const grid = Dom.el( "div" , { class: "media-grid layout-" + card.layout + " size-" + card.size } );
    rows.forEach( ( row ) => grid.appendChild( Card.build( row , card , {} ) ) );
    return Dom.el( "section" , { class: "search-extra " + extra , children: [
      Dom.el( "div" , { class: "search-extra-head" , children: [
        Dom.el( "h2" , { class: "search-extra-title" , text: I18n.get( headingKey ) } ),
        Dom.el( "span" , { class: "badge rounded-pill text-bg-light" , text: String( rows.length ) } ),
        Dom.el( "span" , { class: "search-extra-note text-body-secondary small" , text: I18n.get( noteKey ) } ),
      ] } ),
      grid,
    ] } );
  },
};
