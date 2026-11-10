// Fills a table from a paged list route (see pagination in the server) and
// offers "Load more" under it while there are rows left.
//
// A refresh is a load from the start: it replaces the rows and the button, so
// a change on the screen never leaves a stale page behind. Rows come from
// renderRow, which appends one to the table the same way a plain forEach would.
const Pager = {
  // How each sorted table is sorted now, by its id: { sort , dir }.
  sorts: {},
  // Each table's search box, and anything else narrowing it, by its id.
  searches: {},
  filters: {},
  // Each table's latest load, so an older answer arriving late is dropped.
  loads: {},
  // Tables Pager.reset is holding at their old height, until a load lands.
  holds: {},

  // A search box for a table, on the server like sorting.
  search( table , input , refresh ) {
    this.searches[ table ] = Dom.get( input );
    Dom.typed( this.searches[ table ] , refresh );
  },

  // A checkbox that adds fields to a table's query while it is ticked.
  filter( table , box , fields , refresh ) {
    Dom.get( box ).addEventListener( "change" , ( event ) => {
      this.filters[ table ] = event.target.checked ? fields : {};
      refresh();
    } );
  },

  // Everything narrowing or ordering a table, for its fetchPage to pass to the
  // Api: what the query string needs.
  params( table ) {
    const search = this.searches[ table ];
    return { ...this.sortOf( table ) , ...this.filters[ table ] , q: search ? search.value.trim() : "" };
  },

  // Whether an empty table means nothing matched, not nothing there.
  narrowed( table ) {
    const params = this.params( table );
    return params.q !== "" || Object.keys( this.filters[ table ] || {} ).length > 0;
  },

  // Makes a table's th[data-sort] buttons sort it, on the server, because the
  // browser only holds a page. Pressing one goes up, down, then back to the
  // list's own order. refresh reloads the table, and its fetchPage passes
  // Pager.params( table ) to the Api.
  sortable( table , refresh ) {
    Dom.get( table ).querySelectorAll( "th[data-sort] button" ).forEach( ( button ) => {
      button.addEventListener( "click" , async () => {
        if ( button.disabled ) return;
        const field = button.closest( "th" ).dataset.sort;
        const now = this.sortOf( table );
        if ( now.sort !== field ) this.sorts[ table ] = { sort: field , dir: "asc" };
        else if ( now.dir === "asc" ) this.sorts[ table ] = { sort: field , dir: "desc" };
        else delete this.sorts[ table ];
        this.paintSort( table );
        // A second press while this loads could land its rows out of order.
        button.disabled = true;
        try {
          await refresh();
        } finally {
          button.disabled = false;
        }
      } );
    } );
  },

  sortOf( table ) {
    return this.sorts[ table ] || {};
  },

  // Back to the list's own order, for a table whose sort no longer applies.
  // The caller refreshes.
  clearSort( table ) {
    delete this.sorts[ table ];
    this.paintSort( table );
  },

  paintSort( table ) {
    const now = this.sortOf( table );
    Dom.get( table ).querySelectorAll( "th[data-sort]" ).forEach( ( header ) => {
      if ( header.dataset.sort === now.sort ) header.setAttribute( "aria-sort" , now.dir === "desc" ? "descending" : "ascending" );
      else header.removeAttribute( "aria-sort" );
    } );
  },

  // Empties a table at once, for when what it holds is about to be someone
  // else's. A load that is still out is dropped by the next load's turn.
  release( table ) {
    if ( !this.holds[ table ] ) return;
    this.holds[ table ]();
    delete this.holds[ table ];
  },

  // The table keeps its height until the next load fills it (Dom.hold), so
  // the page does not shrink and spring back in between.
  reset( table ) {
    const element = Dom.get( table );
    this.release( table );
    this.holds[ table ] = Dom.hold( element );
    Dom.clear( element.querySelector( "tbody" ) );
    const holder = element.closest( ".table-responsive" ) || element;
    const more = holder.parentElement.querySelector( ".pager-more[data-for='" + table + "']" );
    if ( more ) more.remove();
  },

  // Gives each cell its column's name, which a narrow screen shows beside the
  // value once the header row is gone. See the stacked tables in style.css.
  label( table ) {
    const element = Dom.get( table );
    const names = Array.from( element.querySelectorAll( "thead th:not([hidden])" ) ).map( ( header ) => header.textContent.trim() );
    Array.from( element.querySelector( "tbody" ).rows ).forEach( ( row ) => {
      if ( row.cells.length !== names.length ) return;
      Array.from( row.cells ).forEach( ( cell , index ) => cell.setAttribute( "data-label" , names[ index ] ) );
    } );
  },

  // What can take the focus in a row.
  controls( row ) {
    return Array.from( row.querySelectorAll( "a[href], button, input, select, textarea" ) ).filter( ( control ) => control.offsetParent !== null );
  },

  // Redrawing a table takes away the button that was pressed, and with it the
  // keyboard's place on the page. This notes where the focus is, for putBack.
  focusSpot( element ) {
    const active = document.activeElement;
    const body = element.querySelector( "tbody" );
    if ( !active || !body.contains( active ) ) return null;
    const row = active.closest( "tr" );
    return {
      row: Array.from( body.rows ).indexOf( row ),
      control: this.controls( row ).indexOf( active ),
      text: active.textContent,
    };
  },

  // The same button in the same row if it is still there, or the nearest thing
  // to it: the row that took its place, or the table if no rows are left.
  putBack( element , spot ) {
    if ( !spot ) return;
    const rows = element.querySelector( "tbody" ).rows;
    const row = rows[ Math.min( spot.row , rows.length - 1 ) ];
    const controls = row ? this.controls( row ) : [];
    const target = controls.find( ( control ) => control.textContent === spot.text )
      || controls[ Math.min( spot.control , controls.length - 1 ) ];
    if ( target ) {
      target.focus( { preventScroll: true } );
      return;
    }
    element.setAttribute( "tabindex" , "-1" );
    element.focus( { preventScroll: true } );
  },

  // table is the table's id, field the name its rows arrive under, fetchPage
  // calls the Api with an offset. Answers the page, or null if the call failed.
  async load( table , field , fetchPage , renderRow , offset ) {
    const element = Dom.get( table );
    const turn = this.loads[ table ] = ( this.loads[ table ] || 0 ) + 1;
    let page;
    try {
      page = await fetchPage( offset );
    } catch ( error ) {
      this.release( table );
      App.showError( error.message );
      return null;
    }
    if ( turn !== this.loads[ table ] ) return null;
    const spot = offset ? null : this.focusSpot( element );
    if ( !offset ) Dom.clear( element.querySelector( "tbody" ) );
    page[ field ].forEach( renderRow );
    this.release( table );
    if ( !offset && page[ field ].length === 0 ) this.empty( element );
    this.label( table );
    this.putBack( element , spot );

    const holder = element.closest( ".table-responsive" ) || element;
    const old = holder.parentElement.querySelector( ".pager-more[data-for='" + table + "']" );
    const onMore = old !== null && old === document.activeElement;
    if ( old ) old.remove();
    if ( page.next !== null && page.next !== undefined ) {
      const more = Dom.el( "button" , {
        class: "btn btn-sm btn-outline-secondary mt-2 pager-more",
        attrs: { "data-for": table },
        text: I18n.get( "ui.load_more" ),
      } );
      // Busy until the page is in: a second press would fetch the same offset
      // and append those rows twice. Added here rather than through Dom.el, so
      // that does not depend on an app having taken busy-buttons.
      more.addEventListener( "click" , () => Dom.busy( more , () => this.load( table , field , fetchPage , renderRow , page.next ) ) );
      holder.after( more );
      if ( onMore ) more.focus( { preventScroll: true } );
    } else if ( onMore ) {
      this.putBack( element , { row: element.querySelector( "tbody" ).rows.length - 1 , control: 0 , text: "" } );
    }
    return page;
  },

  // One row saying there is nothing here, worded by the table's data-empty
  // key, so a bare heading row does not look like a screen that failed to load.
  empty( table ) {
    const text = I18n.get( this.narrowed( table.id ) ? "ui.no_matches" : table.getAttribute( "data-empty" ) || "" );
    if ( text === "" ) return;
    table.querySelector( "tbody" ).appendChild( Dom.el( "tr" , { children: [
      Dom.el( "td" , {
        class: "text-body-secondary",
        text: text,
        attrs: { colspan: String( table.querySelectorAll( "thead th:not([hidden])" ).length ) },
      } ),
    ] } ) );
  },
};
