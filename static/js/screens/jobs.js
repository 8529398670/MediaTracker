// What is running in the background: filling in titles, the IMDb ratings
// download, Apple TV ids, the Wikipedia catalogue. Everyone can see it (it
// explains why posters are appearing); only an admin can start or stop one.
const JobsScreen = {
  timer: null,

  init( me ) {
    this.me = me;
    Dom.show( Dom.get( "jobs-panel" ) , true );
    window.addEventListener( "hashchange" , () => this.poll() );
    this.poll();
  },

  async poll() {
    window.clearTimeout( this.timer );
    if ( Nav.screen() !== "jobs" ) return;
    try {
      this.render( await Api.request( "/api/jobs" ) );
    } catch ( error ) {
      // try again on the next tick
    }
    this.timer = window.setTimeout( () => this.poll() , 3000 );
  },

  render( data ) {
    const box = Dom.get( "jobs-list" );
    Dom.clear( box );
    Dom.show( Dom.get( "jobs-offline" ) , !data.network );
    data.jobs.forEach( ( job ) => {
      const progress = job.total ? Math.round( 100 * job.done / job.total ) : 0;
      const lines = [ Dom.el( "div" , { class: "d-flex justify-content-between align-items-center gap-2 flex-wrap" , children: [
        Dom.el( "div" , { children: [
          Dom.el( "h3" , { class: "h6 mb-0" , text: I18n.get( "jobs.name_" + job.name ) || job.name } ),
          Dom.el( "div" , { class: "small text-body-secondary" , text: I18n.get( "jobs.help_" + job.name ) } ),
        ] } ),
        this.controls( job ),
      ] } ) ];
      if ( job.running ) {
        // Width through the CSSOM: a style attribute is refused by the CSP.
        const bar = Dom.el( "div" , { class: "progress-bar" } );
        bar.style.width = progress + "%";
        lines.push( Dom.el( "div" , { class: "progress mt-2" , attrs: { role: "progressbar" , "aria-valuenow": String( progress ) , "aria-valuemin": "0" , "aria-valuemax": "100" } , children: [ bar ] } ) );
        lines.push( Dom.el( "div" , { class: "small text-body-secondary mt-1 text-truncate" , text: I18n.fill( "jobs.progress" , { done: job.done , total: job.total || "?" , what: job.message || "" } ) } ) );
      }
      const facts = [];
      if ( job.finished_at && !job.running ) facts.push( I18n.fill( "jobs.finished" , { when: Vocab.date( job.finished_at ) } ) );
      if ( job.titles ) facts.push( I18n.fill( "jobs.imdb_titles" , { n: job.titles.toLocaleString() , date: job.file_date || "?" } ) );
      if ( job.queued ) facts.push( I18n.fill( "jobs.queued" , { n: job.queued } ) );
      if ( job.last_error ) facts.push( I18n.fill( "jobs.error" , { error: job.last_error } ) );
      if ( facts.length ) lines.push( Dom.el( "div" , { class: "small mt-1" + ( job.last_error ? " text-danger" : " text-body-secondary" ) , text: facts.join( " · " ) } ) );
      box.appendChild( Dom.el( "li" , { class: "list-group-item" , children: lines } ) );
    } );
    Dom.text( Dom.get( "jobs-images" ) , I18n.fill( "jobs.images" , { n: data.images.files , mb: Math.round( data.images.bytes / 1048576 ) , budget: Math.round( data.images.budget / 1048576 ) } ) );
  },

  controls( job ) {
    if ( this.me.role !== "admin" || !job.manual ) return Dom.el( "span" );
    if ( job.running ) {
      return Dom.el( "button" , { class: "btn btn-sm btn-outline-danger" , text: I18n.get( "jobs.stop" ) , attrs: { type: "button" } , on: { click: () => this.act( job.name , "stop" ) } } );
    }
    const scopes = job.scopes || [ null ];
    return Dom.el( "div" , { class: "d-flex gap-1 flex-wrap" , children: scopes.map( ( scope ) => Dom.el( "button" , {
      class: "btn btn-sm btn-outline-primary",
      text: I18n.get( scope ? "jobs.start_" + job.name + "_" + scope : "jobs.start" ) || I18n.get( "jobs.start" ),
      attrs: { type: "button" },
      on: { click: () => this.act( job.name , "start" , scope ? { scope: scope } : {} ) },
    } ) ) } );
  },

  async act( name , action , options ) {
    try {
      await Api.post( "/api/jobs/" + encodeURIComponent( name ) + "/" + action , { options: options || {} } );
      this.poll();
    } catch ( error ) {
      Dom.toast( I18n.get( "errors." + error.message ) || error.message , "error" );
    }
  },
};
