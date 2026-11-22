// Suggestions: lists of things you might like -- Discover films not in the
// library yet, and library titles -- each with a note saying why. Agents fill
// them over MCP (add_suggestions); you import, watch or skip from here.
//
//   #suggestions                every list, in your order (drag to reorder)
//   #suggestions/12             one list, numbered in its own order
//   #suggestions/12?sort=-imdb  the same list sorted (IMDb, high to low)
//
// In its own order a list works like a playlist: type a number, drag, or use
// Move. Sorted any other way the numbers go, and the order is just a view.
// A Discover film keeps Discover's own buttons (Add, Seen it, Skip); once it
// is imported it is its library card, and stays in the list.
const SuggestionsScreen = {
  SORT_KEYS: [ "order" , "imdb" , "imdb_weighted" , "votes" , "year" , "title" , "runtime" , "cert" , "added" , "random" ],
  listIds: () => Suggestions.list.map( ( entry ) => entry.id ),

  init() {
    Dom.show( Dom.get( "suggestions-panel" ) , true );
    Dom.get( "suggestions-new" ).addEventListener( "click" , () => this.create() );
    Dom.get( "suggestion-rename" ).addEventListener( "click" , () => { const entry = this.current(); if ( entry ) this.safely( () => Suggestions.rename( entry ) ); } );
    Dom.get( "suggestion-delete" ).addEventListener( "click" , () => { const entry = this.current(); if ( entry ) this.safely( () => Suggestions.remove( entry ) ); } );
    const box = Dom.get( "suggestion-items" );
    // Library titles: the library's own card actions.
    CardActions.wire( box , {
      open: ( row ) => Editor.open( row ),
      filter: ( id , value ) => { window.location.hash = "#library/all/all"; LibraryScreen.toggleFilter( id , value ); },
      selecting: () => false,
      select: () => {},
    } );
    // Discover films: Discover's.
    box.addEventListener( "click" , ( event ) => this.onDiscoverClick( event ) );
    Suggestions.on( () => this.refresh() );
    Library.on( () => this.refresh() );
    window.addEventListener( "hashchange" , () => this.refresh() );
    this.refresh();
  },

  refresh() {
    if ( Nav.screen() === "suggestions" ) this.render();
  },

  // -- the hash ---------------------------------------------------------------

  parts() {
    const [ path , search ] = window.location.hash.replace( /^#/ , "" ).split( "?" );
    return { id: path.split( "/" )[ 1 ] , params: new URLSearchParams( search || "" ) };
  },

  currentId() {
    const part = this.parts().id;
    return part && /^\d+$/.test( part ) ? Number( part ) : null;
  },

  current() {
    const id = this.currentId();
    return id === null ? null : Suggestions.get( id );
  },

  // The sort in force, as SortControl's query: { sort: [ { key , dir } ] }.
  query() {
    const raw = this.parts().params.get( "sort" ) || "order";
    const sort = raw.split( "," ).filter( Boolean ).map( ( part ) => ( { key: part.replace( /^-/ , "" ) , dir: part.charAt( 0 ) === "-" ? "desc" : "asc" } ) )
      .filter( ( step ) => this.SORT_KEYS.indexOf( step.key ) >= 0 ).slice( 0 , 3 );
    return { sort: sort.length ? sort : [ { key: "order" , dir: "asc" } ] , group: { by: "none" , dir: "asc" } , filters: {} };
  },

  // In its own order, first to last: the numbers mean something.
  inOrder( query ) {
    return query.sort.length === 1 && query.sort[ 0 ].key === "order" && query.sort[ 0 ].dir === "asc";
  },

  setQuery( next ) {
    const sort = next.sort.map( ( step ) => ( step.dir === "desc" ? "-" : "" ) + step.key ).join( "," );
    const base = "#suggestions/" + this.currentId();
    window.location.hash = sort === "order" ? base : base + "?sort=" + encodeURIComponent( sort );
  },

  async safely( work ) {
    try {
      await work();
    } catch ( error ) {
      Dom.toast( error.message || I18n.get( "errors.generic" ) , "error" );
      await Suggestions.load();
    }
  },

  render() {
    const id = this.currentId();
    Dom.show( Dom.get( "suggestions-index" ) , id === null );
    Dom.show( Dom.get( "suggestion-detail" ) , id !== null );
    if ( id === null ) this.renderIndex();
    else this.renderDetail( this.current() );
  },

  // -- one item as a card row ---------------------------------------------------

  // { row , discover } for an item: its library title when it has one, else
  // its Discover film as Discover draws it, else null (gone from both).
  rowOf( item ) {
    const inLibrary = item.title_id ? Library.get( item.title_id ) : null;
    if ( inLibrary ) return { row: inLibrary , discover: false };
    if ( item.film ) return { row: DiscoverScreen.row( item.film ) , discover: true };
    return null;
  },

  poster( item ) {
    const found = this.rowOf( item );
    return found && found.row.t.poster ? found.row.t.poster : "";
  },

  // -- the index ------------------------------------------------------------

  renderIndex() {
    const box = Dom.get( "suggestions-list" );
    const entries = [];
    Dom.show( Dom.get( "suggestions-empty" ) , Suggestions.list.length === 0 );
    Suggestions.list.forEach( ( entry ) => {
      const posters = entry.items.slice( 0 , 4 ).map( ( item ) => {
        const src = this.poster( item );
        return src
          ? Dom.el( "img" , { class: "playlist-thumb" , attrs: { src: src , alt: "" , loading: "lazy" } } )
          : Dom.el( "span" , { class: "playlist-thumb is-empty" , children: [ Card.icon( "film" ) ] } );
      } );
      const waiting = entry.items.filter( ( item ) => !item.title_id ).length;
      const node = Dom.el( "div" , { class: "list-group-item playlist-entry border rounded h-100" , attrs: { "data-id": String( entry.id ) , "data-key": "suggestion-" + entry.id } , children: [
        Dom.el( "span" , { class: "playlist-grip" , attrs: { "aria-hidden": "true" , title: I18n.get( "playlist.drag" ) } , children: [ Card.icon( "grip-vertical" ) ] } ),
        Dom.el( "a" , { class: "playlist-open" , attrs: { href: "#suggestions/" + entry.id } , children: [
          Dom.el( "span" , { class: "playlist-thumbs" , children: posters.length ? posters : [ Dom.el( "span" , { class: "playlist-thumb is-empty" , children: [ Card.icon( "lightbulb" ) ] } ) ] } ),
          Dom.el( "span" , { class: "d-flex flex-column min-w-0" , children: [
            Dom.el( "span" , { class: "playlist-name" , text: entry.name } ),
            waiting ? Dom.el( "span" , { class: "small text-body-secondary" , text: I18n.fill( "suggestion.not_imported" , { n: waiting } ) } ) : Dom.el( "span" ),
          ] } ),
          Dom.el( "span" , { class: "playlist-count" , text: this.countText( entry.items.length ) } ),
        ] } ),
        Dom.el( "div" , { class: "dropdown" , children: [
          Dom.el( "button" , {
            class: "btn btn-sm btn-outline-secondary",
            attrs: { type: "button" , "data-bs-toggle": "dropdown" , "aria-expanded": "false" , "aria-label": I18n.fill( "playlist.manage" , { name: entry.name } ) },
            children: [ Card.icon( "three-dots" ) ],
          } ),
          Dom.el( "ul" , { class: "dropdown-menu dropdown-menu-end" , children: [
            PlaylistsScreen.menuItem( "suggestion.rename" , "pencil" , () => this.safely( () => Suggestions.rename( entry ) ) ),
            PlaylistsScreen.menuItem( "suggestion.delete" , "trash3" , () => this.safely( () => Suggestions.remove( entry ) ) ),
          ] } ),
        ] } ),
      ] } );
      OrderDrag.enable( node , {
        id: entry.id,
        ids: this.listIds,
        move: ( moving , position ) => {
          const ids = this.listIds().filter( ( other ) => other !== moving );
          ids.splice( position - 1 , 0 , moving );
          this.safely( () => Suggestions.reorder( ids ) );
        },
      } );
      entries.push( Dom.el( "div" , { class: "col" , attrs: { "data-key": "suggestion-col-" + entry.id } , children: [ node ] } ) );
    } );
    Dom.swap( box , ...entries );
  },

  countText( n ) {
    return I18n.fill( n === 1 ? "suggestion.count_one" : "suggestion.count" , { n: n } );
  },

  async create() {
    await this.safely( async () => {
      const created = await Suggestions.create( [] );
      if ( created ) window.location.hash = "#suggestions/" + created.id;
    } );
  },

  // -- one list -------------------------------------------------------------

  // Rows kept between renders, by ref, and only rebuilt when what they draw
  // changed: a move reorders the nodes already there.
  rows: new Map(),
  rowsFor: null,
  orders: null,
  shown: [],

  cardSettings( discover ) {
    const card = Object.assign( {} , Prefs.card( discover ? "discover" : "library" ) );
    card.layout = Prefs.card( "library" ).layout === "compact" ? "compact" : "list";
    return card;
  },

  // The items in the order showing: their own, or sorted by the query.
  ordered( entry , query ) {
    if ( this.inOrder( query ) ) return entry.items.slice();
    const rows = entry.items.map( ( item , index ) => {
      const found = this.rowOf( item );
      const row = found ? found.row : { t: { id: item.ref , title: "" } , s: null , score: null , social: null };
      return { t: Object.assign( {} , row.t , { added_at: item.added_at } ) , s: row.s , score: row.score , social: row.social , order: index , item: item };
    } );
    return Sorter.sort( rows , query.sort ).map( ( row ) => row.item );
  },

  renderDetail( entry ) {
    const box = Dom.get( "suggestion-items" );
    Dom.show( Dom.get( "suggestion-tools" ) , Boolean( entry ) );
    if ( !entry ) {
      Dom.clear( box );
      this.rows.clear();
      Dom.text( Dom.get( "suggestion-heading" ) , I18n.get( "suggestion.missing" ) );
      Dom.text( Dom.get( "suggestion-count" ) , "" );
      Dom.show( Dom.get( "suggestion-empty" ) , false );
      return;
    }
    const query = this.query();
    const inOrder = this.inOrder( query );
    SortControl.render( Dom.get( "suggestion-sort-button" ) , Dom.get( "suggestion-sort-menu" ) , query , ( next ) => this.setQuery( next ) , { keys: this.SORT_KEYS , group: false } );
    Dom.text( Dom.get( "suggestion-heading" ) , entry.name );
    Dom.text( Dom.get( "suggestion-count" ) , this.countText( entry.items.length ) );
    Dom.show( Dom.get( "suggestion-empty" ) , entry.items.length === 0 );

    const look = JSON.stringify( [ this.cardSettings( false ) , this.cardSettings( true ) ] ) + Prefs.ui( "appletv_app" , true ) + Vocab.mainButtons().join( "," ) + inOrder;
    if ( this.rowsFor !== entry.id + look ) {
      Dom.clear( box );
      this.rows.clear();
      this.rowsFor = entry.id + look;
    }
    box.className = "playlist-items suggestion-items layout-" + this.cardSettings( false ).layout + " size-" + this.cardSettings( false ).size + ( inOrder ? "" : " is-sorted" );

    const items = this.ordered( entry , query );
    this.shown = items;
    const keep = new Set( items.map( ( item ) => item.ref ) );
    this.rows.forEach( ( cached , ref ) => {
      if ( !keep.has( ref ) ) { cached.node.remove(); this.rows.delete( ref ); }
    } );
    let previous = null;
    items.forEach( ( item , index ) => {
      const found = this.rowOf( item );
      let cached = this.rows.get( item.ref );
      if ( !cached ) {
        cached = this.newRow( entry.id , item.ref , inOrder );
        this.rows.set( item.ref , cached );
      }
      const row = found ? found.row : null;
      const stamp = row ? [ row.t , row.s , found.discover && item.film ? item.film.verdict : null , found.discover ] : null;
      const same = cached.stamp && stamp && cached.stamp.every( ( part , at ) => part === stamp[ at ] );
      if ( !same ) {
        const fresh = row
          ? Card.build( row , this.cardSettings( found.discover ) , {} )
          : Dom.el( "div" , { class: "card playlist-gone" , children: [ Dom.el( "div" , { class: "card-body small text-body-secondary" , text: I18n.get( "suggestion.gone" ) } ) ] } );
        if ( cached.card ) cached.card.replaceWith( fresh );
        else cached.body.insertBefore( fresh , cached.note );
        cached.card = fresh;
        cached.stamp = stamp;
        cached.row = row;
        cached.discover = Boolean( found && found.discover );
      }
      Dom.clear( cached.note );
      if ( item.note ) {
        cached.note.appendChild( Card.icon( "lightbulb" ) );
        cached.note.appendChild( document.createTextNode( " " + item.note ) );
      }
      Dom.show( cached.note , Boolean( item.note ) );
      const title = row ? row.t.title : item.ref;
      if ( cached.input ) {
        if ( document.activeElement !== cached.input ) cached.input.value = String( index + 1 );
        cached.input.max = String( items.length );
        cached.input.setAttribute( "aria-label" , I18n.fill( "playlist.number_label" , { title: title , n: items.length } ) );
      }
      cached.remove.setAttribute( "aria-label" , I18n.fill( "suggestion.remove_title" , { title: title } ) );
      cached.title = title;
      const want = previous ? previous.nextSibling : box.firstChild;
      if ( want !== cached.node ) box.insertBefore( cached.node , want );
      previous = cached.node;
    } );
  },

  items( listId ) {
    const entry = Suggestions.get( listId );
    return entry ? entry.items.map( ( item ) => item.ref ) : [];
  },

  // One row: number, grip, Move, Note and Remove on the left (number, grip
  // and Move only in the list's own order), the card and its note on the right.
  newRow( listId , ref , inOrder ) {
    if ( !this.orders || this.orders.listId !== listId ) {
      this.orders = { listId: listId , ids: () => this.items( listId ) , move: ( moving , position ) => this.move( listId , moving , position ) };
    }
    const options = this.orders;
    const handle = Dom.el( "div" , { class: "playlist-handle" } );
    let input = null;
    if ( inOrder ) {
      input = Dom.el( "input" , { class: "form-control form-control-sm playlist-number" , attrs: { type: "number" , min: "1" , step: "1" , inputmode: "numeric" } } );
      const now = () => this.items( listId ).indexOf( ref ) + 1;
      input.addEventListener( "change" , () => {
        const number = now();
        const total = this.items( listId ).length;
        const wanted = Math.round( Number( input.value ) );
        if ( input.value === "" || !Number.isFinite( wanted ) ) { input.value = String( number ); return; }
        const position = Math.max( 1 , Math.min( total , wanted ) );
        if ( position === number ) { input.value = String( number ); return; }
        input.blur();
        this.move( listId , ref , position );
      } );
      input.addEventListener( "keydown" , ( event ) => { if ( event.key === "Escape" ) { input.value = String( now() ); input.blur(); } } );
      handle.appendChild( Dom.el( "span" , { class: "playlist-grip" , attrs: { "aria-hidden": "true" , title: I18n.get( "playlist.drag" ) } , children: [ Card.icon( "grip-vertical" ) ] } ) );
      handle.appendChild( input );
      handle.appendChild( OrderDrag.menu( ref , options ) );
    }
    const cached = { node: null , input: input , remove: null , card: null , note: null , body: null , stamp: null , row: null , title: ref };
    handle.appendChild( Dom.el( "button" , {
      class: "btn btn-sm btn-outline-secondary",
      attrs: { type: "button" , title: I18n.get( "suggestion.note" ) , "aria-label": I18n.get( "suggestion.note" ) },
      children: [ Card.icon( "pencil" ) ],
      on: { click: () => this.editNote( listId , ref , cached.title ) },
    } ) );
    cached.remove = Dom.el( "button" , {
      class: "btn btn-sm btn-outline-danger",
      attrs: { type: "button" , title: I18n.get( "suggestion.remove" ) },
      children: [ Card.icon( "x-lg" ) ],
      on: { click: () => {
        const entry = Suggestions.get( listId );
        if ( entry ) this.safely( () => Suggestions.removeItems( entry , [ ref ] , I18n.fill( "undo.suggestion_removed" , { title: cached.title , name: entry.name } ) , true ) );
      } },
    } );
    handle.appendChild( cached.remove );
    cached.note = Dom.el( "p" , { class: "suggestion-note small text-body-secondary mb-0 mt-1" } );
    cached.body = Dom.el( "div" , { class: "min-w-0" , children: [ cached.note ] } );
    cached.node = Dom.el( "div" , { class: "playlist-item" , attrs: { "data-id": ref } , children: [ handle , cached.body ] } );
    if ( inOrder ) OrderDrag.enable( cached.node , Object.assign( {} , options , { id: ref } ) );
    return cached;
  },

  editNote( listId , ref , title ) {
    const entry = Suggestions.get( listId );
    const item = entry && entry.items.find( ( other ) => other.ref === ref );
    if ( !item ) return;
    const note = window.prompt( I18n.fill( "suggestion.note_prompt" , { title: title } ) , item.note || "" );
    if ( note === null || note.trim() === ( item.note || "" ) ) return;
    this.safely( () => Suggestions.setNote( entry , ref , note.trim() , I18n.fill( "undo.suggestion_note" , { title: title } ) ) );
  },

  move( listId , ref , position ) {
    const entry = Suggestions.get( listId );
    if ( !entry ) return;
    const cached = this.rows.get( ref );
    const at = entry.items.findIndex( ( item ) => item.ref === ref );
    if ( at < 0 ) return;
    const [ moving ] = entry.items.splice( at , 1 );
    entry.items.splice( position - 1 , 0 , moving );
    this.render();
    this.safely( () => Suggestions.move( entry , ref , position ,
      I18n.fill( "undo.suggestion_moved" , { title: cached ? cached.title : ref , n: position } ) ) );
  },

  // A click on a Discover film's card: Discover's own buttons.
  onDiscoverClick( event ) {
    const article = event.target.closest( ".media-card" );
    if ( !article ) return;
    const holder = article.closest( ".playlist-item" );
    const cached = holder && this.rows.get( holder.getAttribute( "data-id" ) );
    if ( !cached || !cached.discover || !cached.row ) return;
    const row = cached.row;
    const chip = event.target.closest( "[data-filter]" );
    if ( chip ) {
      window.location.hash = "#discover";
      DiscoverScreen.toggle( chip.getAttribute( "data-filter" ) === "cert" ? "rating" : chip.getAttribute( "data-filter" ) , chip.getAttribute( "data-value" ) );
      return;
    }
    if ( Card.clicked( event , article ) ) return;
    const control = event.target.closest( "[data-action]" );
    if ( !control ) return;
    const action = control.getAttribute( "data-action" );
    if ( action === "suggest" ) { Suggestions.pick( control.getAttribute( "data-value" ) , row ); return; }
    if ( action === "expand" ) { Card.toggle( article ); return; }
    Dom.steady( control , async () => {
      await DiscoverScreen.act( action , row );
      // Skip changes the film in place; Add and Seen it reload the lists.
      cached.stamp = null;
      this.render();
    } );
  },
};
