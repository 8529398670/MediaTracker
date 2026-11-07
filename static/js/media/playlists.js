// Playlists, in this browser: the subject's named, numbered lists of titles
// (app/models/playlists.py). A title's number is its place in the list, so
// every add, remove and move renumbers the rest by itself.
//
// Each change goes through Undo. Item changes answer with the list as it
// was, and the undo sends that whole list back.
//
// They are personal, like state, so switching who Showing is reloads them
// (Library emits "load" on a switch).
const Playlists = {
  list: [],
  listeners: [],

  on( listener ) {
    this.listeners.push( listener );
  },

  emit() {
    this.listeners.forEach( ( listener ) => {
      try { listener(); } catch ( error ) { console.error( error ); }
    } );
  },

  async init() {
    Library.on( ( change ) => { if ( change.kind === "load" ) this.load(); } );
    await this.load();
  },

  async load() {
    try {
      this.list = await Api.playlists();
    } catch ( error ) {
      this.list = [];
    }
    this.emit();
  },

  get( id ) {
    return this.list.find( ( playlist ) => playlist.id === id ) || null;
  },

  containing( titleId ) {
    return this.list.filter( ( playlist ) => playlist.items.indexOf( titleId ) >= 0 );
  },

  // The server's copy replaces ours, so the numbers on screen are always
  // the server's numbers.
  put( record ) {
    const at = this.list.findIndex( ( playlist ) => playlist.id === record.id );
    if ( at >= 0 ) this.list[ at ] = record;
    else this.list.push( record );
    this.emit();
  },

  async call( id , action , body ) {
    const result = await Api.playlistCall( id , action , body || {} );
    if ( result.playlist ) this.put( result.playlist );
    return result;
  },

  // Asks for a name; resolves to the new playlist, or null if they backed out.
  async create( items , label ) {
    const name = window.prompt( I18n.get( "playlist.name_prompt" ) );
    if ( !name || !name.trim() ) return null;
    let created = null;
    await Undo.run( {
      label: label ? label( name.trim() ) : I18n.fill( "undo.playlist_created" , { name: name.trim() } ),
      toast: true,
      do: async () => {
        if ( created ) {
          created = ( await this.call( created.id , "restore" ) ).playlist;
        } else {
          created = await Api.createPlaylist( name.trim() , items );
          this.put( created );
        }
      },
      undo: async () => {
        await Api.playlistCall( created.id , "delete" , {} );
        this.list = this.list.filter( ( playlist ) => playlist.id !== created.id );
        this.emit();
      },
    } );
    return created;
  },

  async rename( playlist ) {
    const name = window.prompt( I18n.get( "playlist.rename_prompt" ) , playlist.name );
    if ( !name || !name.trim() || name.trim() === playlist.name ) return;
    const old = playlist.name;
    await Undo.run( {
      label: I18n.fill( "undo.playlist_renamed" , { name: name.trim() } ),
      do: () => this.call( playlist.id , "update" , { name: name.trim() } ),
      undo: () => this.call( playlist.id , "update" , { name: old } ),
    } );
  },

  async remove( playlist ) {
    await Undo.run( {
      label: I18n.fill( "undo.playlist_deleted" , { name: playlist.name } ),
      toast: true,
      do: async () => {
        await Api.playlistCall( playlist.id , "delete" , {} );
        this.list = this.list.filter( ( entry ) => entry.id !== playlist.id );
        this.emit();
      },
      undo: () => this.call( playlist.id , "restore" ),
    } );
  },

  async reorder( ids ) {
    const before = this.list.map( ( playlist ) => playlist.id );
    const apply = async ( order ) => {
      this.list.sort( ( a , b ) => order.indexOf( a.id ) - order.indexOf( b.id ) );
      this.emit();
      await Api.reorderPlaylists( order );
    };
    await Undo.run( {
      label: I18n.get( "undo.playlists_reordered" ),
      do: () => apply( ids ),
      undo: () => apply( before ),
    } );
  },

  // One item change, undone by putting the whole list back as it was.
  async change( playlist , action , body , label , toast ) {
    let before = null;
    await Undo.run( {
      label: label,
      toast: Boolean( toast ),
      do: async () => { before = ( await this.call( playlist.id , action , body ) ).previous_items; },
      undo: () => this.call( playlist.id , "set" , { items: before } ),
    } );
  },

  add( playlist , titleIds , label , toast ) {
    return this.change( playlist , "add" , { title_ids: titleIds } , label , toast );
  },

  removeItems( playlist , titleIds , label , toast ) {
    return this.change( playlist , "remove" , { title_ids: titleIds } , label , toast );
  },

  // position is 1-based; past the end means the end.
  move( playlist , titleId , position , label ) {
    return this.change( playlist , "move" , { title_id: titleId , position: position } , label );
  },
};
