// A change to the frontend, shown without pressing refresh.
//
// server.live_reload decides whether the server offers it (by default: only a
// build being worked on, with no version stamped, serving static/ from disk).
// The first request finds out: no route, nothing more is asked.
//
// A stylesheet is swapped in place, so the page keeps its scroll and whatever
// is open. Any other file needs a reload. On a dev build that happens at once
// and lands back on the same screen, because each screen is its own path; a
// restart of the server (a change to the Go or Python side) reloads too. On a
// stamped build -- a live site with live_reload: always -- nobody is waiting
// for their own save, so it is left to Fresh: the page reloads at the next
// move to another screen, or offers to after a while, never under an open
// dialog or unsaved work. A new build is heard there anyway, from
// X-App-Version on every API reply.
//
// The request is held by the server until something changes (long-poll); see
// server/livereload or app/core/live_reload.py. A hidden tab asks nothing,
// and asks once when it is shown again.
const Live = {
  boot: "",
  stamp: -1,
  eager: false,
  // How long the server holds a request (holdFor / HOLD_SECONDS).
  holdMs: 25 * 1000,

  init( me ) {
    this.eager = me.version === "dev";
    this.listen();
  },

  pause( ms ) {
    return new Promise( ( resolve ) => window.setTimeout( resolve , ms ) );
  },

  shown() {
    if ( !document.hidden ) return Promise.resolve();
    return new Promise( ( resolve ) => {
      const back = () => {
        if ( document.hidden ) return;
        document.removeEventListener( "visibilitychange" , back );
        resolve();
      };
      document.addEventListener( "visibilitychange" , back );
    } );
  },

  async listen() {
    for ( ;; ) {
      await this.shown();
      let reply;
      try {
        const response = await fetch( "/api/live?boot=" + encodeURIComponent( this.boot ) + "&since=" + this.stamp , {
          credentials: "same-origin",
          // The server answers within holdMs. A request held when its process
          // was stopped can hang forever instead of failing, so it is given up.
          signal: AbortSignal.timeout( this.holdMs + 5000 ),
        } );
        // No route: live reload is off. It always was, and there is nothing to
        // do; or the server was restarted with it off, as another build that a
        // dev page should be running.
        if ( response.status === 404 ) {
          if ( this.boot && this.eager ) window.location.reload();
          return;
        }
        if ( !response.ok ) throw new Error( String( response.status ) );
        reply = await response.json();
      } catch ( error ) {
        // Restarting, most likely. Ask again until it is back.
        await this.pause( 1000 );
        continue;
      }
      if ( this.boot && reply.boot !== this.boot ) {
        // A restart. A stamped build that changed says so in X-App-Version.
        if ( this.eager ) {
          window.location.reload();
          return;
        }
      } else if ( this.boot && reply.stamp !== this.stamp && !this.apply( reply.changed ) ) {
        if ( this.eager ) {
          window.location.reload();
          return;
        }
        Fresh.notice( "live" );
      }
      this.boot = reply.boot;
      this.stamp = reply.stamp;
    }
  },

  // Swaps the stylesheets that changed, or answers false when the change
  // needs a reload: a script, the markup, or more than one save missed.
  apply( changed ) {
    if ( !changed ) return false;
    const links = Array.from( document.querySelectorAll( 'link[rel="stylesheet"]' ) );
    const swaps = [];
    for ( const name of changed ) {
      if ( !name.endsWith( ".css" ) ) return false;
      const link = links.find( ( each ) => new URL( each.href ).pathname === "/" + name );
      if ( !link ) return false;
      swaps.push( link );
    }
    swaps.forEach( ( link ) => this.swap( link ) );
    return true;
  },

  // The new sheet goes in beside the old one, which leaves once it has
  // loaded, so the page is never shown unstyled.
  swap( link ) {
    const fresh = link.cloneNode();
    fresh.href = link.href.split( "?" )[ 0 ] + "?t=" + Date.now();
    fresh.addEventListener( "load" , () => link.remove() , { once: true } );
    fresh.addEventListener( "error" , () => fresh.remove() , { once: true } );
    link.after( fresh );
  },
};
