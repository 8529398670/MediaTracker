// Right-click (or long-press) on a card: its buttons in a menu at the
// pointer, so they are one click away without expanding the card or
// opening Details. One menu at a time, built fresh each time from the
// row, so what it shows is always the title's current state.
//
// On a library card Skip means "not for me" (status dropped); on a Discover
// film it is Discover's own Skip, which hides the film just for you.
//
// It lists the same buttons, in the same order, as clicking the card does:
// each person's choice per screen (Appearance > Cards, the card's buttons),
// read on every open. Rate and Playlist are left out -- each is a dropdown
// that needs a value, which a menu item cannot ask for -- and a library
// menu always ends with Details.
const CardMenu = {
  // Need a value, so they only work as the card's own dropdowns.
  NOT_IN_MENU: [ "rate" , "playlist" ],

  ids( card , details ) {
    const ids = card.buttons.filter( ( id ) => this.NOT_IN_MENU.indexOf( id ) < 0 );
    if ( details && ids.indexOf( "edit" ) < 0 ) ids.push( "-" , "edit" );
    return ids;
  },

  library() {
    return this.ids( LibraryScreen.card || Prefs.card( "library" ) , true );
  },

  discover() {
    return this.ids( DiscoverScreen.card || Prefs.card( "discover" ) , false );
  },

  // A Discover film found from the library's search: Add to library first,
  // whatever the person chose for the Discover card, then the rest.
  discoverExtras() {
    return [ "add" ].concat( this.discover().filter( ( id ) => id !== "add" ) );
  },

  node: null,

  // How long a finger rests on a card before its menu opens, and how far it
  // may drift (px) before that counts as a scroll instead.
  PRESS_MS: 500,
  PRESS_SLOP: 10,

  // options: { row( id ) , ids( row ) , run( id , row ) , skip() } -- skip()
  // true leaves the browser's own menu alone (while selecting, say).
  wire( container , options ) {
    // The card's row, or null when this card has no menu right now.
    const target = ( node ) => {
      const article = node.closest( ".media-card" );
      if ( !article || ( options.skip && options.skip() ) ) return null;
      const row = options.row( article.getAttribute( "data-id" ) );
      return row && !row.t.deleted_at ? row : null;
    };
    // What a menu item does, held still on its card (Dom.steady): the card,
    // or the one drawn in its place, stays where it was on screen.
    const steadyRun = ( node ) => {
      const article = node.closest( ".media-card" );
      return ( id , row ) => Dom.steady( article , () => options.run( id , row ) );
    };
    let pressedAt = 0;
    container.addEventListener( "contextmenu" , ( event ) => {
      // Android fires this too at the end of a long press: already open.
      if ( Date.now() - pressedAt < 1500 ) { event.preventDefault(); return; }
      const row = target( event.target );
      if ( !row ) return;
      event.preventDefault();
      this.open( event.clientX , event.clientY , options.ids( row ) , row , steadyRun( event.target ) );
    } );
    // A long press opens the same menu on a phone, where iOS never sends
    // contextmenu. The tap that ends it must not also press what was under
    // the finger, so the next click is swallowed.
    let timer = null;
    let start = null;
    const cancel = () => {
      clearTimeout( timer );
      timer = null;
      start = null;
    };
    container.addEventListener( "pointerdown" , ( event ) => {
      cancel();
      if ( event.pointerType !== "touch" || !event.isPrimary ) return;
      if ( event.target.closest( "input, textarea, select, [contenteditable]" ) ) return;
      if ( !target( event.target ) ) return;
      start = { x: event.clientX , y: event.clientY , node: event.target };
      timer = setTimeout( () => {
        const at = start;
        cancel();
        const row = at && target( at.node );
        if ( !row ) return;
        pressedAt = Date.now();
        this.swallowClick();
        if ( navigator.vibrate ) navigator.vibrate( 10 );
        this.open( at.x , at.y , options.ids( row ) , row , steadyRun( at.node ) );
      } , this.PRESS_MS );
    } );
    container.addEventListener( "pointermove" , ( event ) => {
      if ( !start ) return;
      if ( Math.abs( event.clientX - start.x ) > this.PRESS_SLOP || Math.abs( event.clientY - start.y ) > this.PRESS_SLOP ) cancel();
    } );
    [ "pointerup" , "pointercancel" , "pointerleave" ].forEach( ( type ) => container.addEventListener( type , cancel ) );
    window.addEventListener( "scroll" , cancel , { capture: true , passive: true } );
  },

  // Eats the one click that follows a long press, before any card handler.
  swallowClick() {
    const eat = ( event ) => {
      event.preventDefault();
      event.stopPropagation();
      event.stopImmediatePropagation();
    };
    document.addEventListener( "click" , eat , { capture: true , once: true } );
    // The click (if any) comes just after the finger lifts; none comes when
    // it lifts somewhere else, so the trap is taken down soon after.
    const lift = () => setTimeout( () => document.removeEventListener( "click" , eat , { capture: true } ) , 400 );
    document.addEventListener( "pointerup" , lift , { capture: true , once: true } );
    document.addEventListener( "pointercancel" , lift , { capture: true , once: true } );
  },

  // Library Skip (an old name for Not for me) shows as on when dropped.
  active( id , row ) {
    if ( id === "skip" && !row.discover ) return Card.active( "drop" , row );
    return Card.active( id , row );
  },

  label( id , row ) {
    if ( id === "skip" ) return I18n.get( this.active( id , row ) ? "card.button_skipped" : "card.button_skip" );
    if ( id === "edit" ) return I18n.get( "card.menu_details" );
    if ( id === "add" && row.discover && !row.inLibrary ) return I18n.get( "card.menu_add" );
    return Card.label( id , row );
  },

  item( id , row , run ) {
    const def = Vocab.BUTTONS[ id ];
    if ( !def ) return null;
    const on = this.active( id , row );
    const children = [ Card.icon( on && def.activeIcon ? def.activeIcon : def.icon ) , Dom.el( "span" , { class: "flex-grow-1" , text: this.label( id , row ) } ) ];
    if ( on && !def.activeIcon ) children.push( Card.icon( "check2" ) );
    if ( def.kind === "link" ) {
      const href = Vocab.href( id , row.t );
      if ( !href ) return null;
      return Dom.el( "a" , {
        class: "dropdown-item" , children: children,
        attrs: { href: href , target: Vocab.target( href ) , rel: "noopener noreferrer" , role: "menuitem" },
        on: { click: () => this.close() },
      } );
    }
    const attrs = { type: "button" , role: "menuitem" };
    if ( def.kind === "state" || id === "skip" || id === "seen" ) attrs[ "aria-pressed" ] = String( on );
    return Dom.el( "button" , {
      class: "dropdown-item" , children: children , attrs: attrs,
      on: { click: () => { this.close(); run( id , row ); } },
    } );
  },

  open( x , y , ids , row , run ) {
    this.close();
    const menu = Dom.el( "div" , { class: "dropdown-menu show card-menu" , attrs: { role: "menu" , "aria-label": row.t.title } } );
    menu.appendChild( Dom.el( "h6" , { class: "dropdown-header text-truncate" , text: row.t.title } ) );
    let pendingDivider = false;
    ids.forEach( ( id ) => {
      if ( id === "-" ) { pendingDivider = true; return; }
      const node = this.item( id , row , run );
      if ( !node ) return;
      if ( pendingDivider ) menu.appendChild( Dom.el( "hr" , { class: "dropdown-divider" } ) );
      pendingDivider = false;
      menu.appendChild( node );
    } );
    document.body.appendChild( menu );
    // Kept on screen: flipped left or up when the pointer is near an edge.
    const margin = 8;
    const width = menu.offsetWidth;
    const height = menu.offsetHeight;
    const left = x + width + margin > window.innerWidth ? Math.max( margin , x - width ) : x;
    const top = y + height + margin > window.innerHeight ? Math.max( margin , y - height ) : y;
    menu.style.left = left + "px";
    menu.style.top = top + "px";
    this.node = menu;
    this.listen( true );
    const first = menu.querySelector( ".dropdown-item" );
    if ( first ) first.focus( { preventScroll: true } );
  },

  close() {
    if ( !this.node ) return;
    this.node.remove();
    this.node = null;
    this.listen( false );
  },

  listen( on ) {
    const method = on ? "addEventListener" : "removeEventListener";
    document[ method ]( "pointerdown" , this.onPointer , true );
    document[ method ]( "keydown" , this.onKey , true );
    window[ method ]( "scroll" , this.onAway , true );
    window[ method ]( "resize" , this.onAway );
    window[ method ]( "blur" , this.onAway );
    window[ method ]( "hashchange" , this.onAway );
  },

  onPointer( event ) {
    if ( CardMenu.node && !CardMenu.node.contains( event.target ) ) CardMenu.close();
  },

  onAway() {
    CardMenu.close();
  },

  onKey( event ) {
    const menu = CardMenu.node;
    if ( !menu ) return;
    if ( event.key === "Escape" ) {
      event.preventDefault();
      event.stopPropagation();
      CardMenu.close();
      return;
    }
    if ( event.key !== "ArrowDown" && event.key !== "ArrowUp" ) return;
    event.preventDefault();
    const items = Dom.all( ".dropdown-item" , menu );
    const at = items.indexOf( document.activeElement );
    const step = event.key === "ArrowDown" ? 1 : -1;
    items[ ( at + step + items.length ) % items.length ].focus();
  },
};
