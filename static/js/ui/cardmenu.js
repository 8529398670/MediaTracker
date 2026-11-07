// Right-click (or long-press) on a card: its everyday buttons in a menu at
// the pointer, so Watched, Love, Skip or the parents guide is one click away
// without opening Details. One menu at a time, built fresh each time from the
// row, so what it shows is always the title's current state.
//
// On a library card Skip means "not for me" (status dropped); on a Discover
// film it is Discover's own Skip, which hides the film just for you.
const CardMenu = {
  LIBRARY: [ "watched" , "love" , "skip" , "-" , "parents" , "justwatch" , "wiki" , "imdb" , "-" , "edit" ],
  DISCOVER: [ "add" , "seen" , "skip" , "-" , "parents" , "justwatch" , "wiki" , "imdb" ],

  node: null,

  // options: { row( id ) , ids( row ) , run( id , row ) , skip() } -- skip()
  // true leaves the browser's own menu alone (while selecting, say).
  wire( container , options ) {
    container.addEventListener( "contextmenu" , ( event ) => {
      const article = event.target.closest( ".media-card" );
      if ( !article || ( options.skip && options.skip() ) ) return;
      const row = options.row( article.getAttribute( "data-id" ) );
      if ( !row || row.t.deleted_at ) return;
      event.preventDefault();
      this.open( event.clientX , event.clientY , options.ids( row ) , row , options.run );
    } );
  },

  // Library Skip shows as on when the title is "not for me".
  active( id , row ) {
    if ( id === "skip" && !row.discover ) return Card.active( "drop" , row );
    return Card.active( id , row );
  },

  label( id , row ) {
    if ( id === "skip" ) return I18n.get( this.active( id , row ) ? "card.button_skipped" : "card.button_skip" );
    if ( id === "edit" ) return I18n.get( "card.menu_details" );
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
