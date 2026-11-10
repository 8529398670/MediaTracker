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
  //
  // A button's click goes through press, so one whose handler is async shows
  // that it is working with nothing more said.
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
      Object.entries( settings.on ).forEach( ( entry ) => {
        const pressed = tag === "button" && entry[ 0 ] === "click";
        node.addEventListener( entry[ 0 ] , pressed ? this.press( node , entry[ 1 ] ) : entry[ 1 ] );
      } );
    }
    ( settings.children || [] ).forEach( function ( child ) {
      node.appendChild( child );
    } );
    return node;
  },

  // A click listener for button. A handler that answers a promise keeps the
  // button busy until it settles; one that does not is simply run. Dom.el uses
  // this for every button it makes, and a button in the page's HTML gets it
  // with Dom.onPress. A question the handler asks counts as part of the wait, so
  // the press cannot be repeated behind it; style.css hides the spinner meanwhile.
  //
  // Every press also goes through Dom.steady, so whatever the handler redraws,
  // the button (or what took its place) stays where it was on screen. A button
  // that is meant to take the reader somewhere else has data-scroll="free".
  press( button , handler ) {
    return ( event ) => {
      if ( button.getAttribute( "aria-busy" ) === "true" ) return;
      const result = button.getAttribute( "data-scroll" ) === "free"
        ? handler( event )
        : this.steady( button , () => handler( event ) );
      if ( result && typeof result.then === "function" ) {
        // A button in a row's menu is out of sight by now, so the menu's own
        // button shows the work as well.
        this.busy( button , () => this.busy( this.menuButton( button ) , () => result ) );
      }
    };
  },

  // The button that opens the menu this one is in, if it is in one.
  menuButton( button ) {
    const menu = button.closest( ".dropdown-menu" );
    return menu ? menu.parentElement.querySelector( ".row-menu-toggle" ) : null;
  },

  onPress( button , handler ) {
    button.addEventListener( "click" , this.press( button , handler ) );
  },

  // Nothing moves under the reader. Runs work (sync, or answering a promise)
  // and then scrolls the window so anchor sits where it sat before: the page
  // may have grown, shrunk or been redrawn above it, and none of that should
  // look like a jump. If anchor was redrawn, the nearest thing still there is
  // used: anchor itself, else the closest of its old ancestors that is still
  // showing or was redrawn under the same id or data-key. So a row that gets
  // redrawn should carry a data-key, and its buttons keep their place too.
  //
  // It stands back when the reader scrolled meanwhile, or the screen changed:
  // both are somewhere they chose to go. A dev build says in the console when
  // it had to correct, which means the work moved the page and is worth fixing
  // at its source (Dom.swap, updating in place) rather than leaning on this.
  steady( anchor , work ) {
    const spot = this.spotOf( anchor );
    const done = () => {
      this.settle( spot );
      window.requestAnimationFrame( () => this.settle( spot ) );
    };
    let result;
    try {
      result = work();
    } catch ( error ) {
      done();
      throw error;
    }
    if ( result && typeof result.then === "function" ) return Promise.resolve( result ).finally( done );
    done();
    return result;
  },

  // Where anchor and each of its ancestors sit on screen now, for settle.
  spotOf( anchor ) {
    if ( !anchor || !anchor.isConnected ) return null;
    const chain = [];
    for ( let node = anchor ; node && node !== document.body ; node = node.parentElement ) {
      if ( node.getClientRects().length === 0 ) continue;
      const key = node.id ? "#" + CSS.escape( node.id )
        : node.getAttribute( "data-key" ) ? "[data-key=\"" + CSS.escape( node.getAttribute( "data-key" ) ) + "\"]" : "";
      chain.push( { node , key , top: node.getBoundingClientRect().top } );
    }
    if ( chain.length === 0 ) return null;
    const view = anchor.closest( ".view" );
    return {
      chain,
      hash: window.location.hash,
      view: view && view.classList.contains( "view-active" ) ? view : null,
      scrolled: Dom.scrollIntent,
    };
  },

  settle( spot ) {
    this.shrinkRunway();
    if ( !spot || spot.scrolled !== Dom.scrollIntent || spot.hash !== window.location.hash ) return;
    if ( spot.view && !spot.view.classList.contains( "view-active" ) ) return;
    const showing = ( node ) => Boolean( node ) && node.isConnected && node.getClientRects().length > 0;
    let target = null;
    let before = 0;
    for ( const link of spot.chain ) {
      const node = showing( link.node ) ? link.node : link.key ? document.querySelector( link.key ) : null;
      if ( showing( node ) ) {
        [ target , before ] = [ node , link.top ];
        break;
      }
    }
    if ( !target ) return;
    const moved = target.getBoundingClientRect().top - before;
    if ( Math.abs( moved ) < 1 ) return;
    const room = document.documentElement.scrollHeight - window.innerHeight;
    if ( window.scrollY + moved > room ) this.runway( window.scrollY + moved - room );
    window.scrollBy( { top: moved , behavior: "instant" } );
    if ( Math.abs( moved ) > 2 && typeof Fresh !== "undefined" && Fresh.version === "dev" ) {
      const name = target.id ? "#" + target.id : target.tagName.toLowerCase() + ( target.className ? "." + String( target.className ).trim().split( /\s+/ ).join( "." ) : "" );
      console.warn( "[steady] " + name + " moved " + Math.round( moved ) + "px; kept in place" );
    }
  },

  // Brings element into view because the reader asked for it (a box they
  // opened, the error banner), and tells Dom.steady this move is meant.
  // The one way to scroll after an action: never scrollIntoView directly.
  reveal( element , block = "nearest" ) {
    if ( !element ) return;
    this.movedOnPurpose();
    element.scrollIntoView( { block: block } );
  },

  movedOnPurpose() {
    Dom.scrollIntent += 1;
  },

  // A list filtered down to a few rows can leave the page too short to stay
  // where the reader was, and the browser would pull it up. So, as a word
  // processor does, the page gets blank room at its foot, given back as the
  // reader scrolls up or the content grows into it.
  runway( needed ) {
    let pad = this.get( "steady-runway" );
    if ( !pad ) {
      pad = this.el( "div" , { attrs: { id: "steady-runway" , "aria-hidden": "true" } } );
      document.body.appendChild( pad );
      window.addEventListener( "scroll" , () => this.shrinkRunway() , { passive: true } );
    }
    pad.style.height = Math.ceil( pad.offsetHeight + needed ) + "px";
  },

  shrinkRunway() {
    const pad = this.get( "steady-runway" );
    if ( !pad || pad.offsetHeight === 0 ) return;
    const content = document.documentElement.scrollHeight - pad.offsetHeight;
    const need = Math.max( 0 , Math.ceil( window.scrollY + window.innerHeight - content ) );
    if ( need < pad.offsetHeight ) pad.style.height = need + "px";
  },

  // Puts nodes in holder in one step, in place of what it held, so the page
  // is never painted with the holder empty (which would pull the scroll
  // position up with it). Build the new content first, awaiting whatever it
  // needs, and then swap: never clear a holder and fill it after an await.
  swap( holder , ...nodes ) {
    if ( holder ) holder.replaceChildren( ...nodes.filter( Boolean ) );
  },

  // Holds element at its current height until release() is called, for a
  // holder that has to sit empty while it waits. Prefer building elsewhere
  // and swapping.
  hold( element ) {
    if ( !element ) return () => {};
    const before = element.style.minHeight;
    element.style.minHeight = element.offsetHeight + "px";
    return () => { element.style.minHeight = before; };
  },

  // Runs work with button showing that it is busy: it cannot be pressed, so a
  // second click cannot send the same thing twice, and it has a spinner, so a
  // slow answer does not look like a press that did nothing. A press while it
  // is busy is ignored. Answers what work answers.
  //
  // Not the disabled attribute: that drops the keyboard focus, and Dom.confirm
  // hands the focus back to this button while it is still busy.
  async busy( button , work ) {
    if ( !button ) return work();
    if ( button.getAttribute( "aria-busy" ) === "true" ) return undefined;
    const spinner = this.el( "span" , { class: "spinner-border spinner-border-sm me-2" , attrs: { "aria-hidden": "true" } } );
    button.classList.add( "disabled" );
    button.setAttribute( "aria-disabled" , "true" );
    button.setAttribute( "aria-busy" , "true" );
    button.prepend( spinner );
    try {
      return await work();
    } finally {
      spinner.remove();
      button.removeAttribute( "aria-busy" );
      button.removeAttribute( "aria-disabled" );
      button.classList.remove( "disabled" );
    }
  },

  // A form's submit handler, with its submit button busy until it finishes.
  // handler has to be async and to await what it sends, or the button comes
  // back early.
  onSubmit( form , handler ) {
    form.addEventListener( "submit" , ( event ) => {
      const button = event.submitter || form.querySelector( "[type=submit]" );
      if ( button && button.getAttribute( "aria-busy" ) === "true" ) {
        event.preventDefault();
        return;
      }
      this.busy( button , () => handler( event ) );
    } );
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
      this.toast( I18n.get( "ui.copy_hint" ) , "ok" );
    }
  },

  // Saves text as a file, for what is better kept than copied.
  download( name , text ) {
    const url = URL.createObjectURL( new Blob( [ text ] , { type: "text/plain" } ) );
    const link = this.el( "a" , { attrs: { href: url , download: name } } );
    document.body.appendChild( link );
    link.click();
    link.remove();
    URL.revokeObjectURL( url );
  },

  // "3 hours ago", in the browser's own language. Past a month the date says
  // more than a count of days does.
  ago( date ) {
    const seconds = ( date.getTime() - Date.now() ) / 1000;
    const size = Math.abs( seconds );
    if ( size >= 30 * 86400 ) return date.toLocaleDateString();
    const format = new Intl.RelativeTimeFormat( undefined , { numeric: "auto" } );
    for ( const [ scale , unit ] of [ [ 86400 , "day" ] , [ 3600 , "hour" ] , [ 60 , "minute" ] ] ) {
      if ( size >= scale ) return format.format( Math.round( seconds / scale ) , unit );
    }
    return format.format( 0 , "second" );
  },

  // A time for a table cell: how long ago at a glance, the exact time on hover.
  // fallback is what a missing or unreadable time says instead ("Never").
  when( value , fallback ) {
    const parsed = new Date( value || "" );
    if ( isNaN( parsed.getTime() ) ) return this.el( "span" , { text: fallback || "" } );
    return this.el( "time" , {
      text: this.ago( parsed ),
      attrs: { datetime: parsed.toISOString() , title: parsed.toLocaleString() },
    } );
  },

  // Asks before something that cannot be taken back, in the app's own theme,
  // which window.confirm cannot be. Answers true or false. An empty question
  // answers true, so a language.yaml key set to "" stops the asking. Cancel
  // has the focus: Enter on a question nobody read should not delete anything.
  confirm( question ) {
    if ( !question ) return Promise.resolve( true );
    const element = this.get( "confirm-modal" );
    if ( element._open ) return Promise.resolve( false );
    element._open = true;
    const returnTo = document.activeElement;
    this.text( this.get( "confirm-text" ) , question );
    const modal = bootstrap.Modal.getOrCreateInstance( element );
    return new Promise( ( resolve ) => {
      let answer = false;
      const ok = this.get( "confirm-ok" );
      const onOk = () => {
        answer = true;
        modal.hide();
      };
      ok.addEventListener( "click" , onOk );
      element.addEventListener( "shown.bs.modal" , () => this.get( "confirm-cancel" ).focus() , { once: true } );
      element.addEventListener( "hidden.bs.modal" , () => {
        ok.removeEventListener( "click" , onOk );
        element._open = false;
        if ( returnTo && returnTo.focus ) returnTo.focus( { preventScroll: true } );
        resolve( answer );
      } , { once: true } );
      modal.show();
    } );
  },

  // A value that edits where it sits, for a name in a table row. Answers the
  // element to put in the row: a button showing the value, which turns into a
  // field when pressed. Enter saves, Escape cancels, and clicking away saves.
  //
  //   Dom.editable( key.name , { label: I18n.get( "api_keys.table_name" ) ,
  //                              maxLength: 80 ,
  //                              save: ( name ) => Api.renameKey( key.id , name ) } );
  //
  // save gets the trimmed value and should throw if it was refused: the field
  // stays open with what was typed, and the toast says why. It may answer a
  // string, for a server that cleaned the value up. It is the place for
  // Undo.record too. Nothing is sent if the value did not change.
  //
  // Options: label (says what is being edited), save, maxLength, placeholder
  // (shown when the value is empty), optional (an empty value is allowed).
  editable( value , options ) {
    const settings = options || {};
    const label = settings.label || "";
    let current = value == null ? "" : String( value );
    const text = this.el( "span" , { class: "inline-edit-text" } );
    const icon = this.el( "i" , { class: "bi bi-pencil inline-edit-icon" , attrs: { "aria-hidden": "true" } } );
    const button = this.el( "button" , {
      class: "inline-edit",
      attrs: { type: "button" },
      children: [ text , icon ],
      on: { click: () => edit() },
    } );

    const paint = () => {
      this.text( text , current || settings.placeholder );
      text.classList.toggle( "text-body-secondary" , current === "" );
      // Functions, so a "$&" in someone's name stays as typed.
      const name = I18n.get( "ui.edit" ).replace( "{label}" , () => label ).replace( "{value}" , () => current );
      button.setAttribute( "aria-label" , name );
      button.title = name;
    };

    const edit = () => {
      const input = this.el( "input" , {
        class: "form-control inline-edit-input",
        attrs: { type: "text" , "aria-label": label },
      } );
      if ( settings.maxLength ) input.maxLength = settings.maxLength;
      input.value = current;
      let open = true;

      const close = ( refocus ) => {
        open = false;
        input.replaceWith( button );
        if ( refocus ) button.focus( { preventScroll: true } );
      };
      const refuse = () => {
        input.classList.add( "is-invalid" );
        input.setAttribute( "aria-invalid" , "true" );
      };
      // refocus is for the keyboard. Someone who clicked away has put the
      // focus where they want it, so it is left there.
      const save = async ( refocus ) => {
        if ( !open || input.readOnly ) return;
        const next = input.value.trim();
        if ( next === current ) return close( refocus );
        if ( next === "" && !settings.optional ) {
          // Clicking away from an emptied field is not a request to save it.
          if ( !refocus ) return close( false );
          return refuse();
        }
        input.readOnly = true;
        input.setAttribute( "aria-busy" , "true" );
        try {
          const answer = await settings.save( next );
          current = typeof answer === "string" ? answer : next;
          paint();
          close( refocus );
        } catch ( error ) {
          refuse();
          this.toast( this.worded( error ) , "error" );
        } finally {
          input.readOnly = false;
          input.removeAttribute( "aria-busy" );
        }
      };

      input.addEventListener( "input" , () => {
        input.classList.remove( "is-invalid" );
        input.removeAttribute( "aria-invalid" );
      } );
      // Enter and Escape, or the keys someone chose instead (shortcuts.js).
      const pressed = ( event , id , key ) =>
        typeof Shortcuts === "undefined" ? event.key === key : Shortcuts.matches( id , event );
      input.addEventListener( "keydown" , ( event ) => {
        // Enter also ends an IME composition, which is not a save.
        if ( pressed( event , "edit_save" , "Enter" ) && !event.isComposing ) {
          event.preventDefault();
          save( true );
        } else if ( pressed( event , "edit_cancel" , "Escape" ) && !input.readOnly ) {
          event.preventDefault();
          event.stopPropagation();
          close( true );
        }
      } );
      // A row refresh takes the field away, which is not someone clicking off it.
      input.addEventListener( "blur" , () => {
        if ( input.isConnected ) save( false );
      } );

      button.replaceWith( input );
      input.focus();
      input.select();
    };

    paint();
    return button;
  },

  // A small form in a dialog, for what is more than one value. Answers what
  // save answered (true if that was nothing), or null if it was cancelled.
  //
  //   await Dom.form( { title: I18n.get( "invite_links.edit_heading" ) ,
  //                     fields: [ { name: "label" , label: "Label" , value: link.label , required: true } ,
  //                               { name: "places" , label: "Places" , type: "number" , min: 1 , value: link.places } ] ,
  //                     save: ( values ) => Api.editInvite( link.id , values ) } );
  //
  // save gets { name: value } and should throw if it was refused: the dialog
  // stays open with what was typed, and says why. Clicking outside does not
  // close it, so a stray click cannot lose a filled-in form.
  //
  // Each field has name and label, and optionally value, help, required,
  // placeholder, maxLength, min and max. type is any text-like input type
  // ("text" by default, "url", ...), or one of:
  //   "number"   -- answers a number, or null when left blank
  //   "checkbox" -- answers true or false
  //   "select"   -- options: [ { value , label } ]
  //   "checks"   -- a group of boxes: options as above, answers the values ticked
  form( options ) {
    const element = this.get( "form-modal" );
    if ( element._open ) return Promise.resolve( null );
    element._open = true;
    const returnTo = document.activeElement;
    const form = this.get( "form-modal-form" );
    const problem = this.get( "form-modal-problem" );
    const submit = this.get( "form-modal-save" );
    const built = options.fields.map( ( field , index ) => this.formField( field , "form-modal-field-" + index ) );

    this.text( this.get( "form-modal-title" ) , options.title );
    this.text( submit , options.submit || I18n.get( "ui.save" ) );
    this.get( "form-modal-fields" ).replaceChildren( ...built.map( ( item ) => item.element ) );
    this.show( problem , false );

    const modal = bootstrap.Modal.getOrCreateInstance( element );
    return new Promise( ( resolve ) => {
      let answer = null;
      let saving = false;

      form.onsubmit = ( event ) => {
        event.preventDefault();
        this.busy( submit , async () => {
          const values = {};
          built.forEach( ( item ) => { values[ item.name ] = item.read(); } );
          this.show( problem , false );
          saving = true;
          try {
            const result = await options.save( values );
            answer = result === undefined ? true : result;
          } catch ( error ) {
            this.text( problem , this.worded( error ) );
            this.show( problem , true );
          }
          saving = false;
          if ( answer !== null ) modal.hide();
        } );
      };

      // Escape or Cancel while it saves would hide whether it worked.
      const holdWhileSaving = ( event ) => {
        if ( saving ) event.preventDefault();
      };
      element.addEventListener( "hide.bs.modal" , holdWhileSaving );
      element.addEventListener( "shown.bs.modal" , () => {
        const first = form.querySelector( "input, select" );
        if ( first ) first.focus();
      } , { once: true } );
      element.addEventListener( "hidden.bs.modal" , () => {
        element.removeEventListener( "hide.bs.modal" , holdWhileSaving );
        form.onsubmit = null;
        element._open = false;
        if ( returnTo && returnTo.focus ) returnTo.focus( { preventScroll: true } );
        resolve( answer );
      } , { once: true } );
      modal.show();
    } );
  },

  // One Dom.form field: its element, and how to read its value back.
  formField( field , id ) {
    const type = field.type || "text";
    const help = field.help ? this.el( "div" , { class: "form-text" , text: field.help , attrs: { id: id + "-help" } } ) : null;
    const box = ( option , checked , boxId ) => {
      const input = this.el( "input" , { class: "form-check-input" , attrs: { type: "checkbox" , id: boxId } } );
      input.checked = checked;
      return { input , element: this.el( "div" , { class: "form-check" , children: [
        input,
        this.el( "label" , { class: "form-check-label" , text: option.label , attrs: { for: boxId } } ),
      ] } ) };
    };
    const assemble = ( children ) => this.el( "div" , { children: children.concat( help ? [ help ] : [] ) } );

    if ( type === "checkbox" ) {
      const single = box( field , Boolean( field.value ) , id );
      if ( help ) single.input.setAttribute( "aria-describedby" , help.id );
      return { name: field.name , element: assemble( [ single.element ] ) , read: () => single.input.checked };
    }
    if ( type === "checks" ) {
      const chosen = field.value || [];
      const boxes = field.options.map( ( option , index ) => Object.assign(
        box( option , chosen.includes( option.value ) , id + "-" + index ) , { value: option.value } ) );
      const group = this.el( "fieldset" , { children: [
        this.el( "legend" , { class: "form-label fs-6" , text: field.label } ),
        ...boxes.map( ( item ) => item.element ),
      ] } );
      return {
        name: field.name,
        element: assemble( [ group ] ),
        read: () => boxes.filter( ( item ) => item.input.checked ).map( ( item ) => item.value ),
      };
    }

    const input = type === "select"
      ? this.el( "select" , { class: "form-select" , children: field.options.map(
          ( option ) => this.el( "option" , { text: option.label , attrs: { value: option.value } } ) ) } )
      : this.el( "input" , { class: "form-control" , attrs: { type: type } } );
    input.id = id;
    input.required = Boolean( field.required );
    if ( help ) input.setAttribute( "aria-describedby" , help.id );
    if ( field.placeholder ) input.placeholder = field.placeholder;
    if ( field.maxLength ) input.maxLength = field.maxLength;
    if ( field.min != null ) input.min = field.min;
    if ( field.max != null ) input.max = field.max;
    if ( field.value != null ) input.value = field.value;
    return {
      name: field.name,
      element: assemble( [ this.el( "label" , { class: "form-label" , text: field.label , attrs: { for: id } } ) , input ] ),
      read: () => {
        if ( type === "number" ) return input.value === "" ? null : Number( input.value );
        return type === "select" ? input.value : input.value.trim();
      },
    };
  },

  // Calls run once typing in a search box has paused, so a word is one request
  // and not one a letter.
  typed( input , run , delayMs = 300 ) {
    let timer = null;
    input.addEventListener( "input" , () => {
      window.clearTimeout( timer );
      timer = window.setTimeout( run , delayMs );
    } );
  },

  // What to tell someone about a refused save: an error code the server
  // answered with is worded by language.yaml's errors section.
  worded( error ) {
    const message = error && error.message ? error.message : "";
    return ( message && I18n.get( "errors." + message ) ) || message || I18n.get( "errors.generic" );
  },

  // Adds a show/hide button to a password field. A key set to "" leaves it out.
  revealable( input ) {
    const label = I18n.get( "ui.show_password" );
    if ( label === "" ) return;
    const icon = this.el( "i" , { class: "bi bi-eye" , attrs: { "aria-hidden": "true" } } );
    const set = ( shown ) => {
      input.type = shown ? "text" : "password";
      icon.className = "bi " + ( shown ? "bi-eye-slash" : "bi-eye" );
      button.setAttribute( "aria-pressed" , String( shown ) );
    };
    const button = this.el( "button" , {
      class: "btn btn-outline-secondary",
      attrs: { type: "button" , "aria-label": label , title: label , "aria-pressed": "false" },
      children: [ icon ],
      on: { click: () => set( input.type === "password" ) },
    } );
    const group = this.el( "div" , { class: "input-group" } );
    input.replaceWith( group );
    group.append( input , button );
    // Sent, it goes back to dots: whoever walks past later should not read it.
    if ( input.form ) input.form.addEventListener( "submit" , () => set( false ) );
  },

  // A problem with one field, shown under it and tied to it for screen readers.
  // Typing in the field clears it. Under a wrapper (a show-password group, a
  // switch) it goes after the wrapper, where Bootstrap's sibling rule cannot
  // reach, so it is always displayed and is removed rather than hidden.
  fieldError( input , message ) {
    const id = input.id + "-problem";
    let problem = this.get( id );
    if ( !problem ) {
      problem = this.el( "div" , { class: "invalid-feedback d-block" , attrs: { id: id } } );
      ( input.closest( ".input-group, .form-check" ) || input ).after( problem );
    }
    this.text( problem , message );
    input.classList.add( "is-invalid" );
    input.setAttribute( "aria-invalid" , "true" );
    const described = ( input.getAttribute( "aria-describedby" ) || "" ).split( " " ).filter( Boolean );
    if ( !described.includes( id ) ) input.setAttribute( "aria-describedby" , described.concat( id ).join( " " ) );
    if ( !input._clearsProblem ) {
      input._clearsProblem = true;
      input.addEventListener( "input" , () => this.clearFieldError( input ) );
    }
  },

  clearFieldError( input ) {
    const id = input.id + "-problem";
    const problem = this.get( id );
    if ( problem ) problem.remove();
    input.classList.remove( "is-invalid" );
    input.removeAttribute( "aria-invalid" );
    const described = ( input.getAttribute( "aria-describedby" ) || "" ).split( " " ).filter( ( name ) => name && name !== id );
    if ( described.length > 0 ) input.setAttribute( "aria-describedby" , described.join( " " ) );
    else input.removeAttribute( "aria-describedby" );
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

  // A row's buttons, as a group named after the row, so a screen reader can say
  // whose Delete this is. Leaves out any that are null. The first `keep` stay in
  // the row, so put what people reach for most first, and the rest go in a menu.
  // A menu of one saves nothing, so one extra button just stays in the row.
  rowActions( name , buttons , keep = 2 ) {
    const all = buttons.filter( Boolean );
    const folded = all.length > keep + 1;
    const children = folded ? all.slice( 0 , keep ).concat( this.rowMenu( name , all.slice( keep ) ) ) : all;
    return this.el( "div" , {
      class: "row-actions",
      attrs: { role: "group" , "aria-label": name },
      children: children,
    } );
  },

  // The fixed strategy is what lets the menu out of .table-responsive, which
  // would otherwise clip it.
  rowMenu( name , items ) {
    const label = I18n.get( "ui.more_actions" ).replace( "{name}" , () => name );
    const toggle = this.el( "button" , {
      class: "btn btn-sm btn-outline-secondary row-menu-toggle",
      // Left out of the activity log: its label holds the row's name.
      attrs: { type: "button" , "data-bs-toggle": "dropdown" , "aria-expanded": "false" , "aria-label": label , title: label , "data-no-track": "" },
      children: [ this.el( "i" , { class: "bi bi-three-dots" , attrs: { "aria-hidden": "true" } } ) ],
    } );
    const list = this.el( "ul" , {
      class: "dropdown-menu dropdown-menu-end",
      children: items.map( ( item ) => {
        item.className = "dropdown-item" + ( item.classList.contains( "btn-outline-danger" ) ? " text-danger" : "" );
        return this.el( "li" , { children: [ item ] } );
      } ),
    } );
    const holder = this.el( "div" , { class: "dropdown" , children: [ toggle , list ] } );
    const menu = new bootstrap.Dropdown( toggle , { popperConfig: { strategy: "fixed" } } );
    // Before the item's own click. Dom.confirm hands the focus back to whatever
    // has it, and the item is about to be hidden. And the press makes the toggle
    // busy, which Bootstrap takes as disabled and would leave the menu open.
    list.addEventListener( "click" , () => {
      menu.hide();
      toggle.focus( { preventScroll: true } );
    } , true );
    return holder;
  },

  // A status pill for a table cell. tone is a Bootstrap color name:
  // "success", "secondary", "warning", "danger".
  badge( text , tone ) {
    return this.el( "span" , { class: "badge text-bg-" + ( tone || "secondary" ) , text: text } );
  },
};

