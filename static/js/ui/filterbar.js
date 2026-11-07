// The visible half of filtering: a chip for every active filter, the search
// text and the grouping, each with its own x, and a Clear all that really
// clears all (filters, search, sort and grouping, back to the list's
// defaults). Nothing that narrows the list is ever left off this row -- the
// old app's hidden "hide watched" toggles are exactly what made it feel
// broken -- so Hide watched and Hide skipped, on by default, are chips too.
//
// The other half is the sheet (FilterSheet below): every filter that applies
// here, with live counts. Changes apply as they are made; there is no draft
// to forget to apply.
const FilterBar = {
  valueLabel( id , value ) {
    switch ( id ) {
      case "type": return Vocab.typeLabel( value );
      case "status": return I18n.get( "status." + value );
      case "cert": return value === "none" ? I18n.get( "filters.cert_none" ) : value;
      case "watchedby": return value === "nobody" ? I18n.get( "filters.nobody" ) : Vocab.personName( value );
      case "lovedby": case "addedby": return Vocab.personName( value );
      case "missing": return I18n.get( "filters.missing_" + value );
      case "tag": return "#" + value;
      default: return String( value );
    }
  },

  rangeText( id , value ) {
    const show = ( n ) => ( id === "imdb" ? Number( n ).toFixed( 1 ) : id === "runtime" ? Vocab.runtime( n ) : id === "votes" ? Vocab.votes( n ) : String( n ) );
    let text;
    if ( value.from != null && value.to != null ) text = show( value.from ) + "–" + show( value.to );
    else if ( value.from != null ) text = I18n.fill( "filters.at_least" , { value: show( value.from ) } );
    else text = I18n.fill( "filters.at_most" , { value: show( value.to ) } );
    if ( value.unknown ) text += " " + I18n.get( "filters.and_unknown" );
    return text;
  },

  describe( id , value ) {
    const def = Filters.defs[ id ];
    switch ( def.kind ) {
      case "multi": {
        const joiner = I18n.get( value.mode === "all" ? "filters.joiner_all" : "filters.joiner_any" );
        return value.values.map( ( v ) => this.valueLabel( id , v ) ).join( " " + joiner + " " );
      }
      case "range": return this.rangeText( id , value );
      case "rating":
        if ( value.mode === "unrated" ) return I18n.get( "filters.unrated" );
        if ( value.from == null && value.to == null ) return I18n.get( "filters.rated" );
        return this.rangeText( id , value );
      case "toggle": return I18n.get( value.value ? "filters.yes" : "filters.no" );
      default: return "";
    }
  },

  chip( text , onRemove , tone ) {
    return Dom.el( "span" , { class: "filter-chip filter-chip-" + ( tone || "filter" ) , children: [
      Dom.el( "span" , { text: text } ),
      Dom.el( "button" , {
        class: "btn-close btn-close-sm",
        attrs: { type: "button" , "aria-label": I18n.fill( "filters.remove" , { what: text } ) },
        on: { click: onRemove },
      } ),
    ] } );
  },

  // query: the screen's query; change( next ) applies a new one.
  render( container , query , change ) {
    Dom.clear( container );
    const chips = [];
    if ( query.text ) {
      chips.push( this.chip( I18n.fill( "filters.chip_search" , { text: query.text } ) , () => {
        const next = Query.clone( query );
        next.text = "";
        change( next );
      } , "search" ) );
    }
    Filters.ORDER.forEach( ( id ) => {
      const value = query.filters[ id ];
      if ( !Filters.isActive( id , value ) ) return;
      const text = Filters.defs[ id ].kind === "hide" ? I18n.get( "filters.name_" + id ) : I18n.get( "filters.name_" + id ) + ": " + this.describe( id , value );
      chips.push( this.chip( text , () => {
        const next = Query.clone( query );
        delete next.filters[ id ];
        change( next );
      } ) );
    } );
    if ( query.group.by !== "none" ) {
      chips.push( this.chip( I18n.fill( "filters.chip_group" , { by: I18n.get( "group.by_" + query.group.by ) } ) , () => {
        const next = Query.clone( query );
        next.group = { by: "none" , dir: "asc" };
        change( next );
      } , "group" ) );
    }
    chips.forEach( ( chip ) => container.appendChild( chip ) );
    if ( !Query.isDefault( query ) ) {
      container.appendChild( Dom.el( "button" , {
        class: "btn btn-sm btn-link filter-clear",
        text: I18n.get( "filters.clear_all" ),
        attrs: { type: "button" },
        on: { click: () => change( Query.defaults( query.list ) ) },
      } ) );
    }
    Dom.show( container , container.childNodes.length > 0 );
  },
};

