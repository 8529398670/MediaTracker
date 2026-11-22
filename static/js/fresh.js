// What changed while this tab was open.
//
// A tab can sit open for days, and everything /api/me said when the page loaded
// goes stale in that time. So coming back to it asks again, and acts on the
// answer: the session may have ended, maintenance may have started or finished,
// and the server may have been upgraded under a page that is still the old one.
//
// Only on coming back, not on a timer: a tab nobody is looking at has no reason
// to call the server, and calling would count as use and keep its session alive.
//
// An upgrade is also heard on any call: every API reply names the build that
// answered (X-App-Version, read by Api.request). Once a newer build is known,
// the next move to another screen is a real page load instead of an in-page
// switch, landing on the screen asked for, now running the new code -- the
// person never has to do anything. If they stay put, a toast offers the reload
// after toastAfterMs. Nothing reloads while something would be lost: an open
// dialog, or whatever a screen registered with holdWhile (an upload, unsaved
// settings).
const Fresh = {
  // No more often than this, so flicking between tabs is not a request each time.
  everyMs: 5 * 60 * 1000,
  // How long a newer build waits for a screen change before asking instead.
  toastAfterMs: 60 * 1000,
  asked: 0,
  version: "",
  newer: "",
  offered: "",
  holds: [],

  init( me ) {
    this.asked = Date.now();
    this.version = me.version;
    document.addEventListener( "visibilitychange" , () => {
      if ( !document.hidden ) this.check();
    } );
  },

  async check() {
    if ( Date.now() - this.asked < this.everyMs ) return;
    this.asked = Date.now();
    let me;
    try {
      me = await Api.me();
    } catch ( error ) {
      // The server being away is news only once someone tries to use it.
      return;
    }
    if ( !me.authenticated ) {
      Api.sessionEnded();
      return;
    }
    App.showMaintenance( me );
    App.showAnnouncement( me );
    this.heard( me.version );
  },

  // A screen with something a reload would lose says so here; test answers
  // true while it does.
  holdWhile( test ) {
    this.holds.push( test );
  },

  // Api.request passes the build that answered each call. dev is what a build
  // with no version stamped says, which is every build of one being worked
  // on, so a change to or from it means nothing (static/js/live.js covers
  // that case).
  heard( version ) {
    if ( !version || !this.version || version === "dev" || this.version === "dev" ) return;
    if ( version !== this.version ) this.notice( version );
  },

  // Something newer than this page is known: a build (its version), or a
  // file changed under it (static/js/live.js says "live"). The next screen
  // change reloads; if none comes, the toast asks.
  notice( what ) {
    if ( what === this.newer ) return;
    this.newer = what;
    window.setTimeout( () => this.offer() , this.toastAfterMs );
  },

  safe() {
    return !document.querySelector( ".modal.show" ) && !this.holds.some( ( test ) => test() );
  },

  // nav.js asks before showing another screen. True means the page is
  // reloading onto the screen in the URL, so there is nothing to show.
  swap() {
    if ( !this.newer || !this.safe() ) return false;
    window.location.reload();
    return true;
  },

  // Told once: someone who ignores the toast has seen it.
  offer() {
    if ( this.offered === this.newer ) return;
    this.offered = this.newer;
    Dom.toast( I18n.get( "fresh.new_version" ) , "ok" , {
      text: I18n.get( "fresh.reload" ),
      run: () => window.location.reload(),
    } );
  },
};
