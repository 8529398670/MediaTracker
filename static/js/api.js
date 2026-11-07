// Every call to the server goes through here, so the things that are easy to
// forget -- sending the cookie, attaching the CSRF token, turning a non-2xx
// response into a real Error -- happen once instead of at each call site.
const Api = {
  csrfToken: null,

  async request( path , options ) {
    const settings = options || {};
    const response = await fetch( path , {
      method: settings.method || "GET",
      // The session cookie is the only credential; without this an
      // authenticated request silently arrives as an anonymous one.
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: settings.body ? JSON.stringify( settings.body ) : undefined,
    } );

    let payload = {};
    try {
      payload = await response.json();
    } catch ( parseError ) {
      payload = {};
    }

    if ( !response.ok ) {
      const error = new Error( payload.error || response.statusText );
      error.status = response.status;
      error.payload = payload;
      throw error;
    }
    return payload;
  },

  // Any state-changing call carries the per-session CSRF token in the body.
  // Wrapping it here means a new endpoint cannot forget it.
  async post( path , body ) {
    return this.request( path , {
      method: "POST",
      body: Object.assign( {} , body || {} , { csrf_token: this.csrfToken } ),
    } );
  },

  async me() {
    try {
      const payload = await this.request( "/api/me" );
      this.csrfToken = payload.csrf_token;
      return payload;
    } catch ( error ) {
      if ( error.status === 401 ) return { authenticated: false };
      throw error;
    }
  },

  // The one POST with no CSRF token: there is no session yet to hold one.
  // The server guards it by requiring this JSON body instead -- see the
  // login route on the server side.
  login( credential ) {
    return this.request( "/api/login" , { method: "POST" , body: { credential: credential } } );
  },

  // Invite links: no session yet either, so the same JSON-body rule as
  // login() applies. The credential always goes in the body.
  joinInfo( credential )                { return this.request( "/api/join/info" , { method: "POST" , body: { credential: credential } } ); },
  joinMatch( credential , name )        { return this.request( "/api/join/match" , { method: "POST" , body: { credential: credential , display_name: name } } ); },
  joinCreate( credential , name )       { return this.request( "/api/join/create" , { method: "POST" , body: { credential: credential , display_name: name } } ); },
  joinClaim( credential , userId , pin ) {
    return this.request( "/api/join/claim" , { method: "POST" , body: { credential: credential , user_id: userId , pin: pin || "" } } );
  },

  // expect is the name the caller believes is stored. The server refuses
  // with a 409 when it is not, so an undo never overwrites a rename made
  // somewhere else in the meantime.
  rename( displayName , expect ) {
    const body = { display_name: displayName };
    if ( expect !== undefined ) body.expect = expect;
    return this.post( "/api/account/rename" , body );
  },
  setPin( pin )                { return this.post( "/api/account/pin" , { pin: pin } ); },
  createMyLoginLink()          { return this.post( "/api/account/login-link" ); },
  logout()                     { return this.post( "/api/logout" ); },
  listTeam()                   { return this.request( "/api/team" ); },
  listUsers()                  { return this.request( "/api/admin/users" ); },
  createUser( name , role )    { return this.post( "/api/admin/users" , { display_name: name , role: role } ); },
  reissueLogin( userId )       { return this.post( "/api/admin/users/" + userId + "/reissue-login" ); },
  setDisabled( userId , flag ) { return this.post( "/api/admin/users/" + userId + "/disabled" , { disabled: flag } ); },
  revokeAccess( userId )       { return this.post( "/api/admin/users/" + userId + "/revoke-access" ); },
  deleteUser( userId )         { return this.post( "/api/admin/users/" + userId + "/delete" ); },
  listInvites()                { return this.request( "/api/admin/invite-links" ); },
  createInvite( label , maxUses , days ) {
    return this.post( "/api/admin/invite-links" , { label: label , max_uses: maxUses , days: days } );
  },
  revokeInvite( linkId )       { return this.post( "/api/admin/invite-links/" + encodeURIComponent( linkId ) + "/revoke" ); },
  deleteInvite( linkId )       { return this.post( "/api/admin/invite-links/" + encodeURIComponent( linkId ) + "/delete" ); },
  restoreInvite( linkId )      { return this.post( "/api/admin/invite-links/" + encodeURIComponent( linkId ) + "/restore" ); },

  // API keys. createKey's expiresInDays is passed through as-is including null,
  // because the server reads absent as "use the default" and 0 as "never
  // expires" -- collapsing them here would lose the distinction.
  listKeys()                   { return this.request( "/api/keys" ); },
  createKey( name , role , expiresInDays ) {
    return this.post( "/api/keys" , { name: name , role: role , expires_in_days: expiresInDays } );
  },
  revokeKey( keyId )           { return this.post( "/api/keys/" + encodeURIComponent( keyId ) + "/revoke" ); },
  deleteKey( keyId )           { return this.post( "/api/keys/" + encodeURIComponent( keyId ) + "/delete" ); },
  restoreKey( keyId )          { return this.post( "/api/keys/" + encodeURIComponent( keyId ) + "/restore" ); },
  listAllKeys()                { return this.request( "/api/admin/keys" ); },
  revokeAnyKey( keyId )        { return this.post( "/api/admin/keys/" + encodeURIComponent( keyId ) + "/revoke" ); },
  deleteAnyKey( keyId )        { return this.post( "/api/admin/keys/" + encodeURIComponent( keyId ) + "/delete" ); },
  restoreAnyKey( keyId )       { return this.post( "/api/admin/keys/" + encodeURIComponent( keyId ) + "/restore" ); },

  // -- the media library -------------------------------------------------
  //
  // Personal calls (state, verdicts) name whose state they are about with
  // ?user=<id>: the signed-in person unless an admin is acting for someone
  // (see static/js/media/acting.js). The server refuses anyone else.
  subject: null,
  forSubject( path ) {
    if ( this.subject == null ) return path;
    return path + ( path.indexOf( "?" ) >= 0 ? "&" : "?" ) + "user=" + encodeURIComponent( this.subject );
  },
  id( value )                  { return encodeURIComponent( value ); },

  library( since )             { return this.request( this.forSubject( "/api/library" + ( since != null ? "?since=" + since : "" ) ) ); },
  vocab()                      { return this.request( "/api/vocab" ); },
  createTitle( title , state , force ) {
    return this.post( this.forSubject( "/api/titles" ) , { title: title , state: state || {} , force: Boolean( force ) } );
  },
  checkTitle( title )          { return this.post( "/api/titles/check" , { title: title } ); },
  updateTitle( id , set , expect ) { return this.post( "/api/titles/" + this.id( id ) + "/update" , { set: set , expect: expect } ); },
  deleteTitle( id )            { return this.post( "/api/titles/" + this.id( id ) + "/delete" ); },
  restoreTitle( id )           { return this.post( "/api/titles/" + this.id( id ) + "/restore" ); },
  bulkTitles( ids , op , value ) { return this.post( "/api/titles/bulk" , { ids: ids , op: op , value: value } ); },
  enrichTitle( id , refresh )  { return this.post( "/api/titles/" + this.id( id ) + "/enrich" , { refresh: Boolean( refresh ) } ); },
  setState( id , set , expect ) { return this.post( this.forSubject( "/api/state/" + this.id( id ) ) , { set: set , expect: expect } ); },
  setStates( changes )         { return this.post( this.forSubject( "/api/state/bulk" ) , { changes: changes } ); },
  prefs()                      { return this.request( "/api/prefs" ); },
  savePrefs( changes )         { return this.post( "/api/prefs" , changes ); },
  views()                      { return this.request( "/api/views" ); },
  createView( view )           { return this.post( "/api/views" , view ); },
  updateView( id , view )      { return this.post( "/api/views/" + id + "/update" , view ); },
  deleteView( id )             { return this.post( "/api/views/" + id + "/delete" ); },
  restoreView( id )            { return this.post( "/api/views/" + id + "/restore" ); },
  reorderViews( ids )          { return this.post( "/api/views/reorder" , { ids: ids } ); },
  // Playlists are personal, so they follow the Showing picker like state.
  playlists()                  { return this.request( this.forSubject( "/api/playlists" ) ); },
  createPlaylist( name , items ) { return this.post( this.forSubject( "/api/playlists" ) , { name: name , items: items || [] } ); },
  reorderPlaylists( ids )      { return this.post( this.forSubject( "/api/playlists/reorder" ) , { ids: ids } ); },
  playlistCall( id , action , body ) { return this.post( this.forSubject( "/api/playlists/" + id + "/" + action ) , body ); },
  types()                      { return this.request( "/api/types" ); },
  saveType( type )             { return this.post( "/api/types" , type ); },
  deleteType( id , reassignTo ) { return this.post( "/api/types/" + this.id( id ) + "/delete" , { reassign_to: reassignTo || null } ); },
  restoreType( id )            { return this.post( "/api/types/" + this.id( id ) + "/restore" ); },
  sources()                    { return this.request( "/api/sources" ); },
  createSource( source )       { return this.post( "/api/sources" , source ); },
  deleteSource( id )           { return this.post( "/api/sources/" + this.id( id ) + "/delete" ); },
  restoreSource( id )          { return this.post( "/api/sources/" + this.id( id ) + "/restore" ); },
};
