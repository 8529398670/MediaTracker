// The About screen: app.description, the running version, app.repo and where
// to read the API reference. It is there only while app.show_about is on;
// the server sends all four in /api/me, so this asks for nothing more.
// app.js calls About.init( me ) once it knows who is signed in.
const About = {
  init( me ) {
    if ( me.show_about !== true ) return;
    const description = Dom.get( "about-description" );
    Dom.text( description , me.description || "" );
    Dom.show( description , Boolean( me.description ) );
    Dom.text( Dom.get( "about-version" ) , me.version || "" );
    this.link( "about-source" , me.repo , me.repo );
    this.link( "about-api" , me.openapi_url );
    this.link( "about-mcp" , me.mcp_enabled === true && me.api_keys_enabled !== false ? me.mcp_url : "" );
    Dom.show( Dom.get( "about-panel" ) , true );
  },

  // A link and its row, shown only when there is somewhere to go. text, when
  // given, replaces the link's label.
  link( id , href , text ) {
    const anchor = Dom.get( id );
    const shown = typeof href === "string" && href !== "";
    if ( shown ) anchor.setAttribute( "href" , href );
    if ( shown && text ) Dom.text( anchor , text );
    Dom.show( anchor.parentElement , shown );
    Dom.show( anchor.parentElement.previousElementSibling , shown );
  },
};
