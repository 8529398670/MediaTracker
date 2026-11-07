// The invite links panel (admin only): one link a whole group can join
// through. app.js calls Invites.init( me ) once it knows the viewer is an
// admin; the server checks again on every call.
const Invites = {
  async init( me ) {
    if ( me.role !== "admin" ) return;
    Dom.show( Dom.get( "invite-links-panel" ) , true );
    Dom.get( "create-invite-form" ).addEventListener( "submit" , this.onCreate.bind( this ) );
    Dom.get( "copy-invite-button" ).addEventListener( "click" , this.onCopy.bind( this ) );
    await this.refresh();
  },

  async onCreate( event ) {
    event.preventDefault();
    const label = Dom.get( "invite-label" ).value.trim();
    const maxUses = parseInt( Dom.get( "invite-uses" ).value , 10 );
    const days = parseInt( Dom.get( "invite-days" ).value , 10 );
    try {
      const created = await Api.createInvite( label , maxUses , days );
      // A path, not a URL, for the same reason as a login link: the browser
      // knows its public origin, the server behind a proxy may not.
      Dom.text( Dom.get( "invite-link-value" ) , window.location.origin + created.join_path );
      Dom.show( Dom.get( "invite-link-box" ) , true );
      Dom.get( "invite-label" ).value = "";
      await this.refresh();
    } catch ( error ) {
      App.showError( error.message );
    }
  },

  async onCopy() {
    await Dom.copy( Dom.get( "invite-link-value" ) );
  },

  status( link ) {
    if ( link.revoked ) return Dom.badge( I18n.get( "invite_links.status_revoked" ) , "secondary" );
    if ( new Date( link.expires_at ) <= new Date() ) return Dom.badge( I18n.get( "invite_links.status_expired" ) , "warning" );
    if ( !link.live ) return Dom.badge( I18n.get( "invite_links.status_orphaned" ) , "warning" );
    if ( link.remaining <= 0 ) return Dom.badge( I18n.get( "invite_links.status_full" ) , "secondary" );
    return Dom.badge( I18n.get( "invite_links.status_live" ) , "success" );
  },

  async refresh() {
    const body = Dom.get( "invite-links-table" ).querySelector( "tbody" );
    let links = [];
    try {
      links = await Api.listInvites();
    } catch ( error ) {
      App.showError( error.message );
      return;
    }

    Dom.clear( body );
    links.forEach( function ( link ) {
      const revokeButton = !link.live ? null : Dom.el( "button" , {
        class: "btn btn-sm btn-outline-danger",
        text: I18n.get( "invite_links.revoke_button" ),
        on: { click: async function () {
          const question = I18n.get( "invite_links.revoke_confirm" );
          if ( question !== "" && !window.confirm( question ) ) return;
          try {
            await Api.revokeInvite( link.id );
            await Invites.refresh();
          } catch ( error ) { App.showError( error.message ); }
        } },
      } );

      // Delete asks nothing and offers Undo: the server keeps a deleted link
      // restorable for a few minutes. Revoke stays a confirmed, one-way step
      // (see Keys.revokeButton for why).
      const deleteButton = Dom.el( "button" , {
        class: "btn btn-sm btn-outline-danger",
        text: I18n.get( "invite_links.delete_button" ),
        on: { click: async function () {
          try {
            await Api.deleteInvite( link.id );
            await Invites.refresh();
          } catch ( error ) {
            App.showError( error.message );
            return;
          }
          Undo.record( {
            label: I18n.get( "undo.deleted_invite" ),
            toast: true,
            undo: async () => { await Api.restoreInvite( link.id ); await Invites.refresh(); },
            redo: async () => { await Api.deleteInvite( link.id ); await Invites.refresh(); },
          } );
        } },
      } );

      const joined = I18n.get( "invite_links.joined_of" )
        .replace( "{used}" , String( link.used ) )
        .replace( "{max}" , String( link.max_uses ) );

      // createElement + textContent, never an HTML string: the label is
      // admin-typed text.
      body.appendChild( Dom.el( "tr" , { children: [
        Dom.el( "td" , { text: link.label } ),
        Dom.el( "td" , { text: joined } ),
        Dom.el( "td" , { children: [ Invites.status( link ) ] } ),
        Dom.el( "td" , { text: new Date( link.expires_at ).toLocaleDateString() } ),
        Dom.el( "td" , { children: [
          Dom.el( "div" , { class: "row-actions" , children: [ revokeButton , deleteButton ].filter( Boolean ) } ),
        ] } ),
      ] } ) );
    } );
  },
};
