// How many times a login link works and for how long -- the choices on the
// create-user form and in the New link and "Sign in on another device"
// dialogs -- and how a link is described afterwards. The server checks the
// same limits again (models.ResolveLoginLink).
const LoginLinks = {
  // "" is once. 0 is unlimited, as the API has it.
  USES: [ "" , "2" , "3" , "5" , "10" , "25" , "100" , "0" ],
  // Minutes; "" is the configured default, 0 never.
  EXPIRES: [
    [ "" , "expires_default" ],
    [ "30" , "expires_30m" ],
    [ "60" , "expires_1h" ],
    [ "1440" , "expires_1d" ],
    [ "10080" , "expires_7d" ],
    [ "43200" , "expires_30d" ],
    [ "129600" , "expires_90d" ],
    [ "0" , "expires_never" ],
  ],

  usesOptions() {
    return this.USES.map( ( value ) => ( { value: value , label: this.usesLabel( value ) } ) );
  },

  usesLabel( value ) {
    if ( value === "" ) return I18n.get( "login_links.uses_once" );
    if ( value === "0" ) return I18n.get( "login_links.uses_unlimited" );
    return I18n.get( "login_links.uses_times" ).replace( "{count}" , value );
  },

  expiresOptions() {
    return this.EXPIRES.map( ( [ value , key ] ) => ( { value: value , label: I18n.get( "login_links." + key ) } ) );
  },

  // The two Dom.form fields, for the dialogs.
  fields( help ) {
    return [
      { name: "uses" , type: "select" , label: I18n.get( "login_links.uses_label" ) , options: this.usesOptions() , value: "" },
      { name: "expires" , type: "select" , label: I18n.get( "login_links.expires_label" ) , options: this.expiresOptions() , value: "" ,
        help: [ I18n.get( "login_links.expires_help" ) , help || "" ].filter( Boolean ).join( " " ) },
    ];
  },

  // Fills a pair of <select>s already on the page (the create-user form).
  fill( usesSelect , expiresSelect ) {
    const options = ( select , list ) => select.replaceChildren( ...list.map(
      ( option ) => Dom.el( "option" , { text: option.label , attrs: { value: option.value } } ) ) );
    options( usesSelect , this.usesOptions() );
    options( expiresSelect , this.expiresOptions() );
  },

  // The request body fields for what was picked. Defaults are left out, so
  // the server's configured ones apply.
  body( uses , expires ) {
    const body = {};
    if ( uses !== "" && uses != null ) body.max_uses = Number( uses );
    if ( expires !== "" && expires != null ) body.expires_in_minutes = Number( expires );
    return body;
  },

  // "Works up to 5 times, until 14 Nov 2026, 09:30" -- for a link just made.
  summary( link ) {
    let works = I18n.get( "login_links.works_once" );
    if ( link.unlimited ) works = I18n.get( "login_links.works_unlimited" );
    else if ( link.max_uses > 1 ) works = I18n.get( "login_links.works_times" ).replace( "{count}" , String( link.max_uses ) );
    return works + ", " + this.expiry( link );
  },

  expiry( link ) {
    if ( !link.expires_at ) return I18n.get( "login_links.never_expires" );
    const date = new Date( link.expires_at ).toLocaleString( undefined , { dateStyle: "medium" , timeStyle: "short" } );
    return I18n.get( "login_links.until" ).replace( "{date}" , () => date );
  },

  // "Link: 2 of 5 used, until ..." -- a live link on a user's row. prefix is
  // "live" there and "my_live" on the Account screen.
  live( link , prefix ) {
    const key = "login_links." + prefix + ( link.unlimited ? "_unlimited" : "" );
    return I18n.get( key )
      .replace( "{used}" , String( link.uses ) )
      .replace( "{max}" , String( link.max_uses ) )
      .replace( "{expires}" , () => this.expiry( link ) );
  },
};