const FilterSheet = {
  // How many values a long facet shows before "Show all".
  SHORT: 10,
  expanded: {},

  render( body , query , scope , pool , change ) {
    Dom.clear( body );
    const ids = Filters.available( query.list , scope );
    const counts = Facets.count( pool , query.filters , ids );
    ids.forEach( ( id ) => {
      const section = this.section( id , query , counts[ id ] , change );
      if ( section ) body.appendChild( section );
    } );
  },

  section( id , query , counts , change ) {
    const def = Filters.defs[ id ];
    const value = query.filters[ id ];
    const heading = Dom.el( "div" , { class: "filter-heading" , children: [
      Dom.el( "h3" , { class: "h6 mb-0" , text: I18n.get( "filters.name_" + id ) } ),
    ] } );
    if ( Filters.isActive( id , value ) ) {
      heading.appendChild( Dom.el( "button" , {
        class: "btn btn-sm btn-link p-0",
        text: I18n.get( "filters.reset" ),
        attrs: { type: "button" },
        on: { click: () => { const next = Query.clone( query ); delete next.filters[ id ]; change( next ); } },
      } ) );
    }
    const box = Dom.el( "section" , { class: "filter-section" , children: [ heading ] } );
    const help = I18n.get( "filters.help_" + id );
    if ( help ) box.appendChild( Dom.el( "p" , { class: "small text-body-secondary mb-2" , text: help } ) );
    let control = null;
    if ( def.kind === "multi" ) control = this.multi( id , def , value , counts , query , change );
    if ( def.kind === "range" ) control = this.range( id , def , value , query , change );
    if ( def.kind === "rating" ) control = this.rating( id , value , query , change );
    if ( def.kind === "toggle" ) control = this.toggle( id , value , query , change );
    if ( def.kind === "hide" ) return this.hide( id , value , query , change );
    if ( !control ) return null;
    box.appendChild( control );
    return box;
  },

  update( query , id , value , change ) {
    const next = Query.clone( query );
    if ( value == null || !Filters.isActive( id , value ) ) delete next.filters[ id ];
    else next.filters[ id ] = value;
    change( next );
  },

  multi( id , def , value , counts , query , change ) {
    const chosen = value ? value.values : [];
    const mode = value ? value.mode || "any" : "any";
    const entries = Facets.ranked( counts || new Map() , chosen );
    if ( !entries.length ) return Dom.el( "p" , { class: "small text-body-secondary mb-0" , text: I18n.get( "filters.none_here" ) } );
    const wrap = Dom.el( "div" );
    if ( def.modes && chosen.length > 1 ) {
      const group = Dom.el( "div" , { class: "btn-group btn-group-sm mb-2" , attrs: { role: "group" } } );
      def.modes.forEach( ( which ) => {
        group.appendChild( Dom.el( "button" , {
          class: "btn " + ( which === mode ? "btn-soft-primary" : "btn-outline-secondary" ),
          text: I18n.get( "filters.mode_" + which ),
          attrs: { type: "button" , "aria-pressed": String( which === mode ) },
          on: { click: () => this.update( query , id , { mode: which , values: chosen } , change ) },
        } ) );
      } );
      wrap.appendChild( group );
    }
    const open = this.expanded[ id ];
    const shown = open ? entries : entries.slice( 0 , this.SHORT );
    const list = Dom.el( "div" , { class: "facet-list" } );
    shown.forEach( ( entry ) => {
      const facetValue = entry[ 0 ];
      const count = entry[ 1 ];
      const on = chosen.indexOf( facetValue ) >= 0;
      list.appendChild( Dom.el( "button" , {
        class: "facet" + ( on ? " is-on" : "" ) + ( count === 0 && !on ? " is-empty" : "" ),
        attrs: { type: "button" , "aria-pressed": String( on ) },
        children: [
          Card.icon( on ? "check-square-fill" : "square" ),
          Dom.el( "span" , { class: "facet-label" , text: FilterBar.valueLabel( id , facetValue ) } ),
          Dom.el( "span" , { class: "facet-count" , text: String( count ) } ),
        ],
        on: { click: () => {
          const values = on ? chosen.filter( ( v ) => v !== facetValue ) : chosen.concat( [ facetValue ] );
          this.update( query , id , { mode: mode , values: values } , change );
        } },
      } ) );
    } );
    wrap.appendChild( list );
    if ( entries.length > this.SHORT ) {
      wrap.appendChild( Dom.el( "button" , {
        class: "btn btn-sm btn-link px-0",
        text: open ? I18n.get( "filters.show_fewer" ) : I18n.fill( "filters.show_all" , { n: entries.length } ),
        attrs: { type: "button" },
        on: { click: () => { this.expanded[ id ] = !open; change( query , true ); } },
      } ) );
    }
    return wrap;
  },

  range( id , def , value , query , change ) {
    const current = value || { from: null , to: null , unknown: false };
    const input = ( which ) => {
      const field = Dom.el( "input" , {
        class: "form-control form-control-sm",
        attrs: { type: "number" , step: String( def.step ) , inputmode: "decimal" , placeholder: I18n.get( "filters." + which ) , "aria-label": I18n.get( "filters.name_" + id ) + " " + I18n.get( "filters." + which ) },
      } );
      if ( current[ which ] != null ) field.value = String( current[ which ] );
      field.addEventListener( "change" , () => {
        const next = Object.assign( {} , current );
        next[ which ] = field.value === "" ? null : Number( field.value );
        this.update( query , id , next , change );
      } );
      return field;
    };
    const row = Dom.el( "div" , { class: "d-flex align-items-center gap-2" , children: [ input( "from" ) , Dom.el( "span" , { text: "–" } ) , input( "to" ) ] } );
    const wrap = Dom.el( "div" , { children: [ row ] } );
    if ( id === "year" || id === "runtime" || id === "imdb" || id === "votes" ) {
      const check = Dom.el( "input" , { class: "form-check-input" , attrs: { type: "checkbox" , id: "unknown-" + id } } );
      check.checked = Boolean( current.unknown );
      check.disabled = current.from == null && current.to == null;
      check.addEventListener( "change" , () => this.update( query , id , Object.assign( {} , current , { unknown: check.checked } ) , change ) );
      wrap.appendChild( Dom.el( "div" , { class: "form-check mt-2" , children: [
        check,
        Dom.el( "label" , { class: "form-check-label small" , text: I18n.get( "filters.include_unknown_" + id ) || I18n.get( "filters.include_unknown" ) , attrs: { for: "unknown-" + id } } ),
      ] } ) );
    }
    return wrap;
  },

  rating( id , value , query , change ) {
    const current = value || { mode: "any" , from: null , to: null };
    const group = Dom.el( "div" , { class: "btn-group btn-group-sm mb-2 w-100" , attrs: { role: "group" } } );
    [ "any" , "rated" , "unrated" ].forEach( ( mode ) => {
      const on = ( current.mode || "any" ) === mode;
      group.appendChild( Dom.el( "button" , {
        class: "btn " + ( on ? "btn-soft-primary" : "btn-outline-secondary" ),
        text: I18n.get( "filters.rating_" + mode ),
        attrs: { type: "button" , "aria-pressed": String( on ) },
        on: { click: () => this.update( query , id , mode === "any" ? null : { mode: mode , from: null , to: null } , change ) },
      } ) );
    } );
    const wrap = Dom.el( "div" , { children: [ group ] } );
    if ( current.mode === "rated" ) {
      wrap.appendChild( this.range( id , { step: 1 } , { from: current.from , to: current.to } , query , ( next ) => {
        const picked = next.filters[ id ];
        this.update( query , id , { mode: "rated" , from: picked ? picked.from : null , to: picked ? picked.to : null } , change );
      } ) );
    }
    return wrap;
  },

  // A hide is one switch, named for what it does, with no heading of its own.
  hide( id , value , query , change ) {
    const input = Dom.el( "input" , {
      class: "form-check-input",
      attrs: { type: "checkbox" , role: "switch" , id: "filter-" + id },
      on: { change: ( event ) => this.update( query , id , event.target.checked ? { on: true } : null , change ) },
    } );
    input.checked = Filters.isActive( id , value );
    return Dom.el( "section" , { class: "filter-section" , children: [
      Dom.el( "div" , { class: "form-check form-switch mb-0" , children: [
        input,
        Dom.el( "label" , { class: "form-check-label" , text: I18n.get( "filters.name_" + id ) , attrs: { for: "filter-" + id } } ),
      ] } ),
    ] } );
  },

  toggle( id , value , query , change ) {
    const current = value ? value.value : null;
    const group = Dom.el( "div" , { class: "btn-group btn-group-sm w-100" , attrs: { role: "group" } } );
    [ [ null , "filters.either" ] , [ true , "filters.yes" ] , [ false , "filters.no" ] ].forEach( ( pair ) => {
      const on = current === pair[ 0 ];
      group.appendChild( Dom.el( "button" , {
        class: "btn " + ( on ? "btn-soft-primary" : "btn-outline-secondary" ),
        text: I18n.get( pair[ 1 ] ),
        attrs: { type: "button" , "aria-pressed": String( on ) },
        on: { click: () => this.update( query , id , pair[ 0 ] == null ? null : { value: pair[ 0 ] } , change ) },
      } ) );
    } );
    return group;
  },
};
