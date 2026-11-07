// What a card's buttons do. One delegated listener per grid, so thousands of
// cards cost one handler, and every state change goes through
// Library.setState -- which makes each one undoable (Ctrl+Z, or the toast).
const CardActions = {
  // The screen's callbacks: { open( row ) , filter( id , value ) ,
  // select( row , event ) , selecting() }.
  wire( container , screen ) {
    container.addEventListener( "click" , ( event ) => {
      const article = event.target.closest( ".media-card" );
      if ( !article ) return;
      const row = Library.get( article.getAttribute( "data-id" ) );
      if ( !row ) return;
      if ( screen.selecting() && !event.target.closest( "a, .dropdown-menu, [data-bs-toggle]" ) ) {
        event.preventDefault();
        screen.select( row , event );
        return;
      }
      const chip = event.target.closest( "[data-filter]" );
      if ( chip ) {
        screen.filter( chip.getAttribute( "data-filter" ) , chip.getAttribute( "data-value" ) );
        return;
      }
      if ( Card.clicked( event , article ) ) return;
      const control = event.target.closest( "[data-action]" );
      if ( !control ) {
        // A click on the card itself: its Details.
        if ( !event.target.closest( "a, input, button, .dropdown-menu" ) ) screen.open( row );
        return;
      }
      this.run( control.getAttribute( "data-action" ) , row , control , screen );
    } );
  },

  async run( action , row , control , screen ) {
    const s = row.s || {};
    const title = row.t.title;
    try {
      switch ( action ) {
        case "expand":
          Card.toggle( control.closest( ".media-card" ) );
          return;
        case "edit": case "open":
          screen.open( row );
          return;
        case "restore":
          await Library.restoreTitle( row.t.id );
          return;
        case "watched":
          await Library.setState( row.t.id , { status: s.status === "watched" ? null : "watched" } ,
            I18n.fill( s.status === "watched" ? "undo.unwatched" : "undo.watched" , { title: title } ) );
          return;
        case "queue": {
          const on = s.status === "queue" || s.status === "watching";
          await Library.setState( row.t.id , { status: on ? null : "queue" } , I18n.fill( on ? "undo.unqueued" : "undo.queued" , { title: title } ) );
          return;
        }
        case "watching":
          await Library.setState( row.t.id , { status: s.status === "watching" ? null : "watching" } , I18n.fill( "undo.watching" , { title: title } ) );
          return;
        case "drop":
          await Library.setState( row.t.id , { status: s.status === "dropped" ? null : "dropped" } , I18n.fill( "undo.dropped" , { title: title } ) );
          return;
        case "love":
          await Library.setState( row.t.id , { heart: !s.heart } , I18n.fill( s.heart ? "undo.unloved" : "undo.loved" , { title: title } ) );
          return;
        case "playlist": {
          const value = control.getAttribute( "data-value" );
          if ( value === "new" ) {
            await Playlists.create( [ row.t.id ] , ( name ) => I18n.fill( "undo.playlist_added" , { title: title , name: name } ) );
            return;
          }
          const playlist = Playlists.get( Number( value ) );
          if ( !playlist ) return;
          if ( playlist.items.indexOf( row.t.id ) >= 0 ) {
            await Playlists.removeItems( playlist , [ row.t.id ] , I18n.fill( "undo.playlist_removed" , { title: title , name: playlist.name } ) , true );
          } else {
            await Playlists.add( playlist , [ row.t.id ] , I18n.fill( "undo.playlist_added" , { title: title , name: playlist.name } ) , true );
          }
          return;
        }
        case "rate": {
          const value = control.getAttribute( "data-value" );
          const rating = value ? Number( value ) : null;
          await Library.setState( row.t.id , { rating: rating } , I18n.fill( rating ? "undo.rated" : "undo.unrated" , { title: title , rating: rating } ) );
          return;
        }
        default:
          return;
      }
    } catch ( error ) {
      Dom.toast( error.message || I18n.get( "errors.generic" ) , "error" );
    }
  },
};
