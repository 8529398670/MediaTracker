// The library screen: one scope (All, Movies, TV, Radio drama...) and one
// list (Everything, Watched, Trash), searched, filtered, sorted and grouped
// by a query that lives in the URL. What to watch next is a playlist.
//
//   #library/movie/all?genre=Drama&sort=-imdb,title
//
// Each scope and list remembers its own last query on the account, so a
// filter set in Movies stays in Movies. The sidebar lists the scopes with
// their counts.
const LibraryScreen = {
  scope: "all",
  query: null,
  card: null,
  sheetOpen: false,
  selecting: false,
  selected: new Set(),
  renderToken: 0,
  leaving: null,
  CHUNK: 120,

  async init( me ) {
    this.me = me;
    Dom.show( Dom.get( "library-panel" ) , true );
    this.card = Prefs.card( "library" );
    this.grid = Dom.get( "library-grid" );
    CardActions.wire( this.grid , {
      open: ( row ) => Editor.open( row ),
      filter: ( id , value ) => this.toggleFilter( id , value ),
      selecting: () => this.selecting,
      select: ( row , event ) => this.toggleSelect( row , event ),
    } );
    CardMenu.wire( this.grid , {
      row: ( id ) => Library.get( id ),
      ids: () => CardMenu.LIBRARY,
      skip: () => this.selecting,
      // Skip on a library title is "not for me".
      run: ( id , row ) => {
        if ( id === "edit" ) Editor.open( row );
        else CardActions.run( id === "skip" ? "drop" : id , row , null , this );
      },
    } );
    SearchExtras.init( Dom.get( "library-extras" ) , {
      open: ( row ) => Editor.open( row ),
      filter: ( id , value ) => this.toggleFilter( id , value ),
      selecting: () => false,
      select: () => {},
    } );
    this.wireToolbar();
    Library.on( ( change ) => this.onLibrary( change ) );
    // The bulk bar's Add to playlist menu lists them.
    Playlists.on( () => { if ( this.selecting ) BulkBar.render(); } );
    window.addEventListener( "hashchange" , () => {
      if ( Nav.screen() === "library" ) this.route();
    } );
    document.addEventListener( "keydown" , ( event ) => this.onKey( event ) );
    if ( Nav.screen() === "" || Nav.screen() === "library" ) this.route();
    else this.route( "#library/all/all" , true );
  },

  // -- routing ------------------------------------------------------------

  route( hash , quiet ) {
    const parsed = QueryCodec.parse( hash || window.location.hash || "#library/all/all" );
    const scope = parsed.scope === "all" || Library.types.some( ( type ) => type.id === parsed.scope ) || !Library.loaded ? parsed.scope : "all";
    if ( !parsed.hasQuery && !quiet ) {
      const remembered = Prefs.lastQuery( scope + "/" + parsed.query.list );
      if ( remembered && remembered !== this.hashFor( scope , parsed.query ) ) {
        window.history.replaceState( null , "" , remembered );
        this.route( remembered , true );
        return;
      }
    }
    const scopeChanged = scope !== this.scope || !this.query || parsed.query.list !== this.query.list;
    this.scope = scope;
    this.query = parsed.query;
    if ( scopeChanged ) {
      this.selected.clear();
      window.scrollTo( 0 , 0 );
    }
    if ( !quiet && Nav.screen() !== "library" ) return;
    this.render();
  },

  hashFor( scope , query ) {
    return QueryCodec.format( "library" , scope , query );
  },

  // Every change to the query comes through here. Filter tweaks replace the
  // history entry rather than adding one, so Back leaves the screen instead
  // of stepping through every checkbox.
  setQuery( next , sheetOnly ) {
    if ( sheetOnly ) {
      this.renderSheet();
      return;
    }
    const query = Query.normalize( next , this.scope );
    const hash = this.hashFor( this.scope , query );
    window.history.replaceState( null , "" , hash );
    Prefs.setLastQuery( this.scope + "/" + query.list , hash );
    this.query = query;
    this.render();
  },

  toggleFilter( id , value ) {
    if ( !Filters.defs[ id ] ) return;
    const next = Query.clone( this.query );
    if ( Filters.subsumed( id , next.list , this.scope ) ) {
      // A type chip on a card in "All" is a filter; in Movies it is the scope.
      if ( id === "type" ) {
        window.location.hash = "#library/" + value + "/" + next.list;
      }
      return;
    }
    const current = next.filters[ id ] || { mode: "any" , values: [] };
    const values = current.values.indexOf( value ) >= 0 ? current.values.filter( ( v ) => v !== value ) : current.values.concat( [ value ] );
    next.filters[ id ] = { mode: current.mode || "any" , values: values };
    this.setQuery( next );
    Dom.toast( I18n.fill( values.indexOf( value ) >= 0 ? "filters.added" : "filters.removed" , { what: FilterBar.valueLabel( id , value ) } ) , "ok" );
  },

  // -- working out what to show -------------------------------------------

  compute() {
    const pool = Library.pool( this.scope , this.query.list );
    const match = Search.matcher( this.query.text );
    const searched = match ? pool.filter( match ) : pool;
    const keep = Filters.predicate( this.query.filters );
    const rows = Sorter.sort( searched.filter( keep ) , this.query.sort );
    return { pool: pool , searched: searched , rows: rows , groups: Grouper.group( rows , this.query.group , this.scope ) };
  },

  matches( row ) {
    if ( Library.pool( this.scope , this.query.list ).indexOf( row ) < 0 ) return false;
    const match = Search.matcher( this.query.text );
    if ( match && !match( row ) ) return false;
    return Filters.predicate( this.query.filters )( row );
  },

  // -- drawing ------------------------------------------------------------

  // Where you are, for the count line now that there is no heading:
  // "Movies", "Watched", "Trash". Everything goes without saying.
  placeLabel() {
    return this.query.list === "all" ? this.scopeLabel() : I18n.get( "lists." + this.query.list );
  },

  scopeLabel() {
    return this.scope === "all" ? I18n.get( "library.scope_all" ) : Vocab.typeLabel( this.scope );
  },

  render() {
    if ( !this.query || !Library.loaded ) return;
    const result = this.compute();
    this.result = result;
    Dom.text( Dom.get( "library-count" ) , I18n.fill( result.rows.length === 1 ? "library.count_one" : "library.count" , { place: this.placeLabel() , n: result.rows.length , total: result.pool.length } ) );
    FilterBar.render( Dom.get( "library-chips" ) , this.query , ( next ) => this.setQuery( next ) );
    const badge = Dom.get( "filters-badge" );
    const active = Query.activeCount( this.query );
    Dom.text( badge , String( active ) );
    Dom.show( badge , active > 0 );
    SortControl.render( Dom.get( "sort-button" ) , Dom.get( "sort-menu" ) , this.query , ( next ) => this.setQuery( next ) );
    // Only when it says something else: writing the trimmed text back while
    // someone types would eat the space they just typed ("forest|").
    const search = Dom.get( "library-search" );
    if ( search.value.trim() !== this.query.text ) search.value = this.query.text;
    this.renderLayoutButtons();
    if ( this.sheetOpen ) this.renderSheet();
    ViewsBar.render( "library" );
    LibraryNav.render();
    BulkBar.render();
    this.renderGrid( result );
    SearchExtras.render( this.query.text , result );
  },

  renderLayoutButtons() {
    Dom.all( "[data-layout]" ).forEach( ( button ) => {
      const on = button.getAttribute( "data-layout" ) === this.card.layout;
      button.classList.toggle( "active" , on );
      button.setAttribute( "aria-pressed" , String( on ) );
    } );
  },

  collapsedKey: "library-collapsed",

  collapsed() {
    try {
      return new Set( JSON.parse( window.localStorage.getItem( this.collapsedKey ) || "[]" ) );
    } catch ( error ) {
      return new Set();
    }
  },

  setCollapsed( key , on ) {
    const set = this.collapsed();
    if ( on ) set.add( key );
    else set.delete( key );
    try { window.localStorage.setItem( this.collapsedKey , JSON.stringify( Array.from( set ) ) ); } catch ( error ) { /* not remembered */ }
  },

  groupLabel( group ) {
    if ( group.value == null ) return I18n.get( "group.unknown" );
    switch ( this.query.group.by ) {
      case "decade": return group.value + "s";
      case "type": return Vocab.typeLabel( group.value );
      case "status": return I18n.get( "status." + group.value );
      case "rating": return I18n.fill( "group.rating_value" , { n: group.value } );
      case "imdb": return group.value + ".0–" + group.value + ".9";
      case "added": case "watched": {
        const parts = String( group.value ).split( "-" );
        return new Date( Number( parts[ 0 ] ) , Number( parts[ 1 ] ) - 1 , 1 ).toLocaleDateString( undefined , { year: "numeric" , month: "long" } );
      }
      default: return String( group.value );
    }
  },

  gridClass() {
    return "media-grid layout-" + this.card.layout + " size-" + this.card.size;
  },

  renderGrid( result ) {
    const token = ++this.renderToken;
    const scrollY = window.scrollY;
    const grid = this.grid;
    Dom.clear( grid );
    const empty = Dom.get( "library-empty" );
    Dom.show( empty , result.rows.length === 0 );
    if ( !result.rows.length ) {
      Dom.text( Dom.get( "library-empty-text" ) , I18n.get( result.pool.length ? "library.empty_filtered" : "library.empty_" + this.query.list ) );
      Dom.show( Dom.get( "library-empty-clear" ) , !Query.isDefault( this.query ) );
      return;
    }
    const collapsed = this.collapsed();
    const work = [];
    result.groups.forEach( ( group ) => {
      const container = Dom.el( "div" , { class: this.gridClass() } );
      if ( this.query.group.by !== "none" ) {
        const closed = collapsed.has( group.key );
        const header = Dom.el( "button" , {
          class: "group-header",
          attrs: { type: "button" , "aria-expanded": String( !closed ) },
          children: [ Card.icon( closed ? "chevron-right" : "chevron-down" ) , Dom.el( "span" , { class: "group-name" , text: this.groupLabel( group ) } ) , Dom.el( "span" , { class: "badge rounded-pill text-bg-light" , text: String( group.rows.length ) } ) ],
          on: { click: () => { this.setCollapsed( group.key , !closed ); this.renderGrid( this.result ); } },
        } );
        grid.appendChild( header );
        if ( closed ) return;
      }
      grid.appendChild( container );
      group.rows.forEach( ( row ) => work.push( [ container , row ] ) );
    } );
    const options = ( row ) => ( { selecting: this.selecting , selected: this.selected.has( row.t.id ) } );
    // The first screenful at once, the rest a chunk per frame, so a thousand
    // cards never freeze the page.
    const step = ( start ) => {
      if ( token !== this.renderToken ) return;
      const end = Math.min( work.length , start + this.CHUNK );
      for ( let i = start; i < end; i += 1 ) {
        const node = Card.build( work[ i ][ 1 ] , this.card , options( work[ i ][ 1 ] ) );
        work[ i ][ 0 ].appendChild( node );
      }
      if ( end < work.length ) window.requestAnimationFrame( () => step( end ) );
      else if ( scrollY ) window.scrollTo( 0 , scrollY );
    };
    step( 0 );
    if ( scrollY ) window.scrollTo( 0 , scrollY );
  },

  // One card changed: redraw just it. If it no longer belongs here (marked
  // unwatched while looking at Watched), it stays a moment, faded, so you can
  // see what happened, then the list closes up.
  redrawCard( id ) {
    const row = Library.get( id );
    const old = this.grid.querySelector( '.media-card[data-id="' + CSS.escape( id ) + '"]' );
    if ( !row ) return;
    // Not on screen but belongs here now (an undone Skip or Watched after
    // the card had already left): draw the list again to bring it back.
    if ( !old ) {
      if ( this.matches( row ) ) this.render();
      return;
    }
    const node = Card.build( row , this.card , { selecting: this.selecting , selected: this.selected.has( id ) } );
    old.replaceWith( node );
    if ( !this.matches( row ) ) {
      node.classList.add( "is-leaving" );
      window.clearTimeout( this.leaving );
      this.leaving = window.setTimeout( () => this.render() , 2500 );
    }
  },

  onLibrary( change ) {
    if ( change.kind === "state" ) {
      this.redrawCard( change.id );
      SearchExtras.draw();
      LibraryNav.render();
      return;
    }
    if ( change.kind === "load" && Nav.screen() === "library" ) {
      this.route( window.location.hash , true );
      return;
    }
    this.render();
  },

  // -- the toolbar ----------------------------------------------------------

  wireToolbar() {
    Dom.get( "views-save" ).addEventListener( "click" , () => ViewsBar.save() );
    const search = Dom.get( "library-search" );
    let timer = null;
    search.addEventListener( "input" , () => {
      window.clearTimeout( timer );
      timer = window.setTimeout( () => {
        const next = Query.clone( this.query );
        next.text = search.value.trim();
        this.setQuery( next );
      } , 180 );
    } );
    const sheet = Dom.get( "filter-sheet" );
    sheet.addEventListener( "show.bs.offcanvas" , () => { this.sheetOpen = true; this.renderSheet(); } );
    sheet.addEventListener( "hidden.bs.offcanvas" , () => { this.sheetOpen = false; } );
    Dom.all( "[data-layout]" ).forEach( ( button ) => {
      button.addEventListener( "click" , () => this.setCard( Object.assign( {} , this.card , { layout: button.getAttribute( "data-layout" ) } ) ) );
    } );
    Dom.get( "customize-button" ).addEventListener( "click" , () => Customizer.open( "library" ) );
    Dom.get( "select-button" ).addEventListener( "click" , () => this.setSelecting( !this.selecting ) );
    Dom.get( "library-empty-clear" ).addEventListener( "click" , () => this.setQuery( Query.defaults( this.query.list ) ) );
    Dom.get( "filter-sheet-clear" ).addEventListener( "click" , () => {
      const next = Query.clone( this.query );
      next.filters = {};
      this.setQuery( next );
    } );
  },

  renderSheet() {
    const result = this.result || this.compute();
    Dom.text( Dom.get( "filter-sheet-show" ) , I18n.fill( "filters.show_n" , { n: result.rows.length } ) );
    FilterSheet.render( Dom.get( "filter-sheet-body" ) , this.query , this.scope , result.searched , ( next , sheetOnly ) => this.setQuery( next , sheetOnly ) );
  },

  setCard( card , quiet ) {
    const before = this.card;
    if ( JSON.stringify( before ) === JSON.stringify( card ) ) return;
    const apply = ( value ) => {
      this.card = value;
      Prefs.setCard( "library" , value );
      this.render();
      Customizer.refresh();
    };
    if ( quiet ) {
      apply( card );
      return;
    }
    Undo.run( { label: I18n.get( "undo.card_layout" ) , merge: "card" , do: () => apply( card ) , undo: () => apply( before ) } );
  },

  // -- selecting several ------------------------------------------------------

  setSelecting( on ) {
    this.selecting = on;
    if ( !on ) this.selected.clear();
    Dom.get( "select-button" ).classList.toggle( "active" , on );
    Dom.get( "select-button" ).setAttribute( "aria-pressed" , String( on ) );
    this.render();
  },

  toggleSelect( row , event ) {
    const id = row.t.id;
    if ( event.shiftKey && this.lastPicked && this.result ) {
      const ids = this.result.rows.map( ( r ) => r.t.id );
      const a = ids.indexOf( this.lastPicked );
      const b = ids.indexOf( id );
      if ( a >= 0 && b >= 0 ) {
        ids.slice( Math.min( a , b ) , Math.max( a , b ) + 1 ).forEach( ( each ) => this.selected.add( each ) );
      }
    } else if ( this.selected.has( id ) ) {
      this.selected.delete( id );
    } else {
      this.selected.add( id );
    }
    this.lastPicked = id;
    this.grid.querySelectorAll( ".media-card" ).forEach( ( card ) => {
      const on = this.selected.has( card.getAttribute( "data-id" ) );
      card.classList.toggle( "is-selected" , on );
      const box = card.querySelector( ".media-select" );
      if ( box ) box.checked = on;
    } );
    BulkBar.render();
  },

  onKey( event ) {
    if ( Nav.screen() !== "library" || event.ctrlKey || event.metaKey || event.altKey || Undo.typing( event.target ) ) return;
    if ( document.querySelector( ".modal.show, .offcanvas.show" ) && event.key !== "Escape" ) return;
    if ( event.key === "/" ) {
      event.preventDefault();
      Dom.get( "library-search" ).focus();
    } else if ( event.key === "f" ) {
      bootstrap.Offcanvas.getOrCreateInstance( Dom.get( "filter-sheet" ) ).show();
    } else if ( event.key === "s" ) {
      this.setSelecting( !this.selecting );
    } else if ( event.key === "Escape" && this.selecting ) {
      this.setSelecting( false );
    }
  },
};

