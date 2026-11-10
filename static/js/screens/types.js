// The library's types: Movies and TV, plus whatever the family adds. Each
// is a section in the sidebar and says what it is looked up as when a title
// is added. Renaming is instant; deleting asks where its titles go, and can
// be undone (the titles come back with it).
const TypesScreen = {
  kinds: [],

  async init() {
    Dom.show( Dom.get( "types-panel" ) , true );
    try {
      this.kinds = ( await Api.vocab() ).lookup_kinds;
    } catch ( error ) {
      this.kinds = [ "movie" , "tv" , "other" ];
    }
    Dom.get( "type-form" ).addEventListener( "submit" , ( event ) => { event.preventDefault(); this.create(); } );
    this.fillKinds( Dom.get( "type-lookup" ) , "other" );
    Library.on( () => this.render() );
    this.render();
  },

  fillKinds( select , current ) {
    Dom.clear( select );
    this.kinds.forEach( ( kind ) => {
      const option = Dom.el( "option" , { text: I18n.get( "types.kind_" + kind ) || kind , attrs: { value: kind } } );
      if ( kind === current ) option.selected = true;
      select.appendChild( option );
    } );
  },

  render() {
    const body = Dom.get( "types-table" ).querySelector( "tbody" );
    if ( !body ) return;
    Dom.clear( body );
    Library.types.forEach( ( type ) => {
      const count = Library.counts( type.id ).total;
      const label = Dom.el( "input" , { class: "form-control form-control-sm" , attrs: { maxlength: "40" , "aria-label": I18n.get( "types.label" ) } } );
      label.value = type.label;
      label.addEventListener( "change" , () => this.save( type , { label: label.value.trim() } ) );
      const icon = Dom.el( "input" , { class: "form-control form-control-sm" , attrs: { maxlength: "40" , "aria-label": I18n.get( "types.icon" ) , placeholder: "film" } } );
      icon.value = type.icon || "";
      icon.addEventListener( "change" , () => this.save( type , { icon: icon.value.trim() } ) );
      const lookup = Dom.el( "select" , { class: "form-select form-select-sm" , attrs: { "aria-label": I18n.get( "types.lookup" ) } } );
      this.fillKinds( lookup , type.lookup );
      lookup.disabled = Boolean( type.builtin );
      lookup.addEventListener( "change" , () => this.save( type , { lookup: lookup.value } ) );
      const remove = type.builtin ? Dom.el( "span" ) : Dom.el( "button" , {
        class: "btn btn-sm btn-outline-danger",
        attrs: { type: "button" },
        children: [ Card.icon( "trash3" ) , Dom.el( "span" , { text: " " + I18n.get( "types.delete" ) } ) ],
        on: { click: () => this.remove( type , count ) },
      } );
      body.appendChild( Dom.el( "tr" , { children: [
        Dom.el( "td" , { children: [ Dom.el( "span" , { class: "fs-5" , children: [ Card.icon( Vocab.typeIcon( type.id ) ) ] } ) ] } ),
        Dom.el( "td" , { children: [ label ] } ),
        Dom.el( "td" , { children: [ icon ] } ),
        Dom.el( "td" , { children: [ lookup ] } ),
        Dom.el( "td" , { class: "text-body-secondary" , text: String( count ) } ),
        Dom.el( "td" , { children: [ remove ] } ),
      ] } ) );
    } );
  },

  async save( type , changes ) {
    const before = { id: type.id , label: type.label , icon: type.icon || "" , lookup: type.lookup };
    const after = Object.assign( {} , before , changes );
    try {
      await Undo.run( {
        label: I18n.fill( "undo.type_changed" , { name: after.label } ),
        do: async () => { await Api.saveType( after ); await Library.refresh(); },
        undo: async () => { await Api.saveType( before ); await Library.refresh(); },
      } );
    } catch ( error ) {
      Dom.toast( error.message , "error" );
    }
  },

  async create() {
    const label = Dom.get( "type-label" ).value.trim();
    if ( !label ) return;
    const id = label.toLowerCase().normalize( "NFKD" ).replace( /[^a-z0-9]+/g , "-" ).replace( /^-+|-+$/g , "" ).slice( 0 , 32 ) || "type";
    const type = { id: id , label: label , lookup: Dom.get( "type-lookup" ).value , icon: Dom.get( "type-icon" ).value.trim() };
    try {
      await Undo.run( {
        label: I18n.fill( "undo.type_added" , { name: label } ),
        toast: true,
        do: async () => { await Api.saveType( type ); await Library.refresh(); },
        undo: async () => { await Api.deleteType( id , null ); await Library.refresh(); },
      } );
      Dom.get( "type-form" ).reset();
      Undo.saved( Dom.get( "type-form" ) );
    } catch ( error ) {
      Dom.toast( error.message , "error" );
    }
  },

  async remove( type , count ) {
    let target = null;
    if ( count ) {
      const others = Library.types.filter( ( other ) => other.id !== type.id );
      const answer = window.prompt( I18n.fill( "types.move_prompt" , { n: count , name: type.label , choices: others.map( ( o ) => o.label ).join( ", " ) } ) , others[ 0 ].label );
      if ( answer == null ) return;
      const match = others.find( ( other ) => other.label.toLowerCase() === answer.trim().toLowerCase() );
      if ( !match ) { Dom.toast( I18n.get( "types.no_such" ) , "error" ); return; }
      target = match.id;
    }
    try {
      await Undo.run( {
        label: I18n.fill( "undo.type_deleted" , { name: type.label } ),
        toast: true,
        do: async () => { await Api.deleteType( type.id , target ); await Library.refresh(); },
        undo: async () => { await Api.restoreType( type.id ); await Library.refresh(); },
      } );
    } catch ( error ) {
      Dom.toast( error.message , "error" );
    }
  },
};
