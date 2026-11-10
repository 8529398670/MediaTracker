// The Logs screen (owner only): everything the server and the browsers have
// logged. One day shows at a time, today unless another is picked on the
// calendar, which marks the days that have entries (or, while searching,
// matches). app.js calls
// Logs.init( me ) for admins; only the owner gets past the first line, and
// the server answers anyone else's call with a 404 regardless.
//
// The search box is passed to the server as typed. Free words match anywhere
// in an entry; key:value narrows (kind:ui status:5xx user:ana path:/api
// ip:10.0. level:error action:click), a comma means "or" (kind:auth,admin)
// and a leading minus excludes (-kind:request). The kind buttons under the
// box add a kind: term for you.
//
// An address can be given a name, so the log says who is who. Clicking one in a
// row names it, and the list under the search manages them. Names live in the
// database and are added as the log is read, so naming an address names its past.
//
// The whole screen is data-no-track in index.html: reading the log would
// otherwise write to it.
const Logs = {
  kinds: [ "request" , "ui" , "auth" , "admin" , "error" , "system" ],
  selected: new Set(),
  searchDelayMs: 300,
  // The least time between reads while Live is on, however busy the server is.
  liveMs: 2000,
  liveOn: false,
  liveSource: null,
  liveTimer: null,
  liveLast: 0,
  // The day shown and the month the calendar shows, as UTC dates like the
  // files' names ("2026-11-09", "2026-11"). followToday is true until someone
  // picks a day, so the day shown moves on at midnight UTC.
  shown: "",
  month: "",
  followToday: true,
  // The last listing, by date.
  days: new Map(),

  async init( me ) {
    if ( !me.is_owner || !me.logs_enabled ) return;
    Dom.show( Dom.get( "logs-panel" ) , true );
    Dom.get( "logs-search-form" ).addEventListener( "submit" , ( event ) => {
      event.preventDefault();
      this.search();
    } );
    Dom.typed( Dom.get( "logs-query" ) , () => this.search() , this.searchDelayMs );
    Dom.get( "logs-live" ).addEventListener( "click" , () => this.toggleLive() );
    Dom.onPress( Dom.get( "logs-prune" ) , () => this.onPrune() );
    window.addEventListener( "hashchange" , () => this.followScreen() );
    // The calendar's popup keeps 16px from the window's edges, so on a phone
    // it does not run into the side of the screen. Clicks inside it (the month
    // arrows) leave it open; a picked day closes it (pick).
    new bootstrap.Dropdown( Dom.get( "logs-date-button" ) , {
      autoClose: "outside",
      popperConfig: ( config ) => ( { ...config , modifiers: [ ...config.modifiers ,
        { name: "preventOverflow" , options: { padding: 16 } } ] } ),
    } );
    Dom.get( "logs-cal-prev" ).addEventListener( "click" , () => this.shiftMonth( -1 ) );
    Dom.get( "logs-cal-next" ).addEventListener( "click" , () => this.shiftMonth( 1 ) );
    Dom.get( "logs-cal-today" ).addEventListener( "click" , () => this.pick( this.today() , true ) );
    this.shown = this.today();
    this.month = this.shown.slice( 0 , 7 );
    this.renderKinds();
    await this.refresh();
  },

  // The address, as text.
  ipCell( entry ) {
    return Dom.el( "td" , { class: "text-nowrap" , text: entry.ip || "" } );
  },

  // A new search moves to the newest matching day, unless the day shown has
  // matches of its own.
  search() {
    return this.refresh( true );
  },

  query() {
    const typed = Dom.get( "logs-query" ).value.trim();
    const kinds = Array.from( this.selected );
    return [ typed , kinds.length ? "kind:" + kinds.join( "," ) : "" ].filter( Boolean ).join( " " );
  },

  // Made once: a press flips its own button, so the button under the pointer
  // is never taken away and put back (which loses the keyboard's place, and
  // the browser's hold on where the page was).
  renderKinds() {
    const holder = Dom.get( "logs-kinds" );
    Dom.swap( holder , ...this.kinds.map( ( kind ) => Dom.el( "button" , {
      class: "btn btn-sm",
      text: I18n.get( "logs.kind_" + kind ) || kind,
      attrs: { type: "button" , "data-key": "log-kind-" + kind },
      on: { click: () => {
        if ( this.selected.has( kind ) ) this.selected.delete( kind );
        else this.selected.add( kind );
        this.paintKinds();
        return this.search();
      } },
    } ) ) );
    this.paintKinds();
  },

  paintKinds() {
    this.kinds.forEach( ( kind , index ) => {
      const button = Dom.get( "logs-kinds" ).children[ index ];
      const on = this.selected.has( kind );
      button.classList.toggle( "btn-primary" , on );
      button.classList.toggle( "btn-outline-secondary" , !on );
      button.setAttribute( "aria-pressed" , String( on ) );
    } );
  },

  async refresh( jump = false ) {
    let listing;
    try {
      listing = await Api.logDays( this.query() );
    } catch ( error ) {
      App.showError( error.message );
      return;
    }
    this.renderSettings( listing );
    this.days = new Map( listing.days.map( ( day ) => [ day.date , day ] ) );

    const today = this.today();
    if ( this.followToday && this.shown !== today ) {
      this.shown = today;
      this.month = today.slice( 0 , 7 );
    }
    const searching = this.query() !== "";
    if ( jump && searching && listing.days.length > 0 && !this.days.has( this.shown ) ) {
      this.shown = listing.days[ 0 ].date;
      this.month = this.shown.slice( 0 , 7 );
      this.followToday = this.shown === today;
    }

    const nothing = searching && listing.days.length === 0;
    const empty = Dom.get( "logs-empty" );
    Dom.text( empty , I18n.get( "logs.no_matches" ) );
    Dom.show( empty , nothing );
    Dom.show( Dom.get( "logs-day" ) , !nothing );
    this.renderCalendar();
    await this.renderDay();
  },

  // Shows date: the calendar moves to its month. focus is for a pick made on
  // the calendar: the popup closes and the keyboard goes back to its button,
  // which now names the new day.
  async pick( date , focus ) {
    this.shown = date;
    this.month = date.slice( 0 , 7 );
    this.followToday = date === this.today();
    Dom.show( Dom.get( "logs-day" ) , true );
    this.renderCalendar();
    if ( focus ) {
      const button = Dom.get( "logs-date-button" );
      bootstrap.Dropdown.getOrCreateInstance( button ).hide();
      button.focus( { preventScroll: true } );
    }
    await this.renderDay();
  },

  shiftMonth( step ) {
    const [ year , month ] = this.month.split( "-" ).map( Number );
    this.month = new Date( Date.UTC( year , month - 1 + step , 1 ) ).toISOString().slice( 0 , 7 );
    this.renderCalendar();
  },

  // The day shown, folded or not as it was if it is the same day. The new day
  // is built and its first page read before it replaces the old one, so the
  // page never shrinks to nothing while it waits. Only the latest call lands.
  async renderDay() {
    const holder = Dom.get( "logs-day" );
    const old = holder.querySelector( "details.log-day" );
    const open = old && old.getAttribute( "data-date" ) === this.shown ? old.open : true;
    const searching = this.query() !== "";
    const day = this.days.get( this.shown ) || {
      date: this.shown, bytes: 0, entries: 0, errors: 0, compressed: false,
      matches: searching ? 0 : undefined, missing: true,
    };
    const turn = this.dayTurn = ( this.dayTurn || 0 ) + 1;
    const block = await this.dayBlock( day , open );
    if ( turn !== this.dayTurn ) return;
    Dom.swap( holder , block );
  },

  // A month of buttons, one per date. A date with entries (or matches, while
  // searching) can be picked, and so can today; the rest are disabled. Months
  // before the oldest day or after this one are out of reach.
  renderCalendar() {
    const today = this.today();
    const searching = this.query() !== "";
    const dates = Array.from( this.days.keys() ).sort();
    const oldest = dates.length ? dates[ 0 ].slice( 0 , 7 ) : today.slice( 0 , 7 );
    const newest = [ today.slice( 0 , 7 ) , dates.length ? dates[ dates.length - 1 ].slice( 0 , 7 ) : "" ].sort()[ 1 ];
    const [ year , month ] = this.month.split( "-" ).map( Number );
    const first = new Date( Date.UTC( year , month - 1 , 1 ) );
    const length = new Date( Date.UTC( year , month , 0 ) ).getUTCDate();

    Dom.text( Dom.get( "logs-date-label" ) , this.dayLabel( this.shown ) );
    Dom.text( Dom.get( "logs-cal-title" ) , first.toLocaleDateString( undefined , { month: "long" , year: "numeric" , timeZone: "UTC" } ) );
    Dom.get( "logs-cal-prev" ).disabled = this.month <= oldest;
    Dom.get( "logs-cal-next" ).disabled = this.month >= newest;

    const cells = [];
    // 2026-01-04 was a Sunday; the week starts there.
    for ( let weekday = 0 ; weekday < 7 ; weekday += 1 ) {
      const name = new Date( Date.UTC( 2026 , 0 , 4 + weekday ) ).toLocaleDateString( undefined , { weekday: "narrow" , timeZone: "UTC" } );
      cells.push( Dom.el( "span" , { class: "log-cal-weekday" , text: name , attrs: { "aria-hidden": "true" } } ) );
    }
    for ( let blank = 0 ; blank < first.getUTCDay() ; blank += 1 ) cells.push( Dom.el( "span" ) );
    for ( let number = 1 ; number <= length ; number += 1 ) {
      const date = this.month + "-" + String( number ).padStart( 2 , "0" );
      const day = this.days.get( date );
      const count = day ? ( searching ? day.matches : day.entries ) : 0;
      const label = I18n.get( searching ? "logs.day_matches" : "logs.day_button" )
        .replace( "{date}" , () => this.dayLabel( date ) )
        .replace( "{count}" , Number( count || 0 ).toLocaleString() );
      const cell = Dom.el( "button" , {
        class: "log-cal-day" + ( day ? " has-logs" : "" ) + ( date === today ? " is-today" : "" ),
        attrs: { type: "button" , "data-key": "log-cal-" + date , "aria-pressed": String( date === this.shown ) , "aria-label": label , title: label },
        children: [
          Dom.el( "span" , { text: String( number ) } ),
          day && day.errors > 0 ? Dom.el( "span" , { class: "log-cal-dot" , attrs: { "aria-hidden": "true" } } ) : null,
        ].filter( Boolean ),
        on: { click: () => this.pick( date , true ) },
      } );
      cell.disabled = !day && date !== today;
      cells.push( cell );
    }
    Dom.swap( Dom.get( "logs-cal-grid" ) , ...cells );
  },

  renderSettings( listing ) {
    const settings = listing.settings || {};
    let line = I18n.get( "logs.settings_line" )
      .replace( "{days}" , String( settings.retention_days ) )
      .replace( "{used}" , this.size( listing.total_bytes ) )
      .replace( "{max}" , String( settings.max_total_mb ) + " MB" )
      .replace( "{gzip}" , String( settings.compress_after_days ) );
    const stored = I18n.get( settings.encrypted ? "logs.encrypted" : "logs.not_encrypted" );
    if ( stored ) line += " · " + stored;
    if ( listing.dropped > 0 ) line += " · " + I18n.get( "logs.dropped" ).replace( "{count}" , String( listing.dropped ) );
    Dom.text( Dom.get( "logs-settings" ) , line );
  },

  // Days are UTC dates (the files are named by them); times in the rows are
  // shown in the viewer's own zone.
  dayLabel( date ) {
    return new Date( date + "T00:00:00Z" ).toLocaleDateString( undefined , {
      weekday: "short", year: "numeric", month: "short", day: "numeric", timeZone: "UTC",
    } );
  },

  today() {
    return new Date().toISOString().slice( 0 , 10 );
  },

  size( bytes ) {
    const value = Number( bytes ) || 0;
    if ( value < 1024 ) return value + " B";
    if ( value < 1024 * 1024 ) return ( value / 1024 ).toFixed( 1 ) + " KB";
    return ( value / 1024 / 1024 ).toFixed( 1 ) + " MB";
  },

  count( key , value ) {
    return I18n.get( key ).replace( "{count}" , Number( value || 0 ).toLocaleString() );
  },

  daySummary( day ) {
    const meta = [
      day.matches !== undefined ? this.count( "logs.matches" , day.matches ) : this.count( "logs.entries" , day.entries ),
      this.size( day.bytes ),
    ];
    if ( day.compressed ) meta.push( I18n.get( "logs.compressed" ) );

    const summary = Dom.el( "summary" , { class: "log-day-summary" , children: [
      Dom.el( "span" , { class: "log-day-date" , text: this.dayLabel( day.date ) } ),
      Dom.el( "span" , { class: "log-day-meta" , text: meta.filter( Boolean ).join( " · " ) } ),
      day.errors > 0 ? Dom.badge( this.count( "logs.errors" , day.errors ) , "danger" ) : null,
    ].filter( Boolean ) } );
    return summary;
  },

  // A day, with its first page already in if it is open.
  async dayBlock( day , open ) {
    const summary = this.daySummary( day );

    // Download and delete sit inside the opened day rather than on the
    // summary line, where a click would also fold the day.
    if ( day.missing ) {
      const body = Dom.el( "div" , { class: "log-day-body" , children: [
        Dom.el( "p" , { class: "text-body-secondary mb-0" , text: I18n.get( day.matches === undefined ? "logs.day_empty" : "logs.no_matches" ) } ),
      ] } );
      const block = Dom.el( "details" , { class: "log-day" , attrs: { "data-date": day.date } , children: [ summary , body ] } );
      block.open = open;
      return block;
    }

    const download = Dom.el( "a" , {
      class: "btn btn-sm btn-outline-secondary",
      text: I18n.get( "logs.download_button" ),
      attrs: { href: Api.logDownloadPath( day.date ) , download: "logs-" + day.date + ".jsonl" },
    } );
    const remove = day.date === this.today() ? null : Dom.el( "button" , {
      class: "btn btn-sm btn-outline-danger",
      text: I18n.get( "logs.delete_button" ),
      on: { click: () => this.onDeleteDay( day.date ) },
    } );
    const body = Dom.el( "div" , { class: "log-day-body" , children: [
      Dom.el( "div" , { class: "mb-2" , children: [ Dom.rowActions( this.dayLabel( day.date ) , [ download , remove ] ) ] } ),
    ] } );

    const block = Dom.el( "details" , { class: "log-day" , attrs: { "data-date": day.date } , children: [ summary , body ] } );
    if ( open ) {
      block._loaded = true;
      await this.loadDay( block , body , day.date , null );
    }
    // Folded and then opened: the rows come in under the summary, which is
    // where the reader is looking, so nothing above them moves.
    block.addEventListener( "toggle" , () => {
      if ( block.open && !block._loaded ) {
        block._loaded = true;
        this.loadDay( block , body , day.date , null );
      }
    } );
    block.open = open;
    return block;
  },

  async loadDay( block , body , date , before ) {
    let page;
    try {
      page = await Api.logDay( date , this.query() , before );
    } catch ( error ) {
      App.showError( error.message );
      return;
    }
    let table = body.querySelector( "table" );
    if ( !table ) {
      table = Dom.el( "table" , { class: "table table-sm table-hover align-middle log-table" , children: [
        Dom.el( "thead" , { children: [ Dom.el( "tr" , { children: [
          Dom.el( "th" , { text: I18n.get( "logs.table_time" ) , attrs: { scope: "col" } } ),
          Dom.el( "th" , { text: I18n.get( "logs.table_kind" ) , attrs: { scope: "col" } } ),
          Dom.el( "th" , { text: I18n.get( "logs.table_user" ) , attrs: { scope: "col" } } ),
          Dom.el( "th" , { text: I18n.get( "logs.table_what" ) , attrs: { scope: "col" } } ),
          Dom.el( "th" , { text: I18n.get( "logs.table_ip" ) , attrs: { scope: "col" } } ),
        ] } ) ] } ),
        Dom.el( "tbody" ),
      ] } );
      body.appendChild( Dom.el( "div" , { class: "table-responsive" , children: [ table ] } ) );
    }
    const rows = table.querySelector( "tbody" );
    page.entries.forEach( ( entry ) => this.appendEntry( rows , entry ) );

    const old = body.querySelector( ".log-more" );
    if ( old ) old.remove();
    if ( page.next !== null && page.next !== undefined ) {
      body.appendChild( Dom.el( "button" , {
        class: "btn btn-sm btn-outline-secondary log-more",
        text: I18n.get( "logs.load_more" ),
        on: { click: () => this.loadDay( block , body , date , page.next ) },
      } ) );
    }
  },

  tone( entry ) {
    if ( entry.level === "error" || entry.kind === "error" ) return "danger";
    if ( entry.level === "warn" ) return "warning";
    return { request: "secondary" , ui: "info" , auth: "primary" , admin: "warning" , system: "dark" }[ entry.kind ] || "secondary";
  },

  who( entry ) {
    const actor = entry.actor || {};
    if ( !actor.user_id ) return I18n.get( "logs.anonymous" );
    const name = actor.name || "#" + actor.user_id;
    return actor.method === "api_key" ? name + " " + I18n.get( "logs.via_key" ) : name;
  },

  what( entry ) {
    if ( entry.request ) {
      const request = entry.request;
      return request.method + " " + request.path + " → " + request.status + " · " + Math.round( request.ms * 10 ) / 10 + " ms";
    }
    if ( entry.ui ) {
      const ui = entry.ui;
      return [ ui.action , ui.target , ui.screen ? "· " + ui.screen : "" ].filter( Boolean ).join( " " );
    }
    return entry.msg || "";
  },

  appendEntry( rows , entry ) {
    rows.append( ...this.entryRows( entry ) );
  },

  // A row, and under it the whole entry as JSON, shown by clicking the row.
  entryRows( entry ) {
    const json = Dom.el( "pre" , { class: "log-json" , text: JSON.stringify( entry , null , 2 ) } );
    const detail = Dom.el( "tr" , { class: "log-detail" , attrs: { hidden: "" } , children: [
      Dom.el( "td" , { attrs: { colspan: "5" } , children: [ json ] } ),
    ] } );
    const row = Dom.el( "tr" , {
      class: "log-row",
      attrs: { tabindex: "0" , "aria-expanded": "false" , "data-pos": String( entry.pos ) , "data-key": "log-" + entry.pos },
      children: [
        Dom.el( "td" , { class: "text-nowrap" , text: new Date( entry.ts ).toLocaleTimeString() } ),
        Dom.el( "td" , { children: [ Dom.badge( I18n.get( "logs.kind_" + entry.kind ) || entry.kind , this.tone( entry ) ) ] } ),
        Dom.el( "td" , { class: "text-nowrap" , text: this.who( entry ) } ),
        Dom.el( "td" , { class: "log-what" , text: this.what( entry ) } ),
        this.ipCell( entry ),
      ],
    } );
    const toggle = () => {
      detail.hidden = !detail.hidden;
      row.setAttribute( "aria-expanded" , String( !detail.hidden ) );
    };
    row.addEventListener( "click" , toggle );
    row.addEventListener( "keydown" , ( event ) => {
      // A button in the row has these keys for itself.
      if ( event.target !== row ) return;
      if ( event.key === "Enter" || event.key === " " ) {
        event.preventDefault();
        toggle();
      }
    } );
    return [ row , detail ];
  },

  // Live: the server says when there is something new, and the list is read
  // again then, so a quiet server costs nothing. The stream only says "look
  // again": the entries come through the same read as everything else here,
  // with the search box applied.
  toggleLive() {
    this.setLive( !this.liveOn );
  },

  setLive( on ) {
    this.liveOn = on;
    const button = Dom.get( "logs-live" );
    button.setAttribute( "aria-pressed" , String( on ) );
    button.classList.toggle( "btn-primary" , on );
    button.classList.toggle( "btn-outline-secondary" , !on );
    this.followScreen();
  },

  // The stream is open only while this screen is showing, because each one
  // holds a connection, and a browser only gets a few per server.
  followScreen() {
    if ( this.liveOn && Nav.current() === "logs" ) {
      this.openLive();
    } else {
      this.closeLive();
    }
  },

  openLive() {
    if ( this.liveSource ) return;
    const source = new EventSource( Api.logStreamPath() );
    source.addEventListener( "changed" , () => this.onChanged() );
    // A dropped connection retries by itself. CLOSED means the server said no:
    // the session ended, or too many pages are watching.
    source.addEventListener( "error" , () => {
      if ( source.readyState !== EventSource.CLOSED ) return;
      this.setLive( false );
      App.showError( I18n.get( "logs.live_lost" ) );
    } );
    this.liveSource = source;
  },

  closeLive() {
    if ( this.liveSource ) this.liveSource.close();
    this.liveSource = null;
    window.clearTimeout( this.liveTimer );
    this.liveTimer = null;
  },

  // At most one read per liveMs, and the last change always gets one. It holds
  // off while an entry is expanded, so what is being read does not fold away
  // under the reader.
  onChanged() {
    if ( this.liveTimer ) return;
    const wait = Math.max( 0 , this.liveLast + this.liveMs - Date.now() );
    this.liveTimer = window.setTimeout( () => {
      this.liveTimer = null;
      this.liveLast = Date.now();
      if ( Dom.all( "#logs-day .log-detail:not([hidden])" ).length > 0 ) {
        this.onChanged();
        return;
      }
      this.liveRead();
    } , wait );
  },

  // What Live does with a change: today's open day gets only the entries newer
  // than its top row, added above it, and the rows already there (with any
  // "Load more" pages) stay as they are. The calendar and the day's counts are
  // brought up to date in place. Anything else is a full refresh.
  async liveRead() {
    const block = Dom.get( "logs-day" ).querySelector( "details.log-day" );
    const rows = block && block.open && block._loaded && block.getAttribute( "data-date" ) === this.shown ? block.querySelector( ".log-table tbody" ) : null;
    const top = rows && rows.querySelector( "tr.log-row" );
    if ( !top || this.shown !== this.today() ) return this.refresh();
    const newest = Number( top.getAttribute( "data-pos" ) );
    let listing;
    let page;
    try {
      [ listing , page ] = await Promise.all( [ Api.logDays( this.query() ) , Api.logDay( this.shown , this.query() , null ) ] );
    } catch ( error ) {
      return;
    }
    const fresh = page.entries.filter( ( entry ) => entry.pos > newest );
    // A whole page of new ones may have skipped some: start over.
    if ( fresh.length === page.entries.length && page.next !== null && page.next !== undefined ) return this.refresh();
    this.renderSettings( listing );
    this.days = new Map( listing.days.map( ( day ) => [ day.date , day ] ) );
    this.renderCalendar();
    const day = this.days.get( this.shown );
    if ( day ) block.querySelector( "summary" ).replaceWith( this.daySummary( day ) );
    if ( fresh.length === 0 ) return;
    // Someone watching the top of the list sees the new rows arrive; someone
    // reading further down keeps the row they are on where it is.
    const table = rows.closest( "table" );
    const anchor = table.getBoundingClientRect().top >= 0
      ? table
      : Array.from( rows.rows ).find( ( row ) => !row.hidden && row.getBoundingClientRect().bottom > 0 ) || table;
    Dom.steady( anchor , () => rows.prepend( ...fresh.flatMap( ( entry ) => this.entryRows( entry ) ) ) );
  },

  async onPrune() {
    const question = I18n.get( "logs.prune_confirm" );
    if ( !( await Dom.confirm( question ) ) ) return;
    try {
      const result = await Api.pruneLogs();
      Dom.toast( I18n.get( "logs.pruned" )
        .replace( "{deleted}" , String( result.deleted ) )
        .replace( "{compressed}" , String( result.compressed ) ) , "ok" );
      await this.refresh();
    } catch ( error ) {
      App.showError( error.message );
    }
  },

  // No undo: the day's files are gone from disk.
  async onDeleteDay( date ) {
    const question = I18n.get( "logs.delete_confirm" ).replace( "{date}" , this.dayLabel( date ) );
    if ( !( await Dom.confirm( question ) ) ) return;
    try {
      await Api.deleteLogDay( date );
      this.followToday = true;
      await this.refresh();
      Dom.toast( I18n.get( "logs.deleted" ).replace( "{date}" , () => this.dayLabel( date ) ) , "ok" );
    } catch ( error ) {
      App.showError( error.message );
    }
  },
};
