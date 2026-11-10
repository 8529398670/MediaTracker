// The PIN card on the Account screen: what stands between "anyone holding the invite link" and
// "signed in as you". Only offered to non-admin accounts -- an admin can
// never be picked on the join page, so a PIN would protect nothing.
const Pin = {
  me: null,

  init( me ) {
    this.me = me;
    if ( me.account_role === "admin" || me.auth !== "session" || me.invite_links_enabled === false ) return;
    Dom.show( Dom.get( "pin-panel" ) , true );
    Dom.onSubmit( Dom.get( "pin-form" ) , this.onSave.bind( this ) );
    Dom.onPress( Dom.get( "pin-clear-button" ) , this.onClear.bind( this ) );
    this.render();
  },

  render() {
    const status = Dom.get( "pin-status" );
    Dom.text( status , I18n.get( this.me.has_pin ? "pin.status_set" : "pin.status_none" ) );
    status.className = "badge " + ( this.me.has_pin ? "text-bg-success" : "text-bg-secondary" );
    Dom.show( Dom.get( "pin-clear-button" ) , this.me.has_pin && I18n.get( "pin.clear_button" ) !== "" );
  },

  async onSave( event ) {
    event.preventDefault();
    await this.save( Dom.get( "pin-value" ).value );
  },

  async onClear() {
    if ( !( await Dom.confirm( I18n.get( "pin.clear_confirm" ) ) ) ) return;
    await this.save( "" , "pin.cleared" );
  },

  async save( pin , done = "ui.saved" ) {
    try {
      const result = await Api.setPin( pin );
      this.me.has_pin = result.has_pin;
      Dom.get( "pin-value" ).value = "";
      this.render();
      Dom.toast( I18n.get( done ) , "ok" );
    } catch ( error ) {
      App.showFieldError( error.message , { bad_pin: "pin-value" } );
    }
  },
};
