// Saved views: a named query plus a card layout, one tap away -- "Pre-code,
// unwatched, best first", "Short ones for a weeknight". A row of pills above
// the library (gone while there are none); the toolbar's Save view keeps what
// is on screen now. Views are yours (on
// your account), and deleting one can be undone.
const ViewsBar = {
  screen: "library",

  render( screen ) {
    this.screen = screen;
    const bar = Dom.get( "views-bar" );
    Dom.clear( bar );
    const here = window.location.hash;
    Prefs.views.filter( ( view ) => view.screen === screen ).forEach( ( view ) => {
      const on = view.query === here;
      bar.appendChild( Dom.el( "div" , { class: "btn-group view-pill" , children: [
        Dom.el( "a" , {
          class: "btn btn-sm " + ( on ? "btn-soft-primary" : "btn-outline-secondary" ),
          attrs: { href: view.query , title: I18n.get( "views.open" ) },
          children: [ Card.icon( view.icon || "bookmark-star" ) , Dom.el( "span" , { text: " " + view.name } ) ],
          on: { click: () => { if ( view.card ) LibraryScreen.setCard( Object.assign( {} , Prefs.card( "library" ) , view.card ) , true ); } },
        } ),
        Dom.el( "button" , {
          class: "btn btn-sm dropdown-toggle dropdown-toggle-split " + ( on ? "btn-soft-primary" : "btn-outline-secondary" ),
          attrs: { type: "button" , "data-bs-toggle": "dropdown" , "aria-expanded": "false" , "aria-label": I18n.fill( "views.manage" , { name: view.name } ) },
        } ),
        Dom.el( "ul" , { class: "dropdown-menu" , children: [
          this.item( "views.update" , "arrow-repeat" , () => this.update( view ) ),
          this.item( "views.rename" , "pencil" , () => this.rename( view ) ),
          this.item( "views.delete" , "trash3" , () => this.remove( view ) ),
        ] } ),
      ] } ) );
    } );
  },

  item( key , icon , run ) {
    return Dom.el( "li" , { children: [ Dom.el( "button" , {
      class: "dropdown-item",
      attrs: { type: "button" },
      children: [ Card.icon( icon ) , Dom.el( "span" , { text: " " + I18n.get( key ) } ) ],
      on: { click: run },
    } ) ] } );
  },

  async save() {
    const name = window.prompt( I18n.get( "views.name_prompt" ) , LibraryScreen.placeLabel() );
    if ( !name || !name.trim() ) return;
    try {
      let created = null;
      await Undo.run( {
        label: I18n.fill( "undo.view_saved" , { name: name.trim() } ),
        toast: true,
        do: async () => {
          created = await Api.createView( { name: name.trim() , screen: "library" , scope: LibraryScreen.scope , query: window.location.hash , card: LibraryScreen.card } );
          await Prefs.reloadViews();
          this.render( this.screen );
        },
        undo: async () => {
          await Api.deleteView( created.id );
          await Prefs.reloadViews();
          this.render( this.screen );
        },
      } );
    } catch ( error ) {
      Dom.toast( error.message , "error" );
    }
  },

  async update( view ) {
    const before = { query: view.query , card: view.card , scope: view.scope };
    const after = { query: window.location.hash , card: LibraryScreen.card , scope: LibraryScreen.scope };
    await this.change( view , after , before , I18n.fill( "undo.view_updated" , { name: view.name } ) );
  },

  async rename( view ) {
    const name = window.prompt( I18n.get( "views.name_prompt" ) , view.name );
    if ( !name || !name.trim() || name.trim() === view.name ) return;
    await this.change( view , { name: name.trim() } , { name: view.name } , I18n.fill( "undo.view_renamed" , { name: name.trim() } ) );
  },

  async change( view , after , before , label ) {
    try {
      await Undo.run( {
        label: label,
        do: async () => { await Api.updateView( view.id , after ); await Prefs.reloadViews(); this.render( this.screen ); },
        undo: async () => { await Api.updateView( view.id , before ); await Prefs.reloadViews(); this.render( this.screen ); },
      } );
    } catch ( error ) {
      Dom.toast( error.message , "error" );
    }
  },

  async remove( view ) {
    try {
      await Undo.run( {
        label: I18n.fill( "undo.view_deleted" , { name: view.name } ),
        toast: true,
        do: async () => { await Api.deleteView( view.id ); await Prefs.reloadViews(); this.render( this.screen ); },
        undo: async () => { await Api.restoreView( view.id ); await Prefs.reloadViews(); this.render( this.screen ); },
      } );
    } catch ( error ) {
      Dom.toast( error.message , "error" );
    }
  },
};
