// Acting on several titles at once: pick cards (tap, or Shift+click for a
// range) with Select on, then one action for all of them --
// Watched, Love, Not for me, Remove from my list, a playlist, a type, a tag,
// or delete.
// Each is one undo step for the whole group.
const BulkBar = {
  render() {
    const bar = Dom.get( "bulk-bar" );
    const on = LibraryScreen.selecting;
    Dom.show( bar , on );
    if ( !on ) return;
    const count = LibraryScreen.selected.size;
    Dom.text( Dom.get( "bulk-count" ) , I18n.fill( "bulk.count" , { n: count } ) );
    Dom.all( "[data-bulk]" , bar ).forEach( ( button ) => { button.disabled = count === 0; } );
    Dom.get( "bulk-playlist-toggle" ).disabled = count === 0;
    if ( !bar._wired ) {
      bar._wired = true;
      bar.addEventListener( "click" , ( event ) => {
        const button = event.target.closest( "[data-bulk]" );
        if ( button ) Dom.steady( button , () => this.run( button.getAttribute( "data-bulk" ) , button.getAttribute( "data-value" ) ) );
      } );
      Dom.onPress( Dom.get( "bulk-all" ) , () => {
        ( LibraryScreen.result ? LibraryScreen.result.rows : [] ).forEach( ( row ) => LibraryScreen.selected.add( row.t.id ) );
        LibraryScreen.render();
      } );
      Dom.onPress( Dom.get( "bulk-none" ) , () => { LibraryScreen.selected.clear(); LibraryScreen.render(); } );
      Dom.get( "bulk-done" ).addEventListener( "click" , () => LibraryScreen.setSelecting( false ) );
    }
    const lists = Dom.get( "bulk-playlists" );
    Dom.clear( lists );
    Playlists.list.forEach( ( playlist ) => {
      lists.appendChild( Dom.el( "li" , { children: [ Dom.el( "button" , {
        class: "dropdown-item",
        text: playlist.name,
        attrs: { type: "button" , "data-bulk": "playlist" , "data-value": String( playlist.id ) },
      } ) ] } ) );
    } );
    if ( Playlists.list.length ) lists.appendChild( Dom.el( "li" , { children: [ Dom.el( "hr" , { class: "dropdown-divider" } ) ] } ) );
    lists.appendChild( Dom.el( "li" , { children: [ Dom.el( "button" , {
      class: "dropdown-item",
      text: I18n.get( "playlist.menu_new" ),
      attrs: { type: "button" , "data-bulk": "playlist" , "data-value": "new" },
    } ) ] } ) );
    const types = Dom.get( "bulk-types" );
    Dom.clear( types );
    Library.types.forEach( ( type ) => {
      types.appendChild( Dom.el( "li" , { children: [ Dom.el( "button" , {
        class: "dropdown-item",
        text: type.label,
        attrs: { type: "button" , "data-bulk": "type" , "data-value": type.id },
      } ) ] } ) );
    } );
  },

  async run( action , value ) {
    const ids = Array.from( LibraryScreen.selected );
    if ( !ids.length ) return;
    const n = ids.length;
    try {
      switch ( action ) {
        case "watched": await Library.setStates( ids , { status: "watched" } , I18n.fill( "undo.bulk_watched" , { n: n } ) ); break;
        case "dropped": await Library.setStates( ids , { status: "dropped" } , I18n.fill( "undo.bulk_dropped" , { n: n } ) ); break;
        case "unlist": await Library.setStates( ids , { status: null } , I18n.fill( "undo.bulk_unlisted" , { n: n } ) ); break;
        case "love": await Library.setStates( ids , { heart: true } , I18n.fill( "undo.bulk_loved" , { n: n } ) ); break;
        case "playlist": {
          if ( value === "new" ) {
            await Playlists.create( ids , ( name ) => I18n.fill( "undo.bulk_playlist" , { n: n , name: name } ) );
            break;
          }
          const playlist = Playlists.get( Number( value ) );
          if ( playlist ) await Playlists.add( playlist , ids , I18n.fill( "undo.bulk_playlist" , { n: n , name: playlist.name } ) , true );
          break;
        }
        case "type": await this.titles( ids , "set_type" , value , I18n.fill( "undo.bulk_type" , { n: n , type: Vocab.typeLabel( value ) } ) ); break;
        case "tag": {
          const tag = window.prompt( I18n.get( "bulk.tag_prompt" ) );
          if ( tag ) await this.titles( ids , "add_tags" , [ tag ] , I18n.fill( "undo.bulk_tagged" , { n: n , tag: tag } ) );
          break;
        }
        case "delete": await this.titles( ids , "delete" , null , I18n.fill( "undo.bulk_deleted" , { n: n } ) ); break;
        default: return;
      }
    } catch ( error ) {
      Dom.toast( error.message , "error" );
    }
  },

  // A shared-title change for many; its undo sends each title's own
  // previous values back.
  async titles( ids , op , value , label ) {
    let previous = {};
    await Undo.run( {
      label: label,
      toast: true,
      do: async () => {
        const result = await Api.bulkTitles( ids , op , value );
        previous = result.previous || {};
        await Library.refresh();
      },
      undo: async () => {
        const touched = Object.keys( previous );
        if ( op === "delete" ) await Api.bulkTitles( touched , "restore" , null );
        else await Api.bulkTitles( touched , "set_fields" , previous );
        await Library.refresh();
      },
    } );
  },
};