// Counts the times the page was moved on purpose (the reader scrolling by
// hand, or Dom.reveal), so Dom.steady never fights it: a correction is
// skipped if this moved while the work ran.
Dom.scrollIntent = 0;
[ "wheel" , "touchmove" ].forEach( function ( type ) {
  window.addEventListener( type , function () { Dom.scrollIntent += 1; } , { passive: true } );
} );
window.addEventListener( "keydown" , function ( event ) {
  if ( [ "PageUp" , "PageDown" , "Home" , "End" , "ArrowUp" , "ArrowDown" , " " ].includes( event.key )
    && !event.target.closest( "input, textarea, select, button, a, summary, [role=button], [tabindex], [contenteditable]" ) ) Dom.scrollIntent += 1;
} );

// The close button on a box that stays until it is dismissed. A shown-once
// value goes with the box rather than sitting hidden in the page. The value of
// data-box-close is the field to hand the focus to, which would otherwise be
// lost with the button.
document.addEventListener( "click" , function ( event ) {
  const button = event.target.closest( "[data-box-close]" );
  if ( !button ) return;
  const box = button.closest( ".alert" );
  Dom.all( "code" , box ).forEach( function ( value ) { Dom.text( value , "" ); } );
  Dom.show( box , false );
  const next = Dom.get( button.getAttribute( "data-box-close" ) );
  if ( next ) next.focus();
} );
