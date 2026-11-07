// Tiny DOM helpers, shared by every page. Kept in its own file so a new page
// can use them without loading the account/admin logic in app.js.
//
// The reason this exists at all rather than each page reaching for innerHTML:
// building elements through createElement + textContent means a display name
// containing "<script>" is rendered as those literal characters. Assembling
// the same row as an HTML string would execute it. There is no escaping
// helper here on purpose -- the safe path should be the only path.
const Dom = {
  get( id ) {
    return document.getElementById( id );
  },

  all( selector , root ) {
    return Array.from( ( root || document ).querySelectorAll( selector ) );
  },

  show( element , visible ) {
    if ( element ) element.hidden = !visible;
  },

  text( element , value ) {
    if ( element ) element.textContent = value == null ? "" : String( value );
  },

  clear( element ) {
    if ( element ) element.replaceChildren();
  },

  // el( "button", { class: "small", text: name, on: { click: fn } } )
  el( tag , options ) {
    const settings = options || {};
    const node = document.createElement( tag );
    if ( settings.class ) node.className = settings.class;
    if ( settings.text != null ) node.textContent = String( settings.text );
    if ( settings.attrs ) {
      Object.entries( settings.attrs ).forEach( function ( entry ) {
        if ( entry[ 1 ] != null ) node.setAttribute( entry[ 0 ] , entry[ 1 ] );
      } );
    }
    if ( settings.on ) {
      Object.entries( settings.on ).forEach( function ( entry ) {
        node.addEventListener( entry[ 0 ] , entry[ 1 ] );
      } );
    }
    ( settings.children || [] ).forEach( function ( child ) {
      node.appendChild( child );
    } );
    return node;
  },

  // Copy an element's text, with a selection fallback. The fallback is not
  // optional politeness: navigator.clipboard needs a secure context, so every
  // plain-http://localhost run lands there, and a copy button that silently
  // does nothing is worse than no button. Used for both login links and API
  // keys, which are exactly the strings nobody wants to retype by hand.
  async copy( source ) {
    const value = source ? source.textContent : "";
    try {
      await navigator.clipboard.writeText( value );
      this.toast( I18n.get( "ui.copied" ) , "ok" );
    } catch ( error ) {
      const range = document.createRange();
      range.selectNodeContents( source );
      const selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange( range );
    }
  },

  // Briefly reveal a confirmation ("Saved.", "Copied.") without leaving it on
  // screen forever.
  flash( element , milliseconds ) {
    if ( !element ) return;
    element.hidden = false;
    window.clearTimeout( element._flashTimer );
    element._flashTimer = window.setTimeout( function () {
      element.hidden = true;
    } , milliseconds || 2000 );
  },

  // A short status line pinned to the bottom of the screen ("Saved.",
  // "Copied."), for confirmations that need no place of their own on the
  // page. kind is "ok" or "error". An empty message shows nothing, so a
  // language.yaml key set to "" switches that toast off.
  //
  // action is an optional { text , run }: a button on the toast ("Undo").
  // A toast with one stays up twice as long, since reaching for it takes
  // longer than reading it.
  //
  // The hiding is timed here rather than by Bootstrap, whose delay is fixed
  // when the instance is made; replacing the instance to change it breaks a
  // toast that is still fading out. The timer stops while the pointer or the
  // focus is on the toast, so it never disappears under someone aiming at it.
  toast( message , kind , action ) {
    const banner = this.get( "toast" );
    if ( !banner || !message ) return;
    banner.className = "toast border-0 " + ( kind === "error" ? "text-bg-danger" : "text-bg-success" );
    this.text( this.get( "toast-text" ) , message );
    const button = this.get( "toast-action" );
    Dom.show( button , Boolean( action ) );
    if ( action ) {
      this.text( button , action.text );
      // The button goes, the toast stays: what the action does next ("Undone:
      // ...", or an error) takes its place. Hiding it here would swallow that
      // next toast, which arrives while this one is still fading out.
      button.onclick = function () {
        Dom.show( button , false );
        action.run();
      };
    }
    const instance = bootstrap.Toast.getOrCreateInstance( banner , { autohide: false } );
    const schedule = function () {
      window.clearTimeout( banner._hideTimer );
      banner._hideTimer = window.setTimeout( function () { instance.hide(); } , banner._delay );
    };
    if ( !banner._wired ) {
      banner._wired = true;
      const hold = function () { window.clearTimeout( banner._hideTimer ); };
      const release = function () {
        if ( !banner.matches( ":hover" ) && !banner.contains( document.activeElement ) ) schedule();
      };
      banner.addEventListener( "mouseenter" , hold );
      banner.addEventListener( "focusin" , hold );
      banner.addEventListener( "mouseleave" , release );
      banner.addEventListener( "focusout" , () => window.setTimeout( release ) );
    }
    banner._delay = action ? 8000 : 4000;
    instance.show();
    schedule();
  },

  // A status pill for a table cell. tone is a Bootstrap colour name:
  // "success", "secondary", "warning", "danger".
  badge( text , tone ) {
    return this.el( "span" , { class: "badge text-bg-" + ( tone || "secondary" ) , text: text } );
  },
};
