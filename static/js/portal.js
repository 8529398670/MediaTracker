// The owner's ProjectPortal card, on the API keys screen (portal contract
// v3). ProjectPortal works through a service account of its own, never the
// owner's key: Connect makes that account (when there is none by the name
// given) and one admin key for it that may make keys and never sign-in links,
// shown once. The status lists its live keys and when they expire, and
// Disconnect revokes them all, and with them everything they made.
//
// Only the owner has the card: the routes are the owner's (role=OWNER), and
// answer anyone else 404. app.js calls Portal.init( me ) once it knows who is
// signed in.
const Portal = {
  me: null,

  async init( me ) {
    this.me = me;
    if ( me.api_keys_enabled === false || !me.is_owner ) return;
    Dom.show( Dom.get( "portal-card" ) , true );
    Dom.onSubmit( Dom.get( "portal-connect-form" ) , this.onConnect.bind( this ) );
    Dom.get( "copy-portal-key-button" ).addEventListener( "click" , () => Dom.copy( Dom.get( "portal-key-value" ) ) );
    await this.refresh();
  },

  async refresh() {
    let page;
    try {
      page = await Api.request( "/api/owner/portal" );
    } catch ( error ) {
      App.showError( error.message );
      return;
    }
    const list = Dom.get( "portal-status" );
    list.replaceChildren();
    const keys = [];
    for ( const account of page.accounts ) {
      for ( const key of account.keys ) keys.push( { account: account , key: key } );
    }
    if ( keys.length === 0 ) {
      list.appendChild( Dom.el( "li" , { class: "list-group-item text-body-secondary" , text: I18n.get( "portal.none" ) } ) );
    }
    const soon = Date.now() + 30 * 24 * 60 * 60 * 1000;
    for ( const { account , key } of keys ) {
      const expires = key.expires_at ? new Date( key.expires_at ) : null;
      const warning = expires !== null && expires.getTime() < soon;
      const when = expires === null ? I18n.get( "portal.never_expires" ) : I18n.get( "portal.expires" ).replace( "{date}" , () => expires.toLocaleDateString() );
      list.appendChild( Dom.el( "li" , {
        class: "list-group-item d-flex flex-wrap align-items-center gap-2" ,
        children: [
          Dom.el( "i" , { class: "bi bi-plug" , attrs: { "aria-hidden": "true" } } ) ,
          Dom.el( "span" , { class: "fw-semibold" , text: account.display_name } ) ,
          Dom.el( "span" , { class: "text-body-secondary" , text: key.name } ) ,
          Dom.badge( when , warning ? "warning" : "secondary" ) ,
        ] ,
      } ) );
    }
    const button = Dom.get( "portal-disconnect-button" );
    Dom.show( button , page.accounts.length > 0 && keys.length > 0 );
    button.onclick = () => this.onDisconnect( page.accounts );
  },

  async onConnect( event ) {
    event.preventDefault();
    const name = Dom.get( "portal-name" ).value.trim() || "ProjectPortal";
    const days = Number( Dom.get( "portal-days" ).value );
    try {
      const created = await Api.post( "/api/owner/portal/connect" , { name: name , days: days } );
      Dom.text( Dom.get( "portal-key-value" ) , created.credential );
      Dom.show( Dom.get( "portal-key-box" ) , true );
      await this.refresh();
    } catch ( error ) {
      App.showError( error.message );
    }
  },

  async onDisconnect( accounts ) {
    if ( !( await Dom.confirm( I18n.get( "portal.disconnect_confirm" ) ) ) ) return;
    try {
      for ( const account of accounts ) {
        await Api.post( "/api/owner/portal/disconnect" , { user_id: account.id } );
      }
      Dom.show( Dom.get( "portal-key-box" ) , false );
      await this.refresh();
    } catch ( error ) {
      App.showError( error.message );
    }
  },
};
