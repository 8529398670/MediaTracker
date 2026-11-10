// Customize cards, on Appearance > Cards: choose what each card shows and
// which buttons it carries, put them in order, pick a layout and a size --
// with a live preview. The library and Discover each have their own
// settings (the switch at the top picks which). Saved on the account per
// screen (Prefs.setCard), so the phone and the laptop match. Each change is
// an undo step (quick runs of changes fold into one); the library's layout
// buttons change the same settings, so both always agree.
const Customizer = {
  screen: "library",

  show( screen ) {
    if ( screen ) this.screen = screen;
    this.refresh();
  },

  owner() {
    return this.screen === "discover" ? DiscoverScreen : LibraryScreen;
  },

  // The screen's live settings; read from the account if it has not
  // started yet.
  current() {
    return this.owner().card || Prefs.card( this.screen );
  },

  apply( card ) {
    this.owner().setCard( card );
  },

  refresh() {
    if ( !Dom.get( "customize-fields" ) ) return;
    Dom.all( "[data-customize-screen]" ).forEach( ( button ) => {
      const on = button.getAttribute( "data-customize-screen" ) === this.screen;
      button.classList.toggle( "btn-soft-primary" , on );
      button.classList.toggle( "btn-outline-secondary" , !on );
      button.setAttribute( "aria-pressed" , String( on ) );
    } );
    const card = this.current();
    this.renderChoices( Dom.get( "customize-fields" ) , "fields" , Object.keys( Vocab.FIELDS ) , card );
    this.renderChoices( Dom.get( "customize-buttons" ) , "buttons" , Vocab.SCREEN_BUTTONS[ this.screen ] , card );
    this.renderSegmented( Dom.get( "customize-layout" ) , "layout" , Vocab.LAYOUTS , card );
    this.renderSegmented( Dom.get( "customize-size" ) , "size" , Vocab.SIZES , card );
    this.renderPreview( card );
  },

  renderSegmented( box , name , values , card ) {
    Dom.clear( box );
    values.forEach( ( value ) => {
      const on = card[ name ] === value;
      box.appendChild( Dom.el( "button" , {
        class: "btn btn-sm " + ( on ? "btn-soft-primary" : "btn-outline-secondary" ),
        text: I18n.get( "customize." + name + "_" + value ),
        attrs: { type: "button" , "aria-pressed": String( on ) },
        on: { click: () => { const next = this.copy( card ); next[ name ] = value; this.apply( next ); } },
      } ) );
    } );
  },

  copy( card ) {
    return JSON.parse( JSON.stringify( card ) );
  },

  // Chosen ones first, in their order, then the rest; each with a checkbox
  // and up/down buttons (which work on a phone, unlike dragging).
  renderChoices( box , name , all , card ) {
    Dom.clear( box );
    const chosen = card[ name ];
    const rest = all.filter( ( id ) => chosen.indexOf( id ) < 0 );
    chosen.concat( rest ).forEach( ( id ) => {
      const on = chosen.indexOf( id ) >= 0;
      const at = chosen.indexOf( id );
      const def = ( name === "fields" ? Vocab.FIELDS : Vocab.BUTTONS )[ id ];
      const check = Dom.el( "input" , { class: "form-check-input" , attrs: { type: "checkbox" , id: "choice-" + name + "-" + id } } );
      check.checked = on;
      check.addEventListener( "change" , () => {
        const next = this.copy( card );
        next[ name ] = check.checked ? next[ name ].concat( [ id ] ) : next[ name ].filter( ( each ) => each !== id );
        this.apply( next );
      } );
      const mover = ( direction , icon ) => Dom.el( "button" , {
        class: "btn btn-sm btn-outline-secondary",
        attrs: { type: "button" , "aria-label": I18n.get( "customize.move_" + direction ) , title: I18n.get( "customize.move_" + direction ) },
        children: [ Card.icon( icon ) ],
        on: { click: () => {
          const next = this.copy( card );
          const list = next[ name ];
          const to = direction === "up" ? at - 1 : at + 1;
          if ( to < 0 || to >= list.length ) return;
          list.splice( to , 0 , list.splice( at , 1 )[ 0 ] );
          this.apply( next );
        } },
      } );
      const label = I18n.get( ( name === "fields" ? "card.field_" : "card.button_" ) + id );
      const help = I18n.get( ( name === "fields" ? "card.field_help_" : "card.button_help_" ) + id );
      box.appendChild( Dom.el( "li" , { class: "list-group-item choice" + ( on ? "" : " is-off" ) , children: [
        Dom.el( "div" , { class: "form-check mb-0 flex-grow-1" , children: [
          check,
          Dom.el( "label" , { class: "form-check-label" , attrs: { for: "choice-" + name + "-" + id } , children: [
            Card.icon( def.icon ),
            Dom.el( "span" , { text: " " + label } ),
            help ? Dom.el( "small" , { class: "d-block text-body-secondary" , text: help } ) : Dom.el( "span" ),
          ] } ),
        ] } ),
        on ? Dom.el( "div" , { class: "btn-group" , children: [ mover( "up" , "arrow-up" ) , mover( "down" , "arrow-down" ) ] } ) : Dom.el( "span" ),
      ] } ) );
    } );
  },

  // A real card from what is on screen now, drawn with the chosen settings.
  renderPreview( card ) {
    const box = Dom.get( "customize-preview" );
    Dom.clear( box );
    const owner = this.owner();
    const rows = owner.result && owner.result.rows && owner.result.rows.length ? owner.result.rows : Array.from( Library.rows.values() );
    const sample = rows.find( ( row ) => row.t.poster && row.score && ( row.t.genres || [] ).length ) || rows[ 0 ];
    if ( !sample ) return;
    const grid = Dom.el( "div" , { class: "media-grid layout-" + card.layout + " size-" + card.size + " is-preview" } );
    grid.appendChild( Card.build( sample , card , { expanded: true } ) );
    box.appendChild( grid );
  },

  reset() {
    this.apply( JSON.parse( JSON.stringify( this.screen === "discover" ? Vocab.DEFAULT_DISCOVER_CARD : Vocab.DEFAULT_CARD ) ) );
  },
};

document.addEventListener( "DOMContentLoaded" , () => {
  Dom.all( "[data-customize-screen]" ).forEach( ( button ) => button.addEventListener( "click" , () => Customizer.show( button.getAttribute( "data-customize-screen" ) ) ) );
  const reset = Dom.get( "customize-reset" );
  if ( reset ) reset.addEventListener( "click" , () => Customizer.reset() );
  // The preview is a picture of a card; its buttons do nothing.
  const preview = Dom.get( "customize-preview" );
  if ( preview ) preview.addEventListener( "click" , ( event ) => { event.preventDefault(); event.stopPropagation(); } , true );
} );
