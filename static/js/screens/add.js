// Adding titles: paste one or many lines -- a name, a name and a year, an
// IMDb or Wikipedia link -- look them up, check what came back, add.
//
// Each line shows its best match, the other candidates to switch to, and a
// warning if the library already has it (anyone in the family may have
// added it). Nothing is written until Add; the whole add is one undo step.
const AddScreen = {
  results: [],
  BATCH: 5,

  init() {
    Dom.show( Dom.get( "add-panel" ) , true );
    const types = Dom.get( "add-type" );
    Library.on( ( change ) => { if ( change.kind === "load" ) this.fillTypes( types ); } );
    this.fillTypes( types );
    Dom.get( "add-form" ).addEventListener( "submit" , ( event ) => { event.preventDefault(); this.lookUp(); } );
    Dom.get( "add-plain" ).addEventListener( "click" , () => this.addPlain() );
    Dom.get( "add-confirm" ).addEventListener( "click" , () => this.addChosen() );
    Dom.get( "add-clear" ).addEventListener( "click" , () => this.reset( true ) );
  },

  fillTypes( select ) {
    const current = select.value;
    Dom.clear( select );
    select.appendChild( Dom.el( "option" , { text: I18n.get( "add.type_auto" ) , attrs: { value: "" } } ) );
    Library.types.forEach( ( type ) => select.appendChild( Dom.el( "option" , { text: type.label , attrs: { value: type.id } } ) ) );
    select.value = current;
    // Arriving from a type's section, start on that type.
    if ( !current && LibraryScreen.scope && LibraryScreen.scope !== "all" ) select.value = LibraryScreen.scope;
  },

  lines() {
    return Dom.get( "add-text" ).value.split( "\n" ).map( ( line ) => line.replace( /^\s*(?:[-*•]|\d+[.)])\s+/ , "" ).trim() ).filter( Boolean );
  },

  reset( clearText ) {
    this.results = [];
    if ( clearText ) Dom.get( "add-text" ).value = "";
    this.render();
  },

  kind() {
    const type = Dom.get( "add-type" ).value;
    if ( !type ) return "any";
    const entry = Library.types.find( ( t ) => t.id === type );
    return entry ? entry.lookup : type;
  },

  async lookUp() {
    const lines = this.lines();
    if ( !lines.length ) return;
    const button = Dom.get( "add-lookup" );
    button.disabled = true;
    this.results = [];
    try {
      for ( let start = 0; start < lines.length; start += this.BATCH ) {
        Dom.text( Dom.get( "add-progress" ) , I18n.fill( "add.progress" , { done: start , total: lines.length } ) );
        const batch = lines.slice( start , start + this.BATCH );
        const answer = await Api.post( "/api/resolve" , { lines: batch , kind: this.kind() } );
        answer.results.forEach( ( result ) => {
          const certainDupe = result.dupes.some( ( dupe ) => dupe.score >= 1 );
          this.results.push( { result: result , pick: 0 , include: result.candidates.length > 0 && !certainDupe , status: Dom.get( "add-status" ).value } );
        } );
        this.render();
      }
      Dom.text( Dom.get( "add-progress" ) , "" );
    } catch ( error ) {
      Dom.text( Dom.get( "add-progress" ) , "" );
      const worded = I18n.get( "errors." + error.message );
      Dom.toast( worded || error.message , "error" );
    } finally {
      button.disabled = false;
    }
  },

  render() {
    const box = Dom.get( "add-results" );
    Dom.clear( box );
    this.results.forEach( ( entry , index ) => box.appendChild( this.row( entry , index ) ) );
    const chosen = this.results.filter( ( entry ) => entry.include && entry.result.candidates.length ).length;
    Dom.show( Dom.get( "add-actions" ) , this.results.length > 0 );
    Dom.text( Dom.get( "add-confirm-label" ) , I18n.fill( chosen === 1 ? "add.add_one" : "add.add_n" , { n: chosen } ) );
    Dom.get( "add-confirm" ).disabled = chosen === 0;
  },

  row( entry , index ) {
    const result = entry.result;
    const candidate = result.candidates[ entry.pick ];
    const item = Dom.el( "div" , { class: "list-group-item add-row" + ( entry.include ? "" : " is-off" ) } );
    const check = Dom.el( "input" , { class: "form-check-input mt-0" , attrs: { type: "checkbox" , "aria-label": I18n.fill( "add.include" , { title: result.input } ) } } );
    check.checked = entry.include;
    check.disabled = !candidate;
    check.addEventListener( "change" , () => { entry.include = check.checked; this.render(); } );
    item.appendChild( check );
    if ( candidate && candidate.poster ) item.appendChild( Dom.el( "img" , { class: "add-poster" , attrs: { src: candidate.poster , alt: "" , loading: "lazy" } } ) );
    else item.appendChild( Dom.el( "div" , { class: "add-poster is-empty" , children: [ Card.icon( "question-lg" ) ] } ) );
    const body = Dom.el( "div" , { class: "flex-grow-1 min-w-0" } );
    body.appendChild( Dom.el( "div" , { class: "small text-body-secondary text-truncate" , text: result.input } ) );
    if ( candidate ) {
      const f = candidate.fields;
      body.appendChild( Dom.el( "div" , { class: "fw-semibold" , text: f.title + ( f.year ? " (" + f.year + ")" : "" ) } ) );
      const facts = [ Vocab.typeLabel( this.typeFor( f ) ) ];
      if ( f.creator ) facts.push( f.creator );
      if ( f.runtime ) facts.push( Vocab.runtime( f.runtime ) );
      body.appendChild( Dom.el( "div" , { class: "small text-body-secondary" , text: facts.join( " · " ) } ) );
      if ( result.candidates.length > 1 ) {
        const select = Dom.el( "select" , { class: "form-select form-select-sm mt-1" , attrs: { "aria-label": I18n.get( "add.other_matches" ) } } );
        result.candidates.forEach( ( other , at ) => {
          const o = other.fields;
          const option = Dom.el( "option" , { text: o.title + ( o.year ? " (" + o.year + ")" : "" ) + " · " + ( other.source || Vocab.typeLabel( o.type ) ) , attrs: { value: String( at ) } } );
          if ( at === entry.pick ) option.selected = true;
          select.appendChild( option );
        } );
        select.addEventListener( "change" , () => { entry.pick = Number( select.value ); this.render(); } );
        body.appendChild( select );
      }
    } else {
      body.appendChild( Dom.el( "div" , { class: "text-danger small" , text: result.note || I18n.get( "add.no_match" ) } ) );
    }
    if ( candidate && !result.confident && result.note ) body.appendChild( Dom.el( "div" , { class: "small text-warning-emphasis" , text: result.note } ) );
    result.dupes.forEach( ( dupe ) => {
      const t = dupe.title;
      body.appendChild( Dom.el( "div" , { class: "small add-dupe" , children: [
        Card.icon( "exclamation-triangle" ),
        Dom.el( "span" , { text: " " + I18n.fill( dupe.score >= 1 ? "add.already" : "add.maybe" , { title: t.title + ( t.year ? " (" + t.year + ")" : "" ) } ) + " " } ),
        Dom.el( "button" , { class: "btn btn-link btn-sm p-0 align-baseline" , text: I18n.get( "add.open_existing" ) , attrs: { type: "button" } , on: { click: () => { const row = Library.get( t.id ); if ( row ) Editor.open( row ); } } } ),
      ] } ) );
    } );
    item.appendChild( body );
    return item;
  },

  // The type a candidate goes in as: the one chosen above, else what the
  // provider said it is, when that is a type the library has.
  typeFor( fields ) {
    const chosen = Dom.get( "add-type" ).value;
    if ( chosen ) return chosen;
    return Library.types.some( ( type ) => type.id === fields.type ) ? fields.type : "movie";
  },

  stateFor( status ) {
    return status ? { status: status } : { status: null };
  },

  async create( fieldsList , status ) {
    const created = [];
    for ( const fields of fieldsList ) {
      const answer = await Api.createTitle( fields , this.stateFor( status ) , true );
      created.push( answer.title.id );
    }
    return created;
  },

  async addChosen() {
    const picks = this.results.filter( ( entry ) => entry.include && entry.result.candidates.length );
    if ( !picks.length ) return;
    const fieldsList = picks.map( ( entry ) => {
      const fields = Object.assign( {} , entry.result.candidates[ entry.pick ].fields );
      fields.type = this.typeFor( fields );
      return fields;
    } );
    await this.commit( fieldsList , Dom.get( "add-status" ).value );
  },

  // Straight in, as typed: "Title (1950)" becomes a title and a year, and
  // the fill-in job looks up the rest in the background.
  async addPlain() {
    const lines = this.lines();
    if ( !lines.length ) return;
    const type = Dom.get( "add-type" ).value || ( LibraryScreen.scope !== "all" ? LibraryScreen.scope : "movie" );
    const fieldsList = lines.map( ( line ) => {
      const match = /^(.*?)[\s(\[,-]+((?:18|19|20)\d{2})[)\]]?\s*$/.exec( line );
      return match ? { title: match[ 1 ].trim() , year: Number( match[ 2 ] ) , type: type } : { title: line , type: type };
    } );
    await this.commit( fieldsList , Dom.get( "add-status" ).value );
  },

  async commit( fieldsList , status ) {
    const button = Dom.get( "add-confirm" );
    button.disabled = true;
    let created = [];
    try {
      await Undo.run( {
        label: I18n.fill( fieldsList.length === 1 ? "undo.added_one" : "undo.added_n" , { n: fieldsList.length , title: fieldsList[ 0 ].title } ),
        toast: true,
        screen: null,
        do: async () => {
          created = await this.create( fieldsList , status );
          await Library.refresh();
        },
        undo: async () => {
          await Api.bulkTitles( created , "delete" , null );
          await Library.refresh();
        },
      } );
      this.reset( true );
    } catch ( error ) {
      Dom.toast( error.message , "error" );
    } finally {
      button.disabled = false;
    }
  },
};
