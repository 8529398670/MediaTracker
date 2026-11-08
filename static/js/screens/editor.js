// One title, in full: everything known about it, the family's own words on
// it (title, tags, notes, links -- shared), and your own state (status,
// rating, heart, watched date, a private note). Save sends only what
// changed; each half is its own undo step.
const Editor = {
  row: null,
  modal: null,

  SHARED: [ "title" , "year" , "type" , "runtime" , "certification" , "creator" , "genres" , "cast" , "tags" , "overview" , "notes" , "poster_url" , "imdb_id" , "wiki_url" , "links" ],
  LISTS: [ "genres" , "cast" , "tags" ],
  NUMBERS: [ "year" , "runtime" ],

  init() {
    this.modal = bootstrap.Modal.getOrCreateInstance( Dom.get( "editor-modal" ) );
    Dom.get( "editor-form" ).addEventListener( "submit" , ( event ) => { event.preventDefault(); this.save(); } );
    Dom.get( "editor-delete" ).addEventListener( "click" , () => this.remove() );
    Dom.get( "editor-enrich" ).addEventListener( "click" , () => this.enrich() );
    // Watched and Love act at once, as on a card.
    Dom.get( "editor-head" ).addEventListener( "click" , ( event ) => {
      const control = event.target.closest( "[data-action]" );
      if ( control && this.row ) CardActions.run( control.getAttribute( "data-action" ) , this.row , control , { open: () => {} } );
    } );
    Library.on( ( change ) => {
      // Mine changed (from those buttons, or anywhere): redraw them, and
      // bring the status and heart fields along so Save does not undo it.
      if ( this.row && change.kind === "state" && change.id === this.row.t.id ) {
        const fresh = Library.get( this.row.t.id );
        if ( fresh ) {
          this.row = fresh;
          const s = fresh.s || Library.EMPTY_STATE;
          Dom.get( "edit-status" ).value = s.status || "";
          Dom.get( "edit-heart" ).checked = Boolean( s.heart );
          this.renderHeader();
        }
        return;
      }
      if ( this.row && change.kind !== "state" && Dom.get( "editor-modal" ).classList.contains( "show" ) ) {
        const fresh = Library.get( this.row.t.id );
        if ( fresh ) { this.row = fresh; this.renderHeader(); this.renderFamily(); }
      }
    } );
  },

  field( name ) {
    return Dom.get( "edit-" + name.replace( /_/g , "-" ) );
  },

  open( row ) {
    if ( !this.modal ) this.init();
    this.row = row;
    const t = row.t;
    const types = this.field( "type" );
    Dom.clear( types );
    Library.types.forEach( ( type ) => {
      const option = Dom.el( "option" , { text: type.label , attrs: { value: type.id } } );
      if ( type.id === t.type ) option.selected = true;
      types.appendChild( option );
    } );
    this.SHARED.forEach( ( name ) => {
      const input = this.field( name );
      if ( !input || name === "type" ) return;
      input.value = this.show( name , t[ name ] );
    } );
    const s = row.s || Library.EMPTY_STATE;
    Dom.get( "edit-status" ).value = s.status || "";
    Dom.get( "edit-rating" ).value = s.rating ? String( s.rating ) : "";
    Dom.get( "edit-heart" ).checked = Boolean( s.heart );
    Dom.get( "edit-watched-at" ).value = s.watched_at ? s.watched_at.slice( 0 , 10 ) : "";
    Dom.get( "edit-note" ).value = s.note || "";
    const acting = Library.subject !== App.currentUser.id;
    Dom.text( Dom.get( "editor-mine-heading" ) , acting ? I18n.fill( "editor.theirs_heading" , { name: Vocab.personName( Library.subject ) } ) : I18n.get( "editor.mine_heading" ) );
    Dom.show( Dom.get( "editor-delete" ) , !t.deleted_at );
    this.renderHeader();
    this.renderFamily();
    this.modal.show();
  },

  show( name , value ) {
    if ( value == null ) return "";
    if ( name === "links" ) return ( value || [] ).map( ( link ) => ( link.label ? link.label + " | " : "" ) + link.url ).join( "\n" );
    if ( this.LISTS.indexOf( name ) >= 0 ) return ( value || [] ).join( ", " );
    return String( value );
  },

  read( name ) {
    const raw = this.field( name ).value.trim();
    if ( name === "links" ) {
      return raw.split( "\n" ).map( ( line ) => line.trim() ).filter( Boolean ).map( ( line ) => {
        const cut = line.lastIndexOf( "|" );
        return cut < 0 ? { label: "" , url: line } : { label: line.slice( 0 , cut ).trim() , url: line.slice( cut + 1 ).trim() };
      } );
    }
    if ( this.LISTS.indexOf( name ) >= 0 ) return raw.split( "," ).map( ( part ) => part.trim() ).filter( Boolean );
    if ( this.NUMBERS.indexOf( name ) >= 0 ) return raw === "" ? null : Number( raw );
    return raw;
  },

  renderHeader() {
    const t = this.row.t;
    const head = Dom.get( "editor-head" );
    Dom.clear( head );
    if ( t.poster ) head.appendChild( Dom.el( "img" , { class: "editor-poster" , attrs: { src: t.poster , alt: "" } } ) );
    const facts = [];
    if ( t.year ) facts.push( String( t.year ) );
    facts.push( Vocab.typeLabel( t.type ) );
    if ( t.runtime ) facts.push( Vocab.runtime( t.runtime ) );
    if ( t.certification ) facts.push( t.certification );
    if ( this.row.score ) facts.push( "IMDb " + Vocab.score( this.row.score[ 0 ] ) + " (" + Vocab.votes( this.row.score[ 1 ] ) + ")" );
    const links = Dom.el( "div" , { class: "media-actions editor-buttons border-0 p-0 mt-2" } );
    Vocab.detailsButtons().forEach( ( id ) => {
      const button = Card.button( id , this.row );
      if ( button ) links.appendChild( button );
    } );
    head.appendChild( Dom.el( "div" , { class: "flex-grow-1 min-w-0" , children: [
      Dom.el( "h2" , { class: "h5 mb-1" , text: t.title } ),
      Dom.el( "p" , { class: "text-body-secondary small mb-1" , text: facts.join( " · " ) } ),
      t.overview ? Dom.el( "p" , { class: "small mb-1 editor-overview" , text: t.overview } ) : Dom.el( "span" ),
      Dom.el( "p" , { class: "small text-body-secondary mb-0" , text: I18n.fill( "editor.added_by" , { name: t.added_by != null ? Vocab.personName( t.added_by ) : "?" , date: Vocab.date( t.added_at ) } ) } ),
      links,
    ] } ) );
  },

  renderFamily() {
    const box = Dom.get( "editor-family" );
    Dom.clear( box );
    const social = this.row.social;
    const rows = [];
    Library.people.forEach( ( person ) => {
      if ( person.id === Library.subject || !social ) return;
      const bits = [];
      if ( social.watched.indexOf( person.id ) >= 0 ) bits.push( I18n.get( "status.watched" ) );
      else if ( social.watching.indexOf( person.id ) >= 0 ) bits.push( I18n.get( "status.watching" ) );
      else if ( social.queued.indexOf( person.id ) >= 0 ) bits.push( I18n.get( "status.queue" ) );
      if ( social.loved.indexOf( person.id ) >= 0 ) bits.push( "♥" );
      const rating = social.ratings[ String( person.id ) ];
      if ( rating ) bits.push( "★ " + rating );
      if ( bits.length ) rows.push( Dom.el( "li" , { class: "list-group-item d-flex justify-content-between" , children: [ Dom.el( "span" , { text: person.display_name } ) , Dom.el( "span" , { class: "text-body-secondary" , text: bits.join( " · " ) } ) ] } ) );
    } );
    Dom.show( Dom.get( "editor-family-section" ) , rows.length > 0 );
    rows.forEach( ( row ) => box.appendChild( row ) );
  },

  async save() {
    const row = this.row;
    const t = row.t;
    const changes = {};
    this.SHARED.forEach( ( name ) => {
      const value = name === "type" ? this.field( "type" ).value : this.read( name );
      if ( JSON.stringify( value ) !== JSON.stringify( name === "links" ? ( t.links || [] ).map( ( l ) => ( { label: l.label || "" , url: l.url } ) ) : t[ name ] == null ? ( this.LISTS.indexOf( name ) >= 0 ? [] : this.NUMBERS.indexOf( name ) >= 0 ? null : "" ) : t[ name ] ) ) {
        changes[ name ] = value;
      }
    } );
    const s = row.s || Library.EMPTY_STATE;
    const state = {};
    const status = Dom.get( "edit-status" ).value || null;
    if ( status !== ( s.status || null ) ) state.status = status;
    const rating = Dom.get( "edit-rating" ).value ? Number( Dom.get( "edit-rating" ).value ) : null;
    if ( rating !== ( s.rating || null ) ) state.rating = rating;
    const heart = Dom.get( "edit-heart" ).checked;
    if ( heart !== Boolean( s.heart ) ) state.heart = heart;
    const watched = Dom.get( "edit-watched-at" ).value;
    if ( watched !== ( s.watched_at ? s.watched_at.slice( 0 , 10 ) : "" ) ) state.watched_at = watched ? watched + "T12:00:00+00:00" : null;
    const note = Dom.get( "edit-note" ).value.trim();
    if ( note !== ( s.note || "" ) ) state.note = note;
    try {
      if ( Object.keys( changes ).length ) await Library.updateTitle( t.id , changes );
      if ( Object.keys( state ).length ) await Library.setState( t.id , state , I18n.fill( "undo.state_edit" , { title: t.title } ) );
      Undo.saved( Dom.get( "editor-form" ) );
      this.modal.hide();
      if ( Object.keys( changes ).length || Object.keys( state ).length ) Dom.toast( I18n.get( "ui.saved" ) , "ok" );
    } catch ( error ) {
      Dom.toast( error.message , "error" );
    }
  },

  async remove() {
    const id = this.row.t.id;
    this.modal.hide();
    try {
      await Library.deleteTitle( id );
    } catch ( error ) {
      Dom.toast( error.message , "error" );
    }
  },

  async enrich() {
    const button = Dom.get( "editor-enrich" );
    button.disabled = true;
    try {
      const result = await Api.enrichTitle( this.row.t.id , true );
      const changed = Object.keys( result.previous || {} );
      await Library.refresh();
      if ( changed.length ) {
        const id = this.row.t.id;
        Undo.record( {
          label: I18n.fill( "undo.enriched" , { title: this.row.t.title } ),
          toast: true,
          undo: async () => { await Api.updateTitle( id , result.previous ); await Library.refresh(); },
          redo: async () => { await Api.enrichTitle( id , true ); await Library.refresh(); },
        } );
        this.open( Library.get( id ) );
      } else {
        Dom.toast( I18n.get( "editor.enrich_nothing" ) , "ok" );
      }
    } catch ( error ) {
      Dom.toast( error.message , "error" );
    } finally {
      button.disabled = false;
    }
  },
};
