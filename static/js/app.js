// Page logic for the account + admin screen this template ships with.
//
// Most projects will replace much of this file. What is worth keeping is the
// shape: load the language file, ask /api/me once, then branch on
// authenticated/role. Do not re-check the session anywhere else -- the server
// is the authority, and a second client-side notion of "am I logged in" is
// how the two drift apart.
//
// New screens belong in their own file under /js/ with their own init(),
// rather than being appended here until this becomes the monolith the rest of
// the project is organised to avoid.

const App = {
  currentUser: null,

  async init() {
    try {
      await I18n.load();
      I18n.apply();
    } catch ( error ) {
      // Without the language file every label is blank, so say something in
      // the one place that can afford a hardcoded string.
      Dom.text( Dom.get( "error-banner" ) , "Could not load language file." );
      Dom.show( Dom.get( "error-banner" ) , true );
    }

    let me = { authenticated: false };
    try {
      me = await Api.me();
    } catch ( error ) {
      this.showError( I18n.get( "errors.network" ) );
    }

    this.currentUser = me.authenticated ? me : null;
    Dom.show( Dom.get( "main" ) , true );

    if ( this.loginCredential() !== "" ) {
      this.renderLoginConfirm( me );
      return;
    }
    if ( Join.credential() !== "" ) {
      await Join.init( me );
      return;
    }
    if ( !me.authenticated ) {
      this.renderSignedOut();
      return;
    }
    await this.renderSignedIn( me );
  },

  renderSignedOut() {
    Dom.show( Dom.get( "signed-out" ) , true );
    // A failed login lands here with ?login=invalid rather than explaining
    // what was wrong with the link -- see app/routes/auth.py.
    const params = new URLSearchParams( window.location.search );
    if ( params.get( "login" ) === "invalid" ) {
      const banner = Dom.get( "invalid-link" );
      if ( I18n.get( "signed_out.invalid_link" ) !== "" ) Dom.show( banner , true );
    }
  },

  // A login link is /login/<credential>, and the server answers it with this
  // page. Nothing has been redeemed at that point.
  loginCredential() {
    const prefix = "/login/";
    const path = window.location.pathname;
    if ( path.indexOf( prefix ) !== 0 ) return "";
    try {
      return decodeURIComponent( path.slice( prefix.length ) ).replace( /\/+$/ , "" );
    } catch ( error ) {
      return "";
    }
  },

  // Opening a login link only shows this. The link is spent by the POST the
  // button sends, so a chat app's link preview or a mail scanner fetching the
  // URL cannot use it up, and someone already signed in is told they are
  // about to switch accounts rather than being switched silently.
  renderLoginConfirm( me ) {
    Dom.show( Dom.get( "login-confirm" ) , true );
    if ( me.authenticated ) {
      const warning = I18n.get( "login_confirm.switch_warning" );
      if ( warning !== "" ) {
        const box = Dom.get( "login-switch-warning" );
        Dom.text( box , warning.replace( "{name}" , me.display_name ) );
        Dom.show( box , true );
      }
    }

    const button = Dom.get( "login-confirm-button" );
    button.addEventListener( "click" , async () => {
      button.disabled = true;
      try {
        await Api.login( this.loginCredential() );
        // replace, not assign: the link should not stay in the back button.
        window.location.replace( "/" );
      } catch ( error ) {
        if ( error.status === 400 ) {
          window.location.replace( "/?login=invalid" );
          return;
        }
        // Anything else (rate limited, network) leaves the link unspent,
        // so let them try again.
        button.disabled = false;
        this.showError( error.message );
      }
    } );
  },

  async renderSignedIn( me ) {
    Dom.show( Dom.get( "signed-in" ) , true );
    Dom.show( Dom.get( "app-nav" ) , true );
    this.labelAccount();
    Theme.render( Dom.get( "theme-picker" ) );
    Dom.get( "display-name" ).value = me.display_name;

    Dom.get( "rename-form" ).addEventListener( "submit" , this.onRename.bind( this ) );
    Dom.get( "logout-button" ).addEventListener( "click" , this.onLogout.bind( this ) );
    Dom.get( "my-link-button" ).addEventListener( "click" , this.onMyLoginLink.bind( this ) );
    Dom.get( "my-link-copy-button" ).addEventListener( "click" , () => Dom.copy( Dom.get( "my-link-value" ) ) );

    // Each screen owns its own file and its own init(). These lines are the
    // only place that knows which screens exist.
    Pin.init( me );
    await Keys.init( me );

    // The library first: everything below draws from it.
    try {
      await Promise.all( [ Library.load() , Prefs.load() ] );
    } catch ( error ) {
      this.showError( error.message );
    }
    this.initAppleTv();
    Acting.init( me );
    await Playlists.init();
    await LibraryScreen.init( me );
    AddScreen.init( me );
    DupesScreen.init( me );
    PortingScreen.init( me );
    await DiscoverScreen.init( me );
    await TypesScreen.init( me );
    JobsScreen.init( me );
    PlaylistsScreen.init( me );
    Library.startPolling();

    if ( me.role === "admin" ) {
      Dom.show( Dom.get( "admin-panel" ) , true );
      Dom.get( "create-user-form" ).addEventListener( "submit" , this.onCreateUser.bind( this ) );
      Dom.get( "copy-link-button" ).addEventListener( "click" , this.onCopyLink.bind( this ) );
      await this.refreshUsers();
      await Invites.init( me );
    }

    // Last, so the sidebar offers exactly the screens the lines above un-hid.
    Nav.init();
    window.addEventListener( "hashchange" , () => LibraryNav.render() );
    LibraryScreen.render();
  },

  // Where Apple TV links open: the TV app (the default) or the website.
  initAppleTv() {
    const box = Dom.get( "appletv-app" );
    box.checked = Prefs.ui( "appletv_app" , true );
    const apply = ( on ) => {
      box.checked = on;
      Prefs.setUi( "appletv_app" , on );
      // The link is part of what a card draws, so the cards are redrawn.
      LibraryScreen.render();
      if ( DiscoverScreen.meta ) DiscoverScreen.render();
      PlaylistsScreen.render();
    };
    box.addEventListener( "change" , () => {
      const on = box.checked;
      apply( on );
      Undo.record( {
        label: I18n.get( on ? "account.appletv_on" : "account.appletv_off" ),
        toast: true,
        undo: () => apply( !on ),
        redo: () => apply( on ),
      } );
    } );
  },

  async onRename( event ) {
    event.preventDefault();
    const value = Dom.get( "display-name" ).value.trim();
    const previous = this.currentUser.display_name;
    if ( value === previous ) return;
    try {
      await this.applyRename( value , previous );
    } catch ( error ) {
      this.showError( error.message );
      return;
    }
    // Let go of the field, so the next Ctrl+Z undoes the rename rather than
    // the typing.
    Undo.saved( event.target );
    // The server-backed undo example: both directions go through the API, so
    // Ctrl+Z puts the old name back on the account, not just on the screen.
    // Each says which name it expects to find, so a rename made in another
    // tab since is refused (409) rather than overwritten.
    Undo.record( {
      label: I18n.get( "undo.rename" ),
      toast: true,
      undo: () => this.applyRename( previous , value ),
      redo: () => this.applyRename( value , previous ),
    } );
  },

  async applyRename( value , expect ) {
    await Api.rename( value , expect );
    this.currentUser.display_name = value;
    Dom.get( "display-name" ).value = value;
    this.labelAccount();
  },

  // The sidebar's Account entry names who is signed in on its second line.
  labelAccount() {
    const user = this.currentUser;
    Dom.text( Dom.get( "sidebar-user" ) , user.display_name + " (" + user.role + ")" );
  },

  // A fresh one-time link for this account, to open on another device. The
  // server only allows it from a browser session, never an API key.
  async onMyLoginLink() {
    try {
      const issued = await Api.createMyLoginLink();
      Dom.text( Dom.get( "my-link-value" ) , window.location.origin + issued.login_path );
      Dom.show( Dom.get( "my-link-box" ) , true );
    } catch ( error ) {
      this.showError( error.message );
    }
  },

  async onLogout() {
    try {
      await Api.logout();
    } catch ( error ) {
      // Even if the call failed, reloading lands on the signed-out page,
      // which is the honest state to show.
    }
    window.location.href = "/";
  },

  async onCreateUser( event ) {
    event.preventDefault();
    const name = Dom.get( "new-name" ).value.trim();
    const role = Dom.get( "new-role" ).value;
    try {
      const created = await Api.createUser( name , role );
      this.showLoginLink( created.login_path );
      Dom.get( "new-name" ).value = "";
      await this.refreshUsers();
    } catch ( error ) {
      this.showError( error.message );
    }
  },

  // The server returns a path, not a full URL: behind a reverse proxy it does
  // not reliably know its own public origin, whereas the browser always does.
  showLoginLink( loginPath ) {
    Dom.text( Dom.get( "login-link-value" ) , window.location.origin + loginPath );
    Dom.show( Dom.get( "login-link-box" ) , true );
  },

  async onCopyLink() {
    await Dom.copy( Dom.get( "login-link-value" ) );
  },

  async refreshUsers() {
    const body = Dom.get( "users-table" ).querySelector( "tbody" );
    let users = [];
    try {
      users = await Api.listUsers();
    } catch ( error ) {
      this.showError( error.message );
      return;
    }

    Dom.clear( body );
    users.forEach( function ( user ) {
      const statusKey = user.disabled ? "admin.status_disabled" : "admin.status_active";
      const statusTone = user.disabled ? "secondary" : "success";

      const reissueButton = Dom.el( "button" , {
        class: "btn btn-sm btn-outline-secondary",
        text: I18n.get( "admin.reissue_button" ),
        on: { click: async function () {
          try {
            const issued = await Api.reissueLogin( user.id );
            App.showLoginLink( issued.login_path );
          } catch ( error ) { App.showError( error.message ); }
        } },
      } );

      // The server is the authority on all of these; the rules below only
      // decide which buttons it would refuse, so they are not offered. Your
      // own row and the owner's never get revoke, disable, or delete.
      const isSelf = user.id === App.currentUser.id;
      const isProtected = isSelf || user.owner;

      // Revoking is for "someone else may have this account's credentials":
      // it ends every session, unused login link, and API key, and leaves the
      // account enabled. Not offered on your own row -- the server refuses
      // that, since it would sign you out with no way back in.
      const revokeButton = isProtected ? null : Dom.el( "button" , {
        class: "btn btn-sm btn-outline-danger",
        text: I18n.get( "admin.revoke_button" ),
        on: { click: async function () {
          const question = I18n.get( "admin.revoke_confirm" ).replace( "{name}" , user.display_name );
          if ( question !== "" && !window.confirm( question ) ) return;
          try {
            await Api.revokeAccess( user.id );
            if ( App.currentUser.api_keys_enabled ) await Keys.refreshAll();
          } catch ( error ) { App.showError( error.message ); }
        } },
      } );

      const toggleButton = isProtected ? null : Dom.el( "button" , {
        class: "btn btn-sm btn-outline-secondary",
        text: I18n.get( user.disabled ? "admin.enable_button" : "admin.disable_button" ),
        on: { click: async function () {
          try {
            await Api.setDisabled( user.id , !user.disabled );
            await App.refreshUsers();
          } catch ( error ) { App.showError( error.message ); }
        } },
      } );

      // Deleting removes the account and everything it held, for good. Any
      // admin may delete a user; only the owner may delete another admin.
      const canDelete = !isProtected && ( user.role !== "admin" || App.currentUser.is_owner );
      const deleteButton = !canDelete ? null : Dom.el( "button" , {
        class: "btn btn-sm btn-outline-danger",
        text: I18n.get( "admin.delete_button" ),
        on: { click: async function () {
          const question = I18n.get( "admin.delete_confirm" ).replace( "{name}" , user.display_name );
          if ( question !== "" && !window.confirm( question ) ) return;
          try {
            await Api.deleteUser( user.id );
            await App.refreshUsers();
            if ( App.currentUser.api_keys_enabled ) await Keys.refreshAll();
          } catch ( error ) { App.showError( error.message ); }
        } },
      } );

      const ownerLabel = I18n.get( "admin.owner_label" );
      const roleText = user.owner && ownerLabel !== "" ? user.role + " (" + ownerLabel + ")" : user.role;

      // Built with createElement + textContent, never an HTML string: a
      // display name is user-controlled input.
      body.appendChild( Dom.el( "tr" , { children: [
        Dom.el( "td" , { text: user.display_name } ),
        Dom.el( "td" , { text: roleText } ),
        Dom.el( "td" , { children: [ Dom.badge( I18n.get( statusKey ) , statusTone ) ] } ),
        Dom.el( "td" , { children: [
          Dom.el( "div" , { class: "row-actions" , children: [ reissueButton , revokeButton , toggleButton , deleteButton ].filter( Boolean ) } ),
        ] } ),
      ] } ) );
    } );
  },

  // message may be an error code the server answered with (pin_wrong,
  // invite_link_full, ...); language.yaml's errors section words those.
  showError( message ) {
    const banner = Dom.get( "error-banner" );
    const worded = message ? I18n.get( "errors." + message ) : "";
    Dom.text( banner , worded || message || I18n.get( "errors.generic" ) );
    Dom.flash( banner , 5000 );
  },
};

document.addEventListener( "DOMContentLoaded" , function () {
  App.init();
} );
