// Every filter the library knows, in one registry. Each entry says how to
// test a row, which values it offers (for the facet counts), how it reads
// and writes itself in the URL, and where it does not apply.
//
// A row is { t: title , s: my state , social , score: [tenths, votes] | null }.
//
// Rules that keep filters honest -- the old app broke each of these:
//   - A filter the current list already decides is not offered (Status on
//     Watched) rather than offered and doomed to show nothing.
//   - "Unrated" is a mode of the rating filter, so "unrated and at least 7"
//     cannot be asked for.
//   - A year range says whether titles with no year are in or out, instead
//     of silently dropping them.
//
// Pure: no DOM. Labels for chips are the UI's job (filterbar.js).
const Filters = {
  CERT_ORDER: [ "G" , "TV-Y" , "TV-Y7" , "TV-G" , "PG" , "TV-PG" , "M" , "GP" , "M/PG" , "PG-13" , "TV-14" , "R" , "TV-MA" , "NC-17" , "X" , "NR" ],
  MISSING: [ "poster" , "overview" , "year" , "genres" , "imdb" , "runtime" ],

  defs: {
    genre: {
      kind: "multi",
      modes: [ "any" , "all" ],
      values: ( row ) => Genres.terms( row.t.genres ),
      // Long enough that the specific genres are not all behind Show all;
      // Discover's picker shows the same number.
      short: 24,
    },
    tag: {
      kind: "multi",
      modes: [ "any" , "all" ],
      values: ( row ) => row.t.tags || [],
    },
    type: {
      kind: "multi",
      values: ( row ) => [ row.t.type ],
      // Every other scope is one type already.
      hidden: ( list , scope ) => scope !== "all",
    },
    status: {
      kind: "multi",
      values: ( row ) => [ ( row.s && row.s.status ) || "none" ],
      hidden: ( list ) => list !== "all",
    },
    cert: {
      kind: "multi",
      values: ( row ) => [ row.t.certification || "none" ],
    },
    watchedby: {
      kind: "multi",
      values: ( row ) => {
        const who = ( row.social && row.social.watched ) || [];
        return who.length ? who.map( String ) : [ "nobody" ];
      },
    },
    lovedby: {
      kind: "multi",
      values: ( row ) => ( ( row.social && row.social.loved ) || [] ).map( String ),
    },
    addedby: {
      kind: "multi",
      values: ( row ) => ( row.t.added_by != null ? [ String( row.t.added_by ) ] : [] ),
    },
    missing: {
      kind: "multi",
      modes: [ "any" , "all" ],
      values: ( row ) => {
        const t = row.t;
        const out = [];
        if ( !t.poster ) out.push( "poster" );
        if ( !t.overview ) out.push( "overview" );
        if ( !t.year ) out.push( "year" );
        if ( !( t.genres || [] ).length ) out.push( "genres" );
        if ( !t.imdb_id ) out.push( "imdb" );
        if ( !t.runtime ) out.push( "runtime" );
        return out;
      },
    },
    year: {
      kind: "range",
      step: 1,
      value: ( row ) => row.t.year || null,
    },
    runtime: {
      kind: "range",
      step: 5,
      value: ( row ) => row.t.runtime || null,
    },
    imdb: {
      kind: "range",
      step: 0.1,
      value: ( row ) => ( row.score ? row.score[ 0 ] / 10 : null ),
    },
    votes: {
      kind: "range",
      step: 100,
      value: ( row ) => ( row.score ? row.score[ 1 ] : null ),
    },
    rating: {
      kind: "rating",
      value: ( row ) => ( row.s && row.s.rating ) || null,
    },
    loved: {
      kind: "toggle",
      value: ( row ) => Boolean( row.s && row.s.heart ),
    },
    // What the old Up next list left out, now two plain filters that are on
    // by default in Everything (Query.DEFAULT_FILTERS) and show as chips.
    // Skipped is "not for me" -- what a card's Skip sets.
    hidewatched: {
      kind: "hide",
      status: "watched",
      hidden: ( list ) => list !== "all",
    },
    hideskipped: {
      kind: "hide",
      status: "dropped",
      hidden: ( list ) => list !== "all",
    },
  },

  // The order the filter sheet lists them in.
  ORDER: [ "hidewatched" , "hideskipped" , "genre" , "year" , "rating" , "imdb" , "votes" , "status" , "type" , "cert" , "runtime" , "tag" , "loved" , "watchedby" , "lovedby" , "addedby" , "missing" ],

  subsumed( id , list , scope ) {
    const def = this.defs[ id ];
    return Boolean( def && def.hidden && def.hidden( list , scope ) );
  },

  available( list , scope ) {
    return this.ORDER.filter( ( id ) => !this.subsumed( id , list , scope ) );
  },

  isActive( id , value ) {
    const def = this.defs[ id ];
    if ( !def || value == null ) return false;
    switch ( def.kind ) {
      case "multi": return Array.isArray( value.values ) && value.values.length > 0;
      case "range": return value.from != null || value.to != null;
      case "rating": return ( value.mode && value.mode !== "any" ) || value.from != null || value.to != null;
      case "toggle": return value.value === true || value.value === false;
      case "hide": return value.on === true;
      default: return false;
    }
  },

  // One filter against one row.
  test( id , value , row ) {
    const def = this.defs[ id ];
    switch ( def.kind ) {
      case "multi": {
        const have = def.values( row );
        if ( value.mode === "all" ) return value.values.every( ( wanted ) => have.indexOf( wanted ) >= 0 );
        return value.values.some( ( wanted ) => have.indexOf( wanted ) >= 0 );
      }
      case "range": {
        const number = def.value( row );
        if ( number == null ) return Boolean( value.unknown );
        if ( value.from != null && number < value.from ) return false;
        if ( value.to != null && number > value.to ) return false;
        return true;
      }
      case "rating": {
        const rating = def.value( row );
        if ( value.mode === "unrated" ) return rating == null;
        if ( rating == null ) return false;
        if ( value.from != null && rating < value.from ) return false;
        if ( value.to != null && rating > value.to ) return false;
        return true;
      }
      case "toggle":
        return def.value( row ) === value.value;
      case "hide":
        return !( row.s && row.s.status === def.status );
      default:
        return true;
    }
  },

  // A predicate for a whole query's filters, optionally leaving one out --
  // the facet counts for a filter are counted with every *other* filter on.
  predicate( filters , except ) {
    const ids = Object.keys( filters ).filter( ( id ) => id !== except && this.isActive( id , filters[ id ] ) );
    return ( row ) => ids.every( ( id ) => this.test( id , filters[ id ] , row ) );
  },

  // -- the URL form ---------------------------------------------------------

  encode( id , value ) {
    const def = this.defs[ id ];
    const number = ( n ) => ( n == null ? "" : String( n ) );
    switch ( def.kind ) {
      case "multi": {
        const list = value.values.map( ( v ) => String( v ).replace( /,/g , "%2C" ) ).join( "," );
        return value.mode === "all" ? "all:" + list : list;
      }
      case "range":
        return number( value.from ) + ".." + number( value.to ) + ( value.unknown ? "~unknown" : "" );
      case "rating":
        if ( value.mode === "unrated" ) return "unrated";
        if ( value.from == null && value.to == null ) return "rated";
        return number( value.from ) + ".." + number( value.to );
      case "toggle":
        return value.value ? "yes" : "no";
      case "hide":
        return "on";
      default:
        return "";
    }
  },

  decode( id , raw ) {
    const def = this.defs[ id ];
    if ( !def || raw == null || raw === "" ) return null;
    const number = ( text ) => ( text === "" || text == null || isNaN( Number( text ) ) ? null : Number( text ) );
    switch ( def.kind ) {
      case "multi": {
        let mode = "any";
        let body = raw;
        if ( body.indexOf( "all:" ) === 0 ) { mode = "all"; body = body.slice( 4 ); }
        else if ( body.indexOf( "any:" ) === 0 ) { body = body.slice( 4 ); }
        const values = body.split( "," ).map( ( v ) => v.replace( /%2C/g , "," ) ).filter( Boolean );
        return values.length ? { mode: mode , values: values } : null;
      }
      case "range": {
        const unknown = /~unknown$/.test( raw );
        const parts = raw.replace( /~unknown$/ , "" ).split( ".." );
        const out = { from: number( parts[ 0 ] ) , to: number( parts[ 1 ] ) , unknown: unknown };
        return out.from == null && out.to == null ? null : out;
      }
      case "rating": {
        if ( raw === "unrated" ) return { mode: "unrated" , from: null , to: null };
        if ( raw === "rated" ) return { mode: "rated" , from: null , to: null };
        const parts = raw.split( ".." );
        return { mode: "rated" , from: number( parts[ 0 ] ) , to: number( parts[ 1 ] ) };
      }
      case "toggle":
        return raw === "yes" ? { value: true } : raw === "no" ? { value: false } : null;
      // "off" is not a value: the codec reads it as "take the default away".
      case "hide":
        return raw === "on" ? { on: true } : null;
      default:
        return null;
    }
  },
};
