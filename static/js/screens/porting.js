// Import and export. Import reads a Markdown or Google Docs outline, a CSV,
// or a JSON export (this app's or the old app's): headings like "Watched" or
// "TV shows" set the status and type of what is under them, and other
// headings become tags. You see the rows first, with anything the library
// already has marked; the import is one undo step. Export is your library
// and your own state, as JSON, CSV or a Markdown outline.
const PortingScreen = {
  rows: [],
  CHUNK: 150,

  init() {
    Dom.show( Dom.get( "porting-panel" ) , true );
    Dom.get( "import-file" ).addEventListener( "change" , ( event ) => this.readFile( event.target.files[ 0 ] ) );
    Dom.get( "import-read" ).addEventListener( "click" , () => this.parse( Dom.get( "import-text" ).value ) );
    Dom.get( "import-go" ).addEventListener( "click" , () => this.run() );
    Dom.all( "[data-export]" ).forEach( ( link ) => {
      link.addEventListener( "click" , ( event ) => {
        event.preventDefault();
        window.location.href = Api.forSubject( "/api/export?format=" + link.getAttribute( "data-export" ) );
      } );
    } );
  },

  async readFile( file ) {
    if ( !file ) return;
    const text = await file.text();
    Dom.get( "import-text" ).value = text.length > 200000 ? "" : text;
    this.parse( text );
  },

  // A big JSON export is split into pieces the server will take (its body
  // limit is 1 MiB) and read piece by piece.
  async parse( text ) {
    if ( !text.trim() ) return;
    this.rows = [];
    try {
      const pieces = this.pieces( text );
      for ( const piece of pieces ) {
        const parsed = await Api.post( "/api/import/parse" , { text: piece , format: Dom.get( "import-format" ).value , type: LibraryScreen.scope !== "all" ? LibraryScreen.scope : "movie" } );
        this.rows = this.rows.concat( parsed.rows );
      }
      this.render();
    } catch ( error ) {
      Dom.toast( error.message , "error" );
    }
  },

  pieces( text ) {
    if ( text.length < 800000 || text.trim().charAt( 0 ) !== "{" && text.trim().charAt( 0 ) !== "[" ) return [ text ];
    const data = JSON.parse( text );
    const items = Array.isArray( data ) ? data : data.items || data.titles || [];
    const out = [];
    for ( let i = 0; i < items.length; i += 300 ) {
      const slice = items.slice( i , i + 300 );
      const states = {};
      if ( data.states ) slice.forEach( ( item ) => { if ( data.states[ item.id ] ) states[ item.id ] = data.states[ item.id ]; } );
      out.push( JSON.stringify( { items: slice , states: states } ) );
    }
    return out;
  },

  render() {
    const body = Dom.get( "import-table" ).querySelector( "tbody" );
    Dom.clear( body );
    const dupes = this.rows.filter( ( row ) => row.dupe && row.dupe.score >= 1 ).length;
    Dom.text( Dom.get( "import-summary" ) , I18n.fill( "porting.summary" , { n: this.rows.length , dupes: dupes } ) );
    Dom.show( Dom.get( "import-preview" ) , this.rows.length > 0 );
    this.rows.slice( 0 , 300 ).forEach( ( row ) => {
      const f = row.fields;
      body.appendChild( Dom.el( "tr" , { class: row.dupe && row.dupe.score >= 1 ? "table-warning" : "" , children: [
        Dom.el( "td" , { text: f.title } ),
        Dom.el( "td" , { text: f.year ? String( f.year ) : "" } ),
        Dom.el( "td" , { text: Vocab.typeLabel( f.type ) } ),
        Dom.el( "td" , { text: row.state.status ? I18n.get( "status." + row.state.status ) : "" } ),
        Dom.el( "td" , { text: ( f.tags || [] ).map( ( t ) => "#" + t ).join( " " ) } ),
        Dom.el( "td" , { class: "small" , text: row.dupe ? I18n.fill( "porting.already" , { title: row.dupe.title } ) : "" } ),
      ] } ) );
    } );
  },

  async run() {
    if ( !this.rows.length ) return;
    const skip = Dom.get( "import-skip" ).checked;
    const button = Dom.get( "import-go" );
    button.disabled = true;
    let batch = null;
    let created = 0;
    try {
      await Undo.run( {
        label: I18n.fill( "undo.imported" , { n: this.rows.length } ),
        toast: true,
        screen: null,
        do: async () => {
          batch = null;
          created = 0;
          for ( let i = 0; i < this.rows.length; i += this.CHUNK ) {
            Dom.text( Dom.get( "import-summary" ) , I18n.fill( "porting.importing" , { done: i , total: this.rows.length } ) );
            const answer = await Api.post( Api.forSubject( "/api/import/items" ) , { rows: this.rows.slice( i , i + this.CHUNK ) , batch_id: batch , skip_dupes: skip } );
            batch = answer.batch_id;
            created += answer.created;
          }
          await Library.refresh();
          Dom.text( Dom.get( "import-summary" ) , I18n.fill( "porting.done" , { n: created } ) );
        },
        undo: async () => {
          await Api.post( "/api/import/" + Api.id( batch ) + "/undo" );
          await Library.refresh();
        },
      } );
    } catch ( error ) {
      Dom.toast( error.message , "error" );
    } finally {
      button.disabled = false;
    }
  },
};
