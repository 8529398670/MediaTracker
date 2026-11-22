// Suggestion lists, in this browser: the subject's named lists of things they
// might like (app/models/suggestions.py) -- library titles, and Discover films
// not imported yet, each with an optional note saying why. Agents fill them
// over MCP; the person imports, watches or skips from the Suggestions screen.
//
// Each item comes back from the server already found: { ref , note ,
// added_at , title_id , film }. ref is a title id or "cat:<film key>";
// title_id is the library title it is (an imported film becomes its title),
// film the Discover film for a "cat:" ref.
//
// Each change goes through Undo, as playlists' do: item changes answer the
// items as they were, and the undo sends them back whole.
const Suggestions = {
  list: [],
  listeners: [],
  known: new Set(),

  on( listener ) {
    this.listeners.push( listener );
  },

  emit() {
    this.listeners.forEach( ( listener ) => {
      try { listener(); } catch ( error ) { console.error( error ); }
    } );
  },

  async init() {
    this.known = new Set( Library.rows.keys() );
    Library.on( ( change ) => {
      // A switch of who Showing is, or a title new to the library (a film
      // imported from here, or by anyone): read the lists again, so a film
      // becomes its library card.
      if ( change.kind === "load" ) { this.load(); return; }
      if ( change.kind === "refresh" && this.anyNewTitle() ) this.load();
    } );
    await this.load();
  },

  // Whether the library has a title the lists have not been read with.
  anyNewTitle() {
    const ids = Array.from( Library.rows.keys() );
    const fresh = ids.some( ( id ) => !this.known.has( id ) );
    this.known = new Set( ids );
    return fresh;
  },

  async load() {
    try {
      this.list = await Api.suggestions();
    } catch ( error ) {
      this.list = [];
    }
    this.emit();
  },

  get( id ) {
    return this.list.find( ( entry ) => entry.id === id ) || null;
  },

  // The ref a card's row is suggested by: its library title when it has one,
  // else its Discover film.
  refOf( row ) {
    if ( row.discover ) return row.inLibrary && row.film.title_id ? row.film.title_id : "cat:" + row.film.key;
    return row.t.id;
  },

  // The item in a list that is this card's title or film, or null.
  itemFor( entry , row ) {
    const ref = this.refOf( row );
    const titleId = row.discover ? row.film.title_id : row.t.id;
    const key = row.discover ? "cat:" + row.film.key : null;
    return entry.items.find( ( item ) => item.ref === ref || item.ref === key || ( titleId && item.title_id === titleId ) ) || null;
  },

  put( record ) {
    const at = this.list.findIndex( ( entry ) => entry.id === record.id );
    if ( at >= 0 ) this.list[ at ] = record;
    else this.list.push( record );
    this.emit();
  },

  async call( id , action , body ) {
    const result = await Api.suggestionCall( id , action , body || {} );
    if ( result.suggestion_list ) this.put( result.suggestion_list );
    return result;
  },

  // Asks for a name; resolves to the new list, or null if they backed out.
  // refs, when given, go in it at once.
  async create( refs , label ) {
    const name = window.prompt( I18n.get( "suggestion.name_prompt" ) );
    if ( !name || !name.trim() ) return null;
    let created = null;
    await Undo.run( {
      label: label ? label( name.trim() ) : I18n.fill( "undo.suggestion_created" , { name: name.trim() } ),
      toast: true,
      do: async () => {
        if ( created ) {
          created = ( await this.call( created.id , "restore" ) ).suggestion_list;
          return;
        }
        created = await Api.createSuggestionList( name.trim() );
        this.put( created );
        if ( refs && refs.length ) created = ( await this.call( created.id , "add" , this.body( refs ) ) ).suggestion_list;
      },
      undo: async () => {
        await Api.suggestionCall( created.id , "delete" , {} );
        this.list = this.list.filter( ( entry ) => entry.id !== created.id );
        this.emit();
      },
    } );
    return created;
  },

  async rename( entry ) {
    const name = window.prompt( I18n.get( "suggestion.rename_prompt" ) , entry.name );
    if ( !name || !name.trim() || name.trim() === entry.name ) return;
    const old = entry.name;
    await Undo.run( {
      label: I18n.fill( "undo.suggestion_renamed" , { name: name.trim() } ),
      do: () => this.call( entry.id , "update" , { name: name.trim() } ),
      undo: () => this.call( entry.id , "update" , { name: old } ),
    } );
  },

  async remove( entry ) {
    await Undo.run( {
      label: I18n.fill( "undo.suggestion_deleted" , { name: entry.name } ),
      toast: true,
      do: async () => {
        await Api.suggestionCall( entry.id , "delete" , {} );
        this.list = this.list.filter( ( other ) => other.id !== entry.id );
        this.emit();
      },
      undo: () => this.call( entry.id , "restore" ),
    } );
  },

  async reorder( ids ) {
    const before = this.list.map( ( entry ) => entry.id );
    const apply = async ( order ) => {
      this.list.sort( ( a , b ) => order.indexOf( a.id ) - order.indexOf( b.id ) );
      this.emit();
      await Api.reorderSuggestionLists( order );
    };
    await Undo.run( {
      label: I18n.get( "undo.suggestions_reordered" ),
      do: () => apply( ids ),
      undo: () => apply( before ),
    } );
  },

  // What add takes, from refs: library titles and Discover film keys apart.
  body( refs , note ) {
    const body = { title_ids: [] , film_keys: [] };
    refs.forEach( ( ref ) => {
      if ( ref.indexOf( "cat:" ) === 0 ) body.film_keys.push( ref.slice( 4 ) );
      else body.title_ids.push( ref );
    } );
    if ( note ) body.note = note;
    return body;
  },

  // One item change, undone by putting the whole list back as it was.
  async change( entry , action , body , label , toast ) {
    let before = null;
    await Undo.run( {
      label: label,
      toast: Boolean( toast ),
      do: async () => { before = ( await this.call( entry.id , action , body ) ).previous_items; },
      undo: () => this.call( entry.id , "set" , { items: before } ),
    } );
  },

  add( entry , refs , label , toast ) {
    return this.change( entry , "add" , this.body( refs ) , label , toast );
  },

  removeItems( entry , refs , label , toast ) {
    return this.change( entry , "remove" , { refs: refs } , label , toast );
  },

  move( entry , ref , position , label ) {
    return this.change( entry , "move" , { ref: ref , position: position } , label );
  },

  setNote( entry , ref , note , label ) {
    return this.change( entry , "note" , { ref: ref , note: note } , label );
  },

  // A pick from a card's Suggest menu (data-value: a list id, or "new"):
  // into that list, or out of it if it is there already.
  async pick( value , row ) {
    const title = row.t.title;
    try {
      if ( value === "new" ) {
        await this.create( [ this.refOf( row ) ] , ( name ) => I18n.fill( "undo.suggestion_added" , { title: title , name: name } ) );
        return;
      }
      const entry = this.get( Number( value ) );
      if ( !entry ) return;
      const item = this.itemFor( entry , row );
      if ( item ) await this.removeItems( entry , [ item.ref ] , I18n.fill( "undo.suggestion_removed" , { title: title , name: entry.name } ) , true );
      else await this.add( entry , [ this.refOf( row ) ] , I18n.fill( "undo.suggestion_added" , { title: title , name: entry.name } ) , true );
    } catch ( error ) {
      Dom.toast( error.message || I18n.get( "errors.generic" ) , "error" );
    }
  },
};
