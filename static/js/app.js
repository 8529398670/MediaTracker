// Page logic for the account + admin screen this template ships with.
//
// Most projects will replace much of this file. What is worth keeping is the
// shape: load the language file, ask /api/me, then branch on
// authenticated/role. Do not keep a second client-side notion of "am I logged
// in" -- the server is the authority, and guessing is how the two drift apart.
// When the page needs to know again it asks again: see fresh.js, and the 401
// handling in api.js.
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
      Dom.text( Dom.get( "error-banner-text" ) , "Could not load language file." );
      Dom.show( Dom.get( "error-copy-button" ) , false );
      Dom.show( Dom.get( "error-banner" ) , true );
    }

    Dom.all( "input[type=password]" ).forEach( ( input ) => Dom.revealable( input ) );
    // Not a plain #main link: the hash is which screen is showing.
    Dom.get( "skip-link" ).addEventListener( "click" , ( event ) => {
      event.preventDefault();
      Dom.get( "main" ).focus();
    } );

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
    // what was wrong with the link -- see routes/auth.go.
    const params = new URLSearchParams( window.location.search );
    if ( params.get( "login" ) === "invalid" ) {
      const banner = Dom.get( "invalid-link" );
      if ( I18n.get( "signed_out.invalid_link" ) !== "" ) Dom.show( banner , true );
    }
    if ( params.get( "login" ) === "expired" ) {
      Dom.show( Dom.get( "sign-in-expired" ) , I18n.get( "signed_out.sign_in_expired" ) !== "" );
    }
    if ( params.get( "login" ) === "ended" ) {
      Dom.show( Dom.get( "session-ended" ) , I18n.get( "signed_out.session_ended" ) !== "" );
    }
    Password.initLogin();
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
        const result = await Api.login( this.loginCredential() );
        if ( result.two_factor ) {
          TwoFactor.ask( result.challenge );
          return;
        }
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

  // Says so on every screen, so nobody wonders why a change was refused and
  // the owner, whom the mode lets through, cannot leave it on by accident.
  showMaintenance( me ) {
    const banner = Dom.get( "maintenance-banner" );
    const on = me.maintenance === "read_only" || me.maintenance === "full";
    if ( on ) Dom.text( banner , I18n.get( "maintenance." + me.maintenance + "_banner" ) );
    Dom.show( banner , on );
  },

  // What the owner wants everyone to read. Dismissing it is remembered against
  // its text, so the next message shows up however the last one went.
  showAnnouncement( me ) {
    const text = me.announcement || "";
    let dismissed = "";
    try {
      dismissed = window.localStorage.getItem( "announcement-dismissed" ) || "";
    } catch ( error ) { /* storage blocked: it comes back on the next load */ }
    Dom.text( Dom.get( "announcement-text" ) , text );
    Dom.show( Dom.get( "announcement-banner" ) , text !== "" && text !== dismissed );
  },

  onDismissAnnouncement() {
    Dom.show( Dom.get( "announcement-banner" ) , false );
    try {
      window.localStorage.setItem( "announcement-dismissed" , Dom.get( "announcement-text" ).textContent );
    } catch ( error ) { /* storage blocked: it comes back on the next load */ }
  },

  async renderSignedIn( me ) {
    Dom.show( Dom.get( "app-loading" ) , true );
    Dom.show( Dom.get( "signed-in" ) , true );
    this.showMaintenance( me );
    this.showAnnouncement( me );
    Dom.get( "announcement-dismiss" ).addEventListener( "click" , () => this.onDismissAnnouncement() );
    Dom.show( Dom.get( "app-nav" ) , true );
    Undo.bindButtons( Dom.get( "undo-button" ) , Dom.get( "redo-button" ) );
    this.labelAccount();
    ThemeEditor.init( me );
    Dom.get( "display-name" ).value = me.display_name;

    Dom.onSubmit( Dom.get( "rename-form" ) , this.onRename.bind( this ) );
    Dom.get( "logout-button" ).addEventListener( "click" , this.onLogout.bind( this ) );
    Dom.onPress( Dom.get( "my-link-button" ) , this.onMyLoginLink.bind( this ) );
    Dom.get( "my-link-cancel-button" ).addEventListener( "click" , this.onCancelMyLoginLink.bind( this ) );
    this.showMyLiveLink( me.login_link );
    Dom.get( "my-link-copy-button" ).addEventListener( "click" , () => Dom.copy( Dom.get( "my-link-value" ) ) );
    Qr.toggle( Dom.get( "my-link-qr-button" ) , Dom.get( "my-link-qr" ) , Dom.get( "my-link-value" ) );

    // Each screen owns its own file and its own init(). These lines are the
    // only place that knows which screens exist.
    Track.init( me );
    Pin.init( me );
    Password.init( me );
    TwoFactor.init( me );
    Fresh.init( me );
    // Side by side: the wait is the slowest screen, not all of them added up.
    const loading = [];
    loading.push( Keys.init( me ) );
    Mcp.init( me );
    loading.push( Sessions.init() );
    About.init( me );

    // The library first: everything below draws from it. Someone who starts
    // on another person's lists has to be on them before the first load.
    Acting.start( me );
    try {
      await Promise.all( [ Library.load() , Prefs.load() ] );
    } catch ( error ) {
      this.showError( error.message );
    }
    this.initAppleTv();
    this.initCornerWatch();
    this.initCardLinks();
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
      LoginLinks.fill( Dom.get( "new-uses" ) , Dom.get( "new-expires" ) );
      Dom.onSubmit( Dom.get( "create-user-form" ) , this.onCreateUser.bind( this ) );
      Dom.get( "copy-link-button" ).addEventListener( "click" , this.onCopyLink.bind( this ) );
      Qr.toggle( Dom.get( "login-link-qr-button" ) , Dom.get( "login-link-qr" ) , Dom.get( "login-link-value" ) );
      Pager.search( "users-table" , "users-search" , () => this.refreshUsers() );
      Dom.get( "user-sessions-close" ).addEventListener( "click" , () => Sessions.closeFor() );
      Pager.sortable( "users-table" , () => this.refreshUsers() );
      // Only the owner gets the Logs, Jobs, Webhooks and Settings screens; each init
      // checks is_owner.
      loading.push( this.refreshUsers() );
      loading.push( Invites.init( me ) );
      loading.push( Logs.init( me ) );
      loading.push( Settings.init( me ) );
      const version = I18n.get( "nav.version" );
      if ( version !== "" ) {
        Dom.text( Dom.get( "sidebar-version" ) , version.replace( "{version}" , me.version ) );
        Dom.show( Dom.get( "sidebar-version" ) , true );
      }
    }

    // allSettled, not all: Nav.init has to run whatever else went wrong, or
    // one screen's failure would leave no screen showing at all.
    const results = await Promise.allSettled( loading );
    results.forEach( ( result ) => {
      if ( result.status === "rejected" ) this.showError( result.reason.message );
    } );
    Dom.show( Dom.get( "app-loading" ) , false );

    // After the screens, so the Cards tab finds their card settings.
    Appearance.init();
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

  // Whether a grid card's poster carries Watched on its top-right corner.
  initCornerWatch() {
    const box = Dom.get( "corner-watch" );
    box.checked = Prefs.ui( "corner_watch" , true );
    const apply = ( on ) => {
      box.checked = on;
      Prefs.setUi( "corner_watch" , on );
      LibraryScreen.render();
      if ( DiscoverScreen.meta ) DiscoverScreen.render();
      PlaylistsScreen.render();
    };
    box.addEventListener( "change" , () => {
      const on = box.checked;
      apply( on );
      Undo.record( {
        label: I18n.get( on ? "account.corner_watch_on" : "account.corner_watch_off" ),
        toast: true,
        undo: () => apply( !on ),
        redo: () => apply( on ),
      } );
    } );
  },

  // Which links sit on every card's face, and in what order.
  initCardLinks() {
    this.initLinkList( {
      prefix: "card-links",
      pref: "card_links",
      get: () => Vocab.mainButtons(),
      defaults: Vocab.MAIN_BUTTONS,
      saved: "account.card_links_saved",
      // The links are part of what a card draws, so the cards are redrawn.
      redraw: () => {
        LibraryScreen.render();
        if ( DiscoverScreen.meta ) DiscoverScreen.render();
        PlaylistsScreen.render();
      },
    } );
  },

  // A tickable, orderable list of links saved in one Prefs ui key: chosen
  // ones first with up/down buttons (a phone can't drag), then the rest.
  initLinkList( options ) {
    const box = Dom.get( options.prefix );
    const apply = ( list ) => {
      Prefs.setUi( options.pref , list );
      render();
      options.redraw();
    };
    const change = ( list ) => {
      const before = options.get();
      apply( list );
      Undo.record( {
        label: I18n.get( options.saved ),
        toast: true,
        undo: () => apply( before ),
        redo: () => apply( list ),
      } );
    };
    const render = () => {
      Dom.clear( box );
      const chosen = options.get();
      const rest = Vocab.LINK_BUTTONS.filter( ( id ) => chosen.indexOf( id ) < 0 );
      chosen.concat( rest ).forEach( ( id ) => {
        const at = chosen.indexOf( id );
        const on = at >= 0;
        const boxId = options.prefix + "-" + id;
        const check = Dom.el( "input" , { class: "form-check-input" , attrs: { type: "checkbox" , id: boxId } } );
        check.checked = on;
        check.addEventListener( "change" , () => {
          change( check.checked ? chosen.concat( [ id ] ) : chosen.filter( ( each ) => each !== id ) );
        } );
        const mover = ( direction , icon ) => Dom.el( "button" , {
          class: "btn btn-sm btn-outline-secondary",
          attrs: { type: "button" , "aria-label": I18n.get( "customize.move_" + direction ) , title: I18n.get( "customize.move_" + direction ) },
          children: [ Card.icon( icon ) ],
          on: { click: () => {
            const to = direction === "up" ? at - 1 : at + 1;
            if ( to < 0 || to >= chosen.length ) return;
            const list = chosen.slice();
            list.splice( to , 0 , list.splice( at , 1 )[ 0 ] );
            change( list );
          } },
        } );
        box.appendChild( Dom.el( "li" , { class: "list-group-item choice" + ( on ? "" : " is-off" ) , children: [
          Dom.el( "div" , { class: "form-check mb-0 flex-grow-1" , children: [
            check,
            Dom.el( "label" , { class: "form-check-label" , attrs: { for: boxId } , children: [
              Card.icon( Vocab.BUTTONS[ id ].icon ),
              Dom.el( "span" , { text: " " + I18n.get( "card.button_" + id ) } ),
            ] } ),
          ] } ),
          on ? Dom.el( "div" , { class: "btn-group" , children: [ mover( "up" , "arrow-up" ) , mover( "down" , "arrow-down" ) ] } ) : Dom.el( "span" ),
        ] } ) );
      } );
    };
    Dom.get( options.prefix + "-reset" ).addEventListener( "click" , () => change( options.defaults.slice() ) );
    render();
  },

  async onRename( event ) {
    event.preventDefault();
    const value = Dom.get( "display-name" ).value.trim();
    const previous = this.currentUser.display_name;
    if ( value === previous ) {
      Dom.toast( I18n.get( "ui.unchanged" ) , "ok" );
      return;
    }
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

  // A fresh link for this account, to open on another device: once, or
  // several times until it expires. The server only allows it from a browser
  // session, never an API key.
  async onMyLoginLink() {
    const issued = await Dom.form( {
      title: I18n.get( "account.device_heading" ),
      submit: I18n.get( "login_links.make_button" ),
      fields: LoginLinks.fields(),
      save: ( values ) => Api.createMyLoginLink( LoginLinks.body( values.uses , values.expires ) ),
    } );
    if ( !issued ) return;
    Dom.text( Dom.get( "my-link-value" ) , window.location.origin + issued.login_path );
    Dom.text( Dom.get( "my-link-notice" ) , I18n.get( "account.device_link_notice" ).replace( "{summary}" , () => LoginLinks.summary( issued ) ) );
    Qr.hide( Dom.get( "my-link-qr" ) );
    Dom.show( Dom.get( "my-link-box" ) , true );
    await this.refreshMyLiveLink();
    if ( this.currentUser.role === "admin" ) await this.refreshUsers();
  },

  // The link this account could still sign in with, above the button.
  showMyLiveLink( link ) {
    Dom.show( Dom.get( "my-live-link" ) , Boolean( link ) );
    if ( link ) Dom.text( Dom.get( "my-live-link-text" ) , LoginLinks.live( link , "my_live" ) );
  },

  async refreshMyLiveLink() {
    try {
      const me = await Api.me();
      this.showMyLiveLink( me.login_link );
    } catch ( error ) { /* the line is a convenience; the next load shows it */ }
  },

  async onCancelMyLoginLink() {
    if ( !( await Dom.confirm( I18n.get( "login_links.my_cancel_confirm" ) ) ) ) return;
    try {
      await Api.cancelMyLoginLink();
      this.showMyLiveLink( null );
      Dom.show( Dom.get( "my-link-box" ) , false );
      if ( this.currentUser.role === "admin" ) await this.refreshUsers();
      Dom.toast( I18n.get( "login_links.my_cancelled_toast" ) , "ok" );
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
    const options = LoginLinks.body( Dom.get( "new-uses" ).value , Dom.get( "new-expires" ).value );
    try {
      const created = await Api.createUser( name , role , options );
      this.showLoginLink( created , name );
      Dom.get( "new-name" ).value = "";
      await this.refreshUsers();
    } catch ( error ) {
      this.showError( error.message );
    }
  },

  // The server returns a path, not a full URL: behind a reverse proxy it does
  // not reliably know its own public origin, whereas the browser always does.
  // issued is the server's answer: the path and what the link allows.
  showLoginLink( issued , name ) {
    const box = Dom.get( "login-link-box" );
    Dom.text( Dom.get( "login-link-for" ) , I18n.get( "admin.link_for" ).replace( "{name}" , () => name ) );
    Dom.text( Dom.get( "login-link-notice" ) , I18n.get( "admin.link_notice" ).replace( "{summary}" , () => LoginLinks.summary( issued ) ) );
    Dom.text( Dom.get( "login-link-value" ) , window.location.origin + issued.login_path );
    Qr.hide( Dom.get( "login-link-qr" ) );
    Dom.show( box , true );
    // The row that asked for it may be a long way down the Users table.
    Dom.reveal( box );
  },

  async onCopyLink() {
    await Dom.copy( Dom.get( "login-link-value" ) );
  },

  // A name or a role shows on the other admin screens too: All keys lists
  // whose each key is, and a link stops when its maker stops being an admin.
  async refreshAfterUserChange() {
    await App.refreshUsers();
    if ( App.currentUser.api_keys_enabled ) await Keys.refreshAll();
    if ( App.currentUser.invite_links_enabled !== false ) await Invites.refresh();
  },

  async refreshUsers() {
    const body = Dom.get( "users-table" ).querySelector( "tbody" );
    await Pager.load( "users-table" , "users" , ( offset ) => Api.listUsers( offset , Pager.params( "users-table" ) ) , function ( user ) {
      const statusKey = user.disabled ? "admin.status_disabled" : "admin.status_active";
      const statusTone = user.disabled ? "secondary" : "success";

      const reissueButton = Dom.el( "button" , {
        class: "btn btn-sm btn-outline-secondary",
        text: I18n.get( "admin.reissue_button" ),
        on: { click: async function () {
          const issued = await Dom.form( {
            title: I18n.get( "admin.reissue_heading" ).replace( "{name}" , () => user.display_name ),
            submit: I18n.get( "login_links.make_button" ),
            fields: LoginLinks.fields( I18n.get( "admin.reissue_confirm" ).replace( "{name}" , () => user.display_name ) ),
            save: ( values ) => Api.reissueLogin( user.id , LoginLinks.body( values.uses , values.expires ) ),
          } );
          if ( !issued ) return;
          App.showLoginLink( issued , user.display_name );
          await App.refreshUsers();
          if ( user.id === App.currentUser.id ) await App.refreshMyLiveLink();
        } },
      } );

      // A link they could still use: stop it without making another.
      const cancelLinkButton = !user.login_link ? null : Dom.el( "button" , {
        class: "btn btn-sm btn-outline-danger",
        text: I18n.get( "login_links.cancel_button" ),
        on: { click: async function () {
          const question = I18n.get( "login_links.cancel_confirm" ).replace( "{name}" , () => user.display_name );
          if ( !( await Dom.confirm( question ) ) ) return;
          try {
            await Api.cancelLoginLink( user.id );
            // The box may still be showing the link just cancelled.
            Dom.show( Dom.get( "login-link-box" ) , false );
            await App.refreshUsers();
            if ( user.id === App.currentUser.id ) App.showMyLiveLink( null );
            Dom.toast( I18n.get( "login_links.cancelled_toast" ).replace( "{name}" , () => user.display_name ) , "ok" );
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
          if ( !( await Dom.confirm( question ) ) ) return;
          try {
            await Api.revokeAccess( user.id );
            if ( App.currentUser.api_keys_enabled ) await Keys.refreshAll();
            Dom.toast( I18n.get( "admin.revoked_toast" ).replace( "{name}" , () => user.display_name ) , "ok" );
          } catch ( error ) { App.showError( error.message ); }
        } },
      } );

      // Disabling asks first and is not undoable, like a revoke: it ends their
      // sessions and unused links, and enabling does not bring those back.
      const toggleButton = isProtected ? null : Dom.el( "button" , {
        class: "btn btn-sm btn-outline-secondary",
        text: I18n.get( user.disabled ? "admin.enable_button" : "admin.disable_button" ),
        on: { click: async function () {
          if ( !user.disabled ) {
            const question = I18n.get( "admin.disable_confirm" ).replace( "{name}" , user.display_name );
            if ( !( await Dom.confirm( question ) ) ) return;
          }
          try {
            await Api.setDisabled( user.id , !user.disabled );
            await App.refreshUsers();
            Dom.toast( I18n.get( user.disabled ? "admin.enabled_toast" : "admin.disabled_toast" ).replace( "{name}" , user.display_name ) , "ok" );
          } catch ( error ) { App.showError( error.message ); }
        } },
      } );

      // Who may change what follows the delete rules, but any admin may make
      // another. Both ask first and neither can undo: becoming an admin ends
      // their sessions, which nothing brings back.
      const mayManage = user.role !== "admin" || App.currentUser.is_owner;
      const newRole = user.role === "admin" ? "user" : "admin";
      const roleButton = isProtected || !mayManage ? null : Dom.el( "button" , {
        class: "btn btn-sm btn-outline-secondary",
        text: I18n.get( "admin.make_" + newRole + "_button" ),
        on: { click: async function () {
          const question = I18n.get( "admin.make_" + newRole + "_confirm" ).replace( "{name}" , () => user.display_name );
          if ( !( await Dom.confirm( question ) ) ) return;
          try {
            await Api.setUserRole( user.id , newRole );
            await App.refreshAfterUserChange();
            Dom.toast( I18n.get( "admin.role_changed_toast" ).replace( "{name}" , () => user.display_name ).replace( "{role}" , newRole ) , "ok" );
          } catch ( error ) { App.showError( error.message ); }
        } },
      } );

      // The Showing picker for an ordinary user: an admin grants it, and says
      // whose lists they start on. Admins always have it, so it is not offered.
      const showingButton = user.role === "admin" ? null : Dom.el( "button" , {
        class: "btn btn-sm btn-outline-secondary",
        text: I18n.get( "admin.showing_button" ),
        on: { click: async function () {
          const before = { allowed: Boolean( user.can_show_others ) , subject: user.default_subject == null ? null : user.default_subject , locked: Boolean( user.showing_locked ) };
          const people = ( Library.people || [] ).filter( ( person ) => person.id !== user.id );
          const after = await Dom.form( {
            title: I18n.fill( "admin.showing_heading" , { name: user.display_name } ),
            fields: [
              { name: "allowed" , type: "checkbox" , label: I18n.get( "admin.showing_label" ) , value: before.allowed , help: I18n.get( "admin.showing_help" ) },
              { name: "subject" , type: "select" , label: I18n.get( "admin.starts_on_label" ) , value: before.subject == null ? "" : String( before.subject ) ,
                help: I18n.get( "admin.starts_on_help" ) ,
                options: [ { value: "" , label: I18n.get( "admin.starts_on_own" ) } ].concat( people.map( ( person ) => ( { value: String( person.id ) , label: person.display_name } ) ) ) },
              { name: "locked" , type: "checkbox" , label: I18n.get( "admin.showing_lock_label" ) , value: before.locked , help: I18n.get( "admin.showing_lock_help" ) },
            ],
            save: async ( values ) => {
              // Starting on someone else needs Showing, so choosing someone grants it.
              const subject = values.subject !== "" ? Number( values.subject ) : null;
              const allowed = values.allowed || subject !== null;
              // Nothing to lock without Showing and with no one chosen (the server agrees).
              const wanted = { allowed: allowed , subject: subject , locked: Boolean( values.locked ) && ( allowed || subject !== null ) };
              await Api.setUserShowing( user.id , wanted.allowed , wanted.subject , wanted.locked );
              return wanted;
            },
          } );
          if ( !after ) return;
          const apply = async ( state ) => { await Api.setUserShowing( user.id , state.allowed , state.subject , state.locked ); await App.refreshUsers(); };
          await App.refreshUsers();
          Undo.record( {
            label: I18n.get( "admin.showing_undo" ),
            undo: () => apply( before ),
            redo: () => apply( after ),
          } );
          Dom.toast( I18n.fill( "admin.showing_changed_toast" , { name: user.display_name } ) , "ok" );
        } },
      } );

      // Your own name is on the Account screen. It edits in place, and is
      // built with textContent: a display name is user-controlled input.
      const nameCell = isSelf || !mayManage ? Dom.el( "span" , { text: user.display_name } ) : Dom.editable( user.display_name , {
        label: I18n.get( "admin.table_name" ),
        maxLength: 80,
        save: async function ( value ) {
          const previous = user.display_name;
          await Api.renameUser( user.id , value , previous );
          user.display_name = value;
          Undo.record( {
            label: I18n.get( "undo.rename" ),
            toast: true,
            undo: async () => { await Api.renameUser( user.id , previous , value ); await App.refreshAfterUserChange(); },
            redo: async () => { await Api.renameUser( user.id , value , previous ); await App.refreshAfterUserChange(); },
          } );
        },
      } );

      // Deleting removes the account and everything it held, for good. Any
      // admin may delete a user; only the owner may delete another admin.
      const canDelete = !isProtected && ( user.role !== "admin" || App.currentUser.is_owner );
      const deleteButton = !canDelete ? null : Dom.el( "button" , {
        class: "btn btn-sm btn-outline-danger",
        text: I18n.get( "admin.delete_button" ),
        on: { click: async function () {
          const question = I18n.get( "admin.delete_confirm" ).replace( "{name}" , user.display_name );
          if ( !( await Dom.confirm( question ) ) ) return;
          try {
            await Api.deleteUser( user.id );
            await App.refreshUsers();
            if ( App.currentUser.api_keys_enabled ) await Keys.refreshAll();
          } catch ( error ) { App.showError( error.message ); }
        } },
      } );

      // Only for someone who lost their phone and recovery codes. Who may
      // reset whom follows the delete rules; the owner's is shell-only.
      const canReset = user.two_factor && !isProtected && ( user.role !== "admin" || App.currentUser.is_owner );
      const resetButton = !canReset ? null : Dom.el( "button" , {
        class: "btn btn-sm btn-outline-danger",
        text: I18n.get( "admin.reset_two_factor_button" ),
        on: { click: async function () {
          const question = I18n.get( "admin.reset_two_factor_confirm" ).replace( "{name}" , user.display_name );
          if ( !( await Dom.confirm( question ) ) ) return;
          try {
            await Api.resetTwoFactor( user.id );
            await App.refreshUsers();
            Dom.toast( I18n.get( "admin.two_factor_reset_toast" ).replace( "{name}" , () => user.display_name ) , "ok" );
          } catch ( error ) { App.showError( error.message ); }
        } },
      } );

      // Where they are signed in. The owner's are the owner's own, which the
      // server would refuse.
      const sessionsButton = user.owner && !App.currentUser.is_owner ? null : Dom.el( "button" , {
        class: "btn btn-sm btn-outline-secondary",
        text: I18n.get( "admin.sessions_button" ),
        on: { click: () => Sessions.showFor( user ) },
      } );

      // The owner's per-account password switch. Everyone else gets a 404
      // from the server, so it is not offered.
      const canBlock = App.currentUser.is_owner && App.currentUser.passwords_enabled;
      const passwordButton = !canBlock ? null : Dom.el( "button" , {
        class: "btn btn-sm btn-outline-secondary",
        text: I18n.get( user.password_blocked ? "admin.allow_password_button" : "admin.block_password_button" ),
        on: { click: async function () {
          try {
            await Api.setPasswordAccess( user.id , user.password_blocked );
            await App.refreshUsers();
          } catch ( error ) { App.showError( error.message ); }
        } },
      } );

      const ownerLabel = I18n.get( "admin.owner_label" );
      const roleText = user.owner && ownerLabel !== "" ? user.role + " (" + ownerLabel + ")" : user.role;

      // Built with createElement + textContent, never an HTML string: a
      // display name is user-controlled input.
      // The username is what they sign in with, so it is under the name, not
      // instead of it. An account with no password has none.
      const username = user.username ? Dom.el( "div" , { class: "small text-body-secondary" , text: user.username } ) : null;
      const status = [ Dom.badge( I18n.get( statusKey ) , statusTone ) ];
      if ( user.two_factor ) status.push( Dom.el( "span" , { class: "ms-1" , children: [ Dom.badge( I18n.get( "admin.two_factor_badge" ) , "secondary" ) ] } ) );
      if ( user.role !== "admin" && user.can_show_others ) {
        const start = ( Library.people || [] ).find( ( person ) => person.id === user.default_subject );
        let words = start ? I18n.fill( "admin.showing_badge_on" , { name: start.display_name } ) : I18n.get( "admin.showing_badge" );
        if ( user.showing_locked ) words += " · " + I18n.get( "admin.showing_badge_locked" );
        status.push( Dom.el( "span" , { class: "ms-1" , children: [ Dom.badge( words , "info" ) ] } ) );
      }
      if ( user.login_link ) status.push( Dom.el( "div" , { class: "small text-body-secondary" , text: LoginLinks.live( user.login_link , "live" ) } ) );

      body.appendChild( Dom.el( "tr" , { children: [
        Dom.el( "td" , { children: [ nameCell , username ].filter( Boolean ) } ),
        Dom.el( "td" , { text: roleText } ),
        Dom.el( "td" , { children: status } ),
        Dom.el( "td" , { class: "text-nowrap" , children: [ Dom.when( user.created_at ) ] } ),
        Dom.el( "td" , { children: [
          Dom.rowActions( user.display_name , [
            reissueButton,
            cancelLinkButton,
            sessionsButton,
            passwordButton,
            roleButton,
            showingButton,
            resetButton,
            revokeButton,
            toggleButton,
            deleteButton,
          ] ),
        ] } ),
      ] } ) );
    } );
  },

  // message may be an error code the server answered with (pin_wrong,
  // invite_link_full, ...); language.yaml's errors section words those.
  showError( message ) {
    const banner = Dom.get( "error-banner" );
    const text = Dom.get( "error-banner-text" );
    const worded = message ? I18n.get( "errors." + message ) : "";
    Dom.text( text , worded || message || I18n.get( "errors.generic" ) );
    const copy = Dom.get( "error-copy-button" );
    Dom.show( copy , I18n.get( "ui.copy" ) !== "" );
    copy.onclick = () => Dom.copy( text );
    // It stays until it is closed or replaced: it may hold a reference to quote.
    Dom.show( banner , true );
    // It sits at the top of the screen, which may be scrolled well past.
    Dom.reveal( banner );
  },

  // A refusal about one field goes beside that field, and anything else to the
  // banner. fields maps error codes to input ids. A field that is not on screen
  // cannot show it, so that goes to the banner too.
  showFieldError( message , fields ) {
    const input = Dom.get( fields[ message ] );
    if ( !input || input.offsetParent === null ) {
      this.showError( message );
      return;
    }
    Dom.fieldError( input , Dom.worded( { message: message } ) );
    input.focus();
  },
};

document.addEventListener( "DOMContentLoaded" , function () {
  App.init();
} );