// The sidebar's library half: Watched (under Playlists), every scope with its
// count, and Trash.
const LibraryNav = {
  render() {
    const box = Dom.get( "sidebar-library" );
    if ( !box || !Library.loaded ) return;
    Dom.clear( box );
    const list = LibraryScreen.query ? LibraryScreen.query.list : "all";
    const here = Nav.screen() === "library";
    const watched = Dom.get( "sidebar-watched" );
    const watchedOn = here && list === "watched";
    watched.classList.toggle( "active" , watchedOn );
    watched.setAttribute( "aria-current" , watchedOn ? "page" : "false" );
    watched.onclick = () => Nav.closeSidebar();
    Dom.text( Dom.get( "sidebar-watched-count" ) , String( Library.counts( "all" ).watched ) );
    const scopes = [ { id: "all" , label: I18n.get( "library.scope_all" ) , icon: "grid-3x3-gap" } ].concat(
      Library.types.map( ( type ) => ( { id: type.id , label: type.label , icon: Vocab.typeIcon( type.id ) } ) ) );
    scopes.forEach( ( scope ) => {
      const counts = Library.counts( scope.id );
      const on = here && LibraryScreen.scope === scope.id && list === "all";
      box.appendChild( Dom.el( "a" , {
        class: "nav-link" + ( on ? " active" : "" ),
        attrs: { href: "#library/" + scope.id + "/all" , "aria-current": on ? "page" : "false" },
        children: [
          Card.icon( scope.icon ),
          Dom.el( "span" , { class: "nav-link-text flex-grow-1" , text: scope.label } ),
          Dom.el( "span" , { class: "nav-count" , attrs: { title: I18n.get( "library.count_all_title" ) } , text: String( counts.all ) } ),
        ],
        on: { click: () => Nav.closeSidebar() },
      } ) );
    } );
    const trash = Library.trashCount();
    if ( trash ) {
      const on = here && list === "trash";
      box.appendChild( Dom.el( "a" , {
        class: "nav-link" + ( on ? " active" : "" ),
        attrs: { href: "#library/all/trash" },
        children: [ Card.icon( "trash3" ) , Dom.el( "span" , { class: "nav-link-text flex-grow-1" , text: I18n.get( "lists.trash" ) } ) , Dom.el( "span" , { class: "nav-count" , text: String( trash ) } ) ],
        on: { click: () => Nav.closeSidebar() },
      } ) );
    }
  },
};
