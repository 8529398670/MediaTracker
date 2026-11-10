// Putting things in order by dragging: a playlist's titles, and the
// playlists themselves. Drop a row where it belongs and it takes that
// number; everything between shifts by one.
//
// The screen says what the order is and what a move does:
//
//   OrderDrag.enable( node , { id , ids: () => [ ... ] , move: ( id , position ) => ... } );
//
// Positions are 1-based, as shown on screen. Drag is the mouse's way; the
// number box and the Move menu are the keyboard's and the phone's.
const OrderDrag = {
  dragging: null,
  group: null,

  // Where a drop lands, as the number the moving one will have: dropped
  // before or after target, counted once the moving one is out of the list.
  position( ids , moving , target , after ) {
    const rest = ids.filter( ( id ) => id !== moving );
    const at = rest.indexOf( target );
    if ( at < 0 ) return rest.length + 1;
    return at + ( after ? 1 : 0 ) + 1;
  },

  enable( node , options ) {
    const id = options.id;
    node.setAttribute( "draggable" , "true" );
    node.addEventListener( "dragstart" , ( event ) => {
      // A drag that starts in a text box selects text instead.
      if ( event.target.closest && event.target.closest( "input" ) ) { event.preventDefault(); return; }
      this.dragging = id;
      this.group = options;
      node.classList.add( "is-dragging" );
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData( "text/plain" , String( id ) );
    } );
    node.addEventListener( "dragend" , () => {
      node.classList.remove( "is-dragging" );
      this.dragging = null;
      Dom.all( ".drop-before, .drop-after" ).forEach( ( other ) => other.classList.remove( "drop-before" , "drop-after" ) );
    } );
    node.addEventListener( "dragover" , ( event ) => {
      if ( this.dragging === null || this.dragging === id || this.group.ids !== options.ids ) return;
      event.preventDefault();
      const after = this.isAfter( node , event );
      node.classList.toggle( "drop-before" , !after );
      node.classList.toggle( "drop-after" , after );
    } );
    node.addEventListener( "dragleave" , () => node.classList.remove( "drop-before" , "drop-after" ) );
    node.addEventListener( "drop" , ( event ) => {
      event.preventDefault();
      node.classList.remove( "drop-before" , "drop-after" );
      const moving = this.dragging;
      this.dragging = null;
      if ( moving === null || moving === id || this.group.ids !== options.ids ) return;
      const ids = options.ids();
      const position = this.position( ids , moving , id , this.isAfter( node , event ) );
      if ( position !== ids.indexOf( moving ) + 1 ) options.move( moving , position );
    } );
  },

  // In a row of tiles "after" is the right half; in a list, the lower half.
  isAfter( node , event ) {
    const box = node.getBoundingClientRect();
    const holder = node.parentElement;
    // A tile in a Bootstrap column (the playlists index): across while the
    // columns sit side by side, down once they stack into one on a phone.
    const across = holder && holder.classList.contains( "col" ) && holder.parentElement
      ? holder.getBoundingClientRect().width < holder.parentElement.getBoundingClientRect().width * 0.9
      : holder && getComputedStyle( holder ).flexDirection === "row";
    return across ? event.clientX > box.left + box.width / 2 : event.clientY > box.top + box.height / 2;
  },

  // Top / up one / down one / bottom, for whoever cannot drag.
  menu( id , options ) {
    const go = ( where ) => {
      const ids = options.ids();
      const now = ids.indexOf( id ) + 1;
      const to = { top: 1 , up: now - 1 , down: now + 1 , bottom: ids.length }[ where ];
      if ( to >= 1 && to <= ids.length && to !== now ) options.move( id , to );
    };
    const item = ( key , icon ) => Dom.el( "li" , { children: [ Dom.el( "button" , {
      class: "dropdown-item",
      attrs: { type: "button" },
      children: [ Card.icon( icon ) , Dom.el( "span" , { text: " " + I18n.get( "playlist." + key ) } ) ],
      on: { click: () => go( key ) },
    } ) ] } );
    return Dom.el( "div" , { class: "dropdown" , children: [
      Dom.el( "button" , {
        class: "btn btn-sm btn-outline-secondary",
        attrs: { type: "button" , "data-bs-toggle": "dropdown" , "aria-expanded": "false" , title: I18n.get( "playlist.move" ) , "aria-label": I18n.get( "playlist.move" ) },
        children: [ Card.icon( "arrow-down-up" ) ],
      } ),
      Dom.el( "ul" , { class: "dropdown-menu" , children: [
        item( "top" , "chevron-double-up" ),
        item( "up" , "chevron-up" ),
        item( "down" , "chevron-down" ),
        item( "bottom" , "chevron-double-down" ),
      ] } ),
    ] } );
  },
};
