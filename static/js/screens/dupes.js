// Duplicates: the same work added twice under two names ("Sunrise" and
// "Sunrise: A Song of Two Humans"). For each group, keep one: everything the
// others knew -- tags, links, notes, everyone's watched and ratings -- is
// folded into it, and the merge is one undo step. "Not duplicates" is
// remembered for the whole family.
const DupesScreen = {
  init() {
    Dom.show( Dom.get( "dupes-panel" ) , true );
    window.addEventListener( "hashchange" , () => { if ( Nav.screen() === "dupes" ) this.load(); } );
    if ( Nav.screen() === "dupes" ) this.load();
  },

  async load() {
    const box = Dom.get( "dupes-list" );
    Dom.text( Dom.get( "dupes-summary" ) , I18n.get( "dupes.looking" ) );
    try {
      const data = await Api.request( "/api/dupes" );
      this.render( data.groups );
    } catch ( error ) {
      Dom.toast( error.message , "error" );
    }
  },

  render( groups ) {
    const box = Dom.get( "dupes-list" );
    Dom.clear( box );
    Dom.text( Dom.get( "dupes-summary" ) , I18n.fill( groups.length ? "dupes.found" : "dupes.none" , { n: groups.length } ) );
    groups.forEach( ( group ) => {
      const list = Dom.el( "div" , { class: "dupe-titles" } );
      group.titles.forEach( ( title ) => {
        const row = Library.get( title.id );
        list.appendChild( Dom.el( "div" , { class: "dupe-title" , children: [
          title.poster_url && row && row.t.poster ? Dom.el( "img" , { class: "add-poster" , attrs: { src: row.t.poster , alt: "" , loading: "lazy" } } ) : Dom.el( "div" , { class: "add-poster is-empty" , children: [ Card.icon( Vocab.typeIcon( title.type ) ) ] } ),
          Dom.el( "div" , { class: "flex-grow-1 min-w-0" , children: [
            Dom.el( "div" , { class: "fw-semibold" , text: title.title + ( title.year ? " (" + title.year + ")" : "" ) } ),
            Dom.el( "div" , { class: "small text-body-secondary" , text: [ Vocab.typeLabel( title.type ) , title.creator , Vocab.date( title.added_at ) ].filter( Boolean ).join( " · " ) } ),
            Dom.el( "button" , { class: "btn btn-sm btn-success mt-1" , attrs: { type: "button" } , children: [ Card.icon( "check2" ) , Dom.el( "span" , { text: " " + I18n.get( "dupes.keep" ) } ) ] , on: { click: () => this.merge( title , group ) } } ),
          ] } ),
        ] } ) );
      } );
      box.appendChild( Dom.el( "div" , { class: "list-group-item" , children: [
        Dom.el( "div" , { class: "small text-body-secondary mb-2" , text: I18n.get( "dupes.why_" + group.why ) || group.why } ),
        list,
        Dom.el( "button" , { class: "btn btn-sm btn-outline-secondary mt-2" , text: I18n.get( "dupes.not_dupes" ) , attrs: { type: "button" } , on: { click: () => this.dismiss( group ) } } ),
      ] } ) );
    } );
  },

  async merge( keep , group ) {
    const drop = group.ids.filter( ( id ) => id !== keep.id );
    let result = null;
    try {
      await Undo.run( {
        label: I18n.fill( "undo.merged" , { title: keep.title , n: drop.length } ),
        toast: true,
        do: async () => {
          result = await Api.post( "/api/titles/" + Api.id( keep.id ) + "/merge" , { drop_ids: drop } );
          await Library.refresh();
          await this.load();
        },
        undo: async () => {
          await Api.post( "/api/merges/" + Api.id( result.merge_id ) + "/undo" );
          await Library.load();
          await this.load();
        },
      } );
    } catch ( error ) {
      Dom.toast( error.message , "error" );
    }
  },

  async dismiss( group ) {
    let pairs = [];
    try {
      await Undo.run( {
        label: I18n.get( "undo.not_dupes" ),
        toast: true,
        do: async () => { pairs = ( await Api.post( "/api/dupes/dismiss" , { ids: group.ids } ) ).pairs; await this.load(); },
        undo: async () => { await Api.post( "/api/dupes/undismiss" , { pairs: pairs } ); await this.load(); },
      } );
    } catch ( error ) {
      Dom.toast( error.message , "error" );
    }
  },
};
