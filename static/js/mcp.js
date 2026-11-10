// The MCP card on Account: setting up Claude Code, Claude Desktop or any
// other MCP client to use this app through POST /mcp.
//
// It makes nothing the API keys card cannot. /mcp takes an ordinary API key,
// so this is that card's create call plus the setup each client wants, with
// the endpoint and the new key already written in. Until a key is made here
// the setup shows a placeholder, for someone who already has a key.
//
// The key is held only in this page, in memory, the same "shown once" as on
// the API keys card. Closing the notice forgets it and puts the placeholder
// back. app.js calls Mcp.init( me ) once it knows who is signed in.
const Mcp = {
  me: null,
  // The key made here, while it is still shown. Never stored anywhere.
  credential: "",
  // Whether the key name is still the one this card filled in, so picking
  // another client can rename it without overwriting what someone typed.
  nameIsOurs: true,

  init( me ) {
    this.me = me;
    // Both switches: /mcp answers 404 without either, and a setup for a
    // dead endpoint is worse than no card.
    if ( me.mcp_enabled !== true || me.api_keys_enabled === false ) return;

    Dom.show( Dom.get( "mcp-panel" ) , true );
    // What an agent can call: mcp.json in app.repo, else the server's own.
    if ( me.mcp_url ) {
      Dom.get( "mcp-spec-link" ).setAttribute( "href" , me.mcp_url );
      Dom.show( Dom.get( "mcp-spec-line" ) , true );
    }
    Dom.text( Dom.get( "mcp-endpoint" ) , this.endpoint() );
    Dom.show( Dom.get( "mcp-key-role-field" ) , me.role === "admin" );
    Dom.get( "mcp-endpoint-copy" ).addEventListener( "click" , () => Dom.copy( Dom.get( "mcp-endpoint" ) ) );
    Dom.get( "mcp-snippet-copy" ).addEventListener( "click" , () => Dom.copy( Dom.get( "mcp-snippet" ) ) );
    Dom.get( "mcp-key-forget" ).addEventListener( "click" , () => this.forget() );
    Dom.get( "mcp-clients" ).addEventListener( "change" , () => this.onClientChange() );
    Dom.get( "mcp-key-name" ).addEventListener( "input" , () => { this.nameIsOurs = false; } );
    Dom.onSubmit( Dom.get( "mcp-key-form" ) , this.onCreate.bind( this ) );
    this.onClientChange();
  },

  // Where the browser reached this app is where an agent on the same machine
  // or network reaches it too, proxy or not.
  endpoint() {
    return window.location.origin + "/mcp";
  },

  client() {
    const picked = document.querySelector( "input[name=mcp-client]:checked" );
    return picked ? picked.value : "claude_code";
  },

  // The name the server goes by in the client's config: the app's title,
  // lower case, with anything but letters and digits as dashes.
  serverName() {
    const slug = I18n.get( "app.title" ).toLowerCase().replace( /[^a-z0-9]+/g , "-" ).replace( /^-+|-+$/g , "" );
    return slug || "app";
  },

  onClientChange() {
    const client = this.client();
    if ( this.nameIsOurs ) Dom.get( "mcp-key-name" ).value = I18n.get( "mcp.client_" + client );
    Dom.text( Dom.get( "mcp-hint" ) , I18n.get( "mcp.hint_" + client ) );
    this.render();
  },

  // The setup for the chosen client. Each is what that client's own docs
  // ask for: a remote HTTP server and one Authorization header. Claude
  // Desktop's config file only starts local programs, so it goes through
  // mcp-remote, with the header in env so the space in it survives Windows.
  snippet( client , url , key ) {
    const name = this.serverName();
    const bearer = "Bearer " + key;
    const json = ( value ) => JSON.stringify( value , null , 2 );
    const remote = { [ name ]: { type: "http" , url: url , headers: { Authorization: bearer } } };
    switch ( client ) {
      case "claude_code":
        return "claude mcp add --transport http " + name + " " + url + " --header \"Authorization: " + bearer + "\"";
      case "claude_desktop":
        return json( { mcpServers: { [ name ]: {
          command: "npx",
          args: [ "-y" , "mcp-remote" , url , "--header" , "Authorization:${AUTH_HEADER}" ],
          env: { AUTH_HEADER: bearer },
        } } } );
      default:
        return json( { mcpServers: remote } );
    }
  },

  render() {
    const key = this.credential || I18n.get( "mcp.placeholder_key" );
    Dom.text( Dom.get( "mcp-snippet" ) , this.snippet( this.client() , this.endpoint() , key ) );
  },

  forget() {
    this.credential = "";
    Dom.show( Dom.get( "mcp-key-notice" ) , false );
    this.render();
    Dom.get( "mcp-key-name" ).focus();
  },

  async onCreate( event ) {
    event.preventDefault();
    const name = Dom.get( "mcp-key-name" ).value.trim();
    const role = this.me.role === "admin" ? Dom.get( "mcp-key-role" ).value : "user";
    // Blank is the configured default and 0 is never, as on the API keys card.
    const rawDays = Dom.get( "mcp-key-days" ).value.trim();
    const expiresInDays = rawDays === "" ? null : Number( rawDays );
    try {
      const created = await Api.createKey( name , role , expiresInDays );
      this.credential = created.credential;
      this.render();
      Dom.text( Dom.get( "mcp-key-notice-text" ) , I18n.get( "mcp.key_notice" ).replace( "{name}" , () => name ) );
      Dom.show( Dom.get( "mcp-key-notice" ) , true );
      Dom.get( "mcp-key-days" ).value = "";
      Dom.reveal( Dom.get( "mcp-snippet" ) );
      await Keys.refreshBoth();
    } catch ( error ) {
      App.showError( error.message );
    }
  },
};
