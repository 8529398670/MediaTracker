// "Where you're signed in", on the Account screen: every device with a live
// session on this account, and a way to sign one out from here. app.js calls
// Sessions.init() once it knows who is signed in.
//
// Signing a device out is never undoable: it is the button for a lost phone,
// and an undo would let the session back in. So it asks first, like revoking an
// API key. This device has no button here; that is what Log out is for.
const Sessions = {
  // Whose devices an admin has open under the Users table.
  shownFor: null,

  async init() {
    Dom.onPress( Dom.get( "sessions-revoke-others" ) , () => this.onRevokeOthers() );
    window.addEventListener( "hashchange" , () => {
      if ( Nav.current() === "account" ) this.refresh();
    } );
    await this.refresh();
  },

  // A short name out of a User-Agent header. It only has to help someone tell
  // their own devices apart; the order matters, since Edge and Chrome both
  // say Safari, and Android says Linux.
  browser( agent ) {
    const known = [ [ /Edg\// , "Edge" ] , [ /OPR\// , "Opera" ] , [ /Firefox\// , "Firefox" ] , [ /Chrome\// , "Chrome" ] , [ /Safari\// , "Safari" ] ];
    const match = known.find( function ( entry ) { return entry[ 0 ].test( agent ); } );
    return match ? match[ 1 ] : "";
  },

  system( agent ) {
    const known = [ [ /Android/ , "Android" ] , [ /iPhone|iPad/ , "iOS" ] , [ /Mac OS X/ , "macOS" ] , [ /Windows/ , "Windows" ] , [ /Linux/ , "Linux" ] ];
    const match = known.find( function ( entry ) { return entry[ 0 ].test( agent ); } );
    return match ? match[ 1 ] : "";
  },

  device( session ) {
    const agent = session.user_agent || "";
    const browser = this.browser( agent );
    const system = this.system( agent );
    if ( browser && system ) {
      return I18n.get( "sessions.device_name" ).replace( "{browser}" , browser ).replace( "{system}" , system );
    }
    return browser || system || agent || I18n.get( "sessions.unknown_device" );
  },

  // What you call a device, in place of the name worked out for it. That name
  // stays underneath, so a label cannot hide what a device says it is. rename
  // is left out on an admin's view: the label is the person's own.
  nameCell( session , rename ) {
    const device = this.device( session );
    const detail = Dom.el( "div" , { class: "small text-body-secondary" , text: device } );
    Dom.show( detail , Boolean( session.label ) );
    const name = !rename ? Dom.el( "span" , { text: session.label || device } ) : Dom.editable( session.label || "" , {
      label: I18n.get( "sessions.table_device" ),
      maxLength: 80,
      optional: true,
      placeholder: device,
      save: async ( value ) => {
        await rename( value );
        Dom.show( detail , value !== "" );
      },
    } );
    const line = [ name ];
    if ( session.current ) line.push( Dom.el( "span" , { class: "ms-2" , children: [ Dom.badge( I18n.get( "sessions.this_device" ) , "success" ) ] } ) );
    return [ Dom.el( "div" , { children: line } ) , detail ];
  },

  // Saves a label on your own list. An empty one puts the worked-out name back.
  rename( session ) {
    return async ( value ) => {
      const previous = session.label || "";
      await Api.labelSession( session.id , value , previous );
      session.label = value;
      Undo.record( {
        label: I18n.get( "undo.rename_session" ),
        toast: true,
        undo: async () => { await Api.labelSession( session.id , previous , value ); await this.refresh(); },
        redo: async () => { await Api.labelSession( session.id , value , previous ); await this.refresh(); },
      } );
    };
  },

  // revoke is the call that ends this session and redraws its table: the
  // button is the same on your own list and on an admin's view of someone's.
  revokeButton( revoke ) {
    return Dom.el( "button" , {
      class: "btn btn-sm btn-outline-danger text-nowrap",
      text: I18n.get( "sessions.revoke_button" ),
      on: { click: async () => {
        // An empty confirm message means "do not ask", following the same
        // language.yaml rule as every other string here.
        const question = I18n.get( "sessions.revoke_confirm" );
        if ( !( await Dom.confirm( question ) ) ) return;
        try {
          await revoke();
        } catch ( error ) { App.showError( error.message ); }
      } },
    } );
  },

  async onRevokeOthers() {
    const question = I18n.get( "sessions.revoke_others_confirm" );
    if ( !( await Dom.confirm( question ) ) ) return;
    try {
      await Api.revokeOtherSessions();
      await this.refresh();
    } catch ( error ) { App.showError( error.message ); }
  },

  async refresh() {
    const body = Dom.get( "sessions-table" ).querySelector( "tbody" );
    const page = await Pager.load( "sessions-table" , "sessions" , ( offset ) => Api.sessions( offset ) , ( session ) => {
      body.appendChild( this.row( session , async () => {
        await Api.revokeSession( session.id );
        await this.refresh();
      } , this.rename( session ) ) );
    } );
    if ( page !== null ) Dom.show( Dom.get( "sessions-revoke-others" ) , page.total > 1 );
  },

  row( session , revoke , rename ) {
    return Dom.el( "tr" , { children: [
      Dom.el( "td" , { children: this.nameCell( session , rename ) } ),
      Dom.el( "td" , { children: [ Dom.el( "span" , { text: session.ip || I18n.get( "sessions.unknown" ) } ) ] } ),
      Dom.el( "td" , { children: [ Dom.when( session.last_seen_at , I18n.get( "sessions.unknown" ) ) ] } ),
      Dom.el( "td" , { children: [ Dom.when( session.created_at , I18n.get( "sessions.unknown" ) ) ] } ),
      Dom.el( "td" , { children: session.current ? [] : [ Dom.rowActions( session.label || this.device( session ) , [ this.revokeButton( revoke ) ] ) ] } ),
    ] } );
  },

  // An admin's view of one account's devices, under the Users table: for ending
  // one of them, where revoke access would end everything.
  async showFor( user ) {
    // Someone else's devices must not sit under this name while it loads.
    if ( !this.shownFor || this.shownFor.id !== user.id ) Pager.reset( "user-sessions-table" );
    this.shownFor = user;
    Dom.text( Dom.get( "user-sessions-heading" ) , I18n.get( "sessions.user_heading" ).replace( "{name}" , user.display_name ) );
    Dom.show( Dom.get( "user-sessions" ) , true );
    const body = Dom.get( "user-sessions-table" ).querySelector( "tbody" );
    await Pager.load( "user-sessions-table" , "sessions" , ( offset ) => Api.userSessions( user.id , offset ) , ( session ) => {
      body.appendChild( this.row( session , async () => {
        await Api.revokeUserSession( user.id , session.id );
        await this.showFor( user );
      } ) );
    } );
    Dom.get( "user-sessions" ).scrollIntoView( { block: "nearest" } );
  },

  closeFor() {
    this.shownFor = null;
    Dom.show( Dom.get( "user-sessions" ) , false );
  },
};
