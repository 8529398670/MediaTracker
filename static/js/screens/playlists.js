// Playlists: your named, numbered lists of titles.
//
//   #playlists       every playlist, in your order (drag to reorder them)
//   #playlists/12    one playlist, numbered 1, 2, 3...
//
// Each title shows its number in a box. Type another number and it moves
// there; drag it and it takes the number where it lands. Either way the
// ones in between shift by one and every number on screen updates. The Move
// menu does the same from a keyboard or a phone.
//
// Titles are added from a title's Details (the Playlist button) or, several
// at once, with Select in the library.
const PlaylistsScreen = {
  card: null,
  // Shared by every row of the index: OrderDrag only lets a row drop onto
  // rows of the same list.
  playlistIds: () => Playlists.list.map( ( playlist ) => playlist.id ),

  init() {
    Dom.show( Dom.get( "playlists-panel" ) , true );
    Dom.get( "playlists-new" ).addEventListener( "click" , () => this.create() );
    Dom.get( "playlist-rename" ).addEventListener( "click" , () => { const playlist = this.current(); if ( playlist ) this.safely( () => Playlists.rename( playlist ) ); } );
    Dom.get( "playlist-delete" ).addEventListener( "click" , () => { const playlist = this.current(); if ( playlist ) this.safely( () => Playlists.remove( playlist ) ); } );
    CardActions.wire( Dom.get( "playlist-items" ) , {
      open: ( row ) => Editor.open( row ),
      filter: ( id , value ) => { window.location.hash = "#library/all/all"; LibraryScreen.toggleFilter( id , value ); },
      selecting: () => false,
      select: () => {},
    } );
    Playlists.on( () => this.refresh() );
    Library.on( () => this.refresh() );
    window.addEventListener( "hashchange" , () => this.refresh() );
    this.refresh();
  },

  refresh() {
    if ( Nav.screen() === "playlists" ) this.render();
  },

  // The playlist the hash names, or null on the index.
  currentId() {
    const part = window.location.hash.replace( /^#/ , "" ).split( "/" )[ 1 ];
    return part && /^\d+$/.test( part ) ? Number( part ) : null;
  },

  current() {
    const id = this.currentId();
    return id === null ? null : Playlists.get( id );
  },

  async safely( work ) {
    try {
      await work();
    } catch ( error ) {
      Dom.toast( error.message || I18n.get( "errors.generic" ) , "error" );
      await Playlists.load();
    }
  },

  render() {
    const id = this.currentId();
    const playlist = this.current();
    Dom.show( Dom.get( "playlists-index" ) , id === null );
    Dom.show( Dom.get( "playlist-detail" ) , id !== null );
    if ( id === null ) this.renderIndex();
    else this.renderDetail( playlist );
  },

  // -- the index ------------------------------------------------------------

  renderIndex() {
    const box = Dom.get( "playlists-list" );
    Dom.clear( box );
    Dom.show( Dom.get( "playlists-empty" ) , Playlists.list.length === 0 );
    Playlists.list.forEach( ( playlist ) => {
      const posters = playlist.items.slice( 0 , 4 ).map( ( titleId ) => {
        const row = Library.get( titleId );
        return row && row.t.poster
          ? Dom.el( "img" , { class: "playlist-thumb" , attrs: { src: row.t.poster , alt: "" , loading: "lazy" } } )
          : Dom.el( "span" , { class: "playlist-thumb is-empty" , children: [ Card.icon( row ? Vocab.typeIcon( row.t.type ) : "film" ) ] } );
      } );
      const entry = Dom.el( "div" , { class: "list-group-item playlist-entry" , attrs: { "data-id": String( playlist.id ) } , children: [
        Dom.el( "span" , { class: "playlist-grip" , attrs: { "aria-hidden": "true" , title: I18n.get( "playlist.drag" ) } , children: [ Card.icon( "grip-vertical" ) ] } ),
        Dom.el( "a" , { class: "playlist-open" , attrs: { href: "#playlists/" + playlist.id } , children: [
          Dom.el( "span" , { class: "playlist-thumbs" , children: posters.length ? posters : [ Dom.el( "span" , { class: "playlist-thumb is-empty" , children: [ Card.icon( "collection-play" ) ] } ) ] } ),
          Dom.el( "span" , { class: "playlist-name" , text: playlist.name } ),
          Dom.el( "span" , { class: "playlist-count" , text: this.countText( playlist.items.length ) } ),
        ] } ),
        Dom.el( "div" , { class: "dropdown" , children: [
          Dom.el( "button" , {
            class: "btn btn-sm btn-outline-secondary",
            attrs: { type: "button" , "data-bs-toggle": "dropdown" , "aria-expanded": "false" , "aria-label": I18n.fill( "playlist.manage" , { name: playlist.name } ) },
            children: [ Card.icon( "three-dots" ) ],
          } ),
          Dom.el( "ul" , { class: "dropdown-menu dropdown-menu-end" , children: [
            this.menuItem( "playlist.rename" , "pencil" , () => this.safely( () => Playlists.rename( playlist ) ) ),
            this.menuItem( "playlist.delete" , "trash3" , () => this.safely( () => Playlists.remove( playlist ) ) ),
          ] } ),
        ] } ),
      ] } );
      OrderDrag.enable( entry , {
        id: playlist.id,
        ids: this.playlistIds,
        move: ( moving , position ) => {
          const ids = this.playlistIds().filter( ( other ) => other !== moving );
          ids.splice( position - 1 , 0 , moving );
          this.safely( () => Playlists.reorder( ids ) );
        },
      } );
      box.appendChild( entry );
    } );
  },

  menuItem( key , icon , run ) {
    return Dom.el( "li" , { children: [ Dom.el( "button" , {
      class: "dropdown-item",
      attrs: { type: "button" },
      children: [ Card.icon( icon ) , Dom.el( "span" , { text: " " + I18n.get( key ) } ) ],
      on: { click: run },
    } ) ] } );
  },

  countText( n ) {
    return I18n.fill( n === 1 ? "playlist.count_one" : "playlist.count" , { n: n } );
  },

  async create() {
    await this.safely( async () => {
      const created = await Playlists.create( [] );
      if ( created ) window.location.hash = "#playlists/" + created.id;
    } );
  },

  // -- one playlist ---------------------------------------------------------

  // Rows are kept between renders and only rebuilt when their title or
  // its state changed: a move reorders the rows already on the page and
  // rewrites the numbers, rather than drawing hundreds of cards again.
  rows: new Map(),
  rowsFor: null,
  orders: null,

  renderDetail( playlist ) {
    const box = Dom.get( "playlist-items" );
    Dom.show( Dom.get( "playlist-tools" ) , Boolean( playlist ) );
    if ( !playlist ) {
      Dom.clear( box );
      this.rows.clear();
      Dom.text( Dom.get( "playlist-heading" ) , I18n.get( "playlist.missing" ) );
      Dom.text( Dom.get( "playlist-count" ) , "" );
      Dom.show( Dom.get( "playlist-empty" ) , false );
      return;
    }
    Dom.text( Dom.get( "playlist-heading" ) , playlist.name );
    Dom.text( Dom.get( "playlist-count" ) , this.countText( playlist.items.length ) );
    Dom.show( Dom.get( "playlist-empty" ) , playlist.items.length === 0 );

    // Always a list, top to bottom: a numbered order reads down the page.
    // Size and what each card shows are the person's own library choices.
    const card = Object.assign( {} , Prefs.card( "library" ) );
    card.layout = card.layout === "compact" ? "compact" : "list";
    // Where Apple TV links open is drawn into each row too.
    const look = JSON.stringify( card ) + Prefs.ui( "appletv_app" , true );
    if ( this.rowsFor !== playlist.id + look ) {
      Dom.clear( box );
      this.rows.clear();
      this.rowsFor = playlist.id + look;
    }
    box.className = "playlist-items layout-" + card.layout + " size-" + card.size;

    const ids = playlist.items;
    const keep = new Set( ids );
    this.rows.forEach( ( entry , titleId ) => {
      if ( !keep.has( titleId ) ) { entry.node.remove(); this.rows.delete( titleId ); }
    } );
    let previous = null;
    ids.forEach( ( titleId , index ) => {
      const row = Library.get( titleId ) || null;
      let entry = this.rows.get( titleId );
      if ( !entry ) {
        entry = this.newRow( playlist.id , titleId );
        this.rows.set( titleId , entry );
      }
      if ( entry.t !== ( row && row.t ) || entry.s !== ( row && row.s ) ) {
        const fresh = row
          ? Card.build( row , card , {} )
          : Dom.el( "div" , { class: "card playlist-gone" , children: [ Dom.el( "div" , { class: "card-body small text-body-secondary" , text: I18n.get( "playlist.gone" ) } ) ] } );
        if ( entry.card ) entry.card.replaceWith( fresh );
        else entry.node.appendChild( fresh );
        entry.card = fresh;
        entry.t = row && row.t;
        entry.s = row && row.s;
      }
      const title = row ? row.t.title : titleId;
      if ( document.activeElement !== entry.input ) entry.input.value = String( index + 1 );
      entry.input.max = String( ids.length );
      entry.input.setAttribute( "aria-label" , I18n.fill( "playlist.number_label" , { title: title , n: ids.length } ) );
      entry.remove.setAttribute( "aria-label" , I18n.fill( "playlist.remove_title" , { title: title } ) );
      // Only touch the DOM where the order actually changed.
      const want = previous ? previous.nextSibling : box.firstChild;
      if ( want !== entry.node ) box.insertBefore( entry.node , want );
      previous = entry.node;
    } );
  },

  // What the rows of one playlist act on, read when they act -- never a
  // copy taken when the row was drawn.
  items( playlistId ) {
    const playlist = Playlists.get( playlistId );
    return playlist ? playlist.items : [];
  },

  // One row: the grip, the number, Move and Remove on the left, the card
  // on the right (added by renderDetail).
  newRow( playlistId , titleId ) {
    if ( !this.orders || this.orders.playlistId !== playlistId ) {
      // One ids function shared by every row, so drops stay inside this list.
      this.orders = { playlistId: playlistId , ids: () => this.items( playlistId ) , move: ( moving , position ) => this.move( playlistId , moving , position ) };
    }
    const options = this.orders;
    const input = Dom.el( "input" , {
      class: "form-control form-control-sm playlist-number",
      attrs: { type: "number" , min: "1" , step: "1" , inputmode: "numeric" },
    } );
    const now = () => this.items( playlistId ).indexOf( titleId ) + 1;
    // "change" fires on Enter and when the box is left with a new number.
    input.addEventListener( "change" , () => {
      const number = now();
      const total = this.items( playlistId ).length;
      const wanted = Math.round( Number( input.value ) );
      if ( input.value === "" || !Number.isFinite( wanted ) ) { input.value = String( number ); return; }
      const position = Math.max( 1 , Math.min( total , wanted ) );
      if ( position === number ) { input.value = String( number ); return; }
      input.blur();
      this.move( playlistId , titleId , position );
    } );
    input.addEventListener( "keydown" , ( event ) => { if ( event.key === "Escape" ) { input.value = String( now() ); input.blur(); } } );
    const remove = Dom.el( "button" , {
      class: "btn btn-sm btn-outline-danger",
      attrs: { type: "button" , title: I18n.get( "playlist.remove" ) },
      children: [ Card.icon( "x-lg" ) ],
      on: { click: () => {
        const playlist = Playlists.get( playlistId );
        const row = Library.get( titleId );
        if ( playlist ) this.safely( () => Playlists.removeItems( playlist , [ titleId ] , I18n.fill( "undo.playlist_removed" , { title: row ? row.t.title : titleId , name: playlist.name } ) , true ) );
      } },
    } );
    const node = Dom.el( "div" , { class: "playlist-item" , attrs: { "data-id": titleId } , children: [
      Dom.el( "div" , { class: "playlist-handle" , children: [
        Dom.el( "span" , { class: "playlist-grip" , attrs: { "aria-hidden": "true" , title: I18n.get( "playlist.drag" ) } , children: [ Card.icon( "grip-vertical" ) ] } ),
        input,
        OrderDrag.menu( titleId , options ),
        remove,
      ] } ),
    ] } );
    OrderDrag.enable( node , Object.assign( {} , options , { id: titleId } ) );
    return { node: node , input: input , remove: remove , card: null , t: undefined , s: undefined };
  },

  // Renumbered on screen at once; the server's answer then replaces it.
  move( playlistId , titleId , position ) {
    const row = Library.get( titleId );
    const playlist = Playlists.get( playlistId );
    if ( !playlist ) return;
    const items = playlist.items.filter( ( id ) => id !== titleId );
    items.splice( position - 1 , 0 , titleId );
    playlist.items = items;
    this.render();
    this.safely( () => Playlists.move( playlist , titleId , position ,
      I18n.fill( "undo.playlist_moved" , { title: row ? row.t.title : titleId , n: position } ) ) );
  },
};
