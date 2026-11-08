// Password sign-in: the form on the signed-out page, and the panel where a
// signed-in person sets a password. Both exist only while the owner has
// auth.passwords on, and the server says so.
//
// The password itself never leaves this page. What is sent is a digest of it
// (see digest below), which the server then bcrypts -- so a compromised server
// or a stray log cannot expose a password someone uses elsewhere. The digest
// still works as a password on the wire, so this does not replace HTTPS.
//
// ITERATIONS and the shape of the salt are part of every stored password:
// changing either makes everyone's password stop working.
const Password = {
  MIN_LENGTH: 12,
  // Which field each refusal of the panel's form is about.
  fields: {
    password_too_short: "password-new",
    password_mismatch: "password-confirm",
    bad_username: "password-username",
    username_taken: "password-username",
    two_factor_wrong: "password-code",
  },
  ITERATIONS: 600000,
  options: null,
  me: null,

  async loadOptions() {
    if ( this.options === null ) this.options = await Api.loginOptions();
    return this.options;
  },

  normalizeUsername( value ) {
    return value.trim().toLowerCase();
  },

  // PBKDF2 through WebCrypto, which browsers offer only on HTTPS and
  // localhost. There is no fallback on purpose: the alternative would be
  // sending the password itself.
  async digest( username , password ) {
    if ( !window.crypto || !window.crypto.subtle ) throw new Error( "insecure_context" );
    const options = await this.loadOptions();
    const encoder = new TextEncoder();
    // NFKC so the same password typed on two devices is the same bytes.
    const key = await window.crypto.subtle.importKey(
      "raw" , encoder.encode( password.normalize( "NFKC" ) ) , "PBKDF2" , false , [ "deriveBits" ]
    );
    const bits = await window.crypto.subtle.deriveBits( {
      name: "PBKDF2",
      hash: "SHA-256",
      salt: encoder.encode( options.salt + ":" + username ),
      iterations: this.ITERATIONS,
    } , key , 256 );
    const text = String.fromCharCode( ...new Uint8Array( bits ) );
    return btoa( text ).replace( /\+/g , "-" ).replace( /\//g , "_" ).replace( /=+$/ , "" );
  },

  // --- the signed-out page --------------------------------------------------

  async initLogin() {
    try {
      const options = await this.loadOptions();
      if ( !options.passwords ) return;
    } catch ( error ) {
      return; // Links still work; the form just is not offered.
    }
    Dom.show( Dom.get( "password-login" ) , true );
    Dom.onSubmit( Dom.get( "password-login-form" ) , this.onLogin.bind( this ) );
  },

  async onLogin( event ) {
    event.preventDefault();
    const username = this.normalizeUsername( Dom.get( "login-username" ).value );
    try {
      const digest = await this.digest( username , Dom.get( "login-password" ).value );
      const result = await Api.passwordLogin( username , digest );
      Dom.get( "login-password" ).value = "";
      if ( result.two_factor ) {
        TwoFactor.ask( result.challenge );
        return;
      }
      window.location.replace( "/" );
    } catch ( error ) {
      App.showError( error.message );
    }
  },

  // --- the signed-in panel --------------------------------------------------

  init( me ) {
    this.me = me;
    if ( !me.passwords_enabled || me.password_blocked || me.auth !== "session" ) return;
    Dom.show( Dom.get( "password-panel" ) , true );
    Dom.onSubmit( Dom.get( "password-form" ) , this.onSave.bind( this ) );
    Dom.onPress( Dom.get( "password-remove-button" ) , this.onRemove.bind( this ) );
    Dom.get( "password-username" ).value = me.username;
    this.render();
  },

  render() {
    if ( this.me === null ) return;
    const status = Dom.get( "password-status" );
    Dom.text( status , I18n.get( this.me.has_password ? "password.status_set" : "password.status_none" ) );
    status.className = "badge " + ( this.me.has_password ? "text-bg-success" : "text-bg-secondary" );
    Dom.show( Dom.get( "password-remove-button" ) , this.me.has_password && I18n.get( "password.remove_button" ) !== "" );
    Dom.show( Dom.get( "password-code-row" ) , this.needsCode() );
  },

  needsCode() {
    return this.me.two_factor && this.me.two_factor_enabled;
  },

  async onSave( event ) {
    event.preventDefault();
    const username = this.normalizeUsername( Dom.get( "password-username" ).value );
    const password = Dom.get( "password-new" ).value;
    // Mending one field can settle a problem shown on another.
    [ "password-username" , "password-new" , "password-confirm" , "password-code" ].forEach( function ( id ) {
      Dom.clearFieldError( Dom.get( id ) );
    } );
    if ( password.length < this.MIN_LENGTH ) {
      App.showFieldError( "password_too_short" , this.fields );
      return;
    }
    if ( password !== Dom.get( "password-confirm" ).value ) {
      App.showFieldError( "password_mismatch" , this.fields );
      return;
    }
    try {
      const digest = await this.digest( username , password );
      await Api.setPassword( username , digest , Dom.get( "password-code" ).value );
      this.me.has_password = true;
      this.me.username = username;
      Dom.get( "password-username" ).value = username;
      this.saved();
    } catch ( error ) {
      App.showFieldError( error.message , this.fields );
    }
  },

  async onRemove() {
    const question = I18n.get( "password.remove_confirm" );
    if ( !( await Dom.confirm( question ) ) ) return;
    try {
      await Api.setPassword( "" , "" , Dom.get( "password-code" ).value );
      this.me.has_password = false;
      this.saved();
    } catch ( error ) {
      App.showFieldError( error.message , this.fields );
    }
  },

  saved() {
    [ "password-new" , "password-confirm" , "password-code" ].forEach( function ( id ) {
      Dom.get( id ).value = "";
    } );
    this.render();
    Dom.toast( I18n.get( "ui.saved" ) , "ok" );
  },
};
