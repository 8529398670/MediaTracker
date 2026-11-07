// Grouping: optional, separate from sorting, with its own direction.
//
// Sorting decides the order inside each group; the group direction decides
// the order of the groups. Titles with no value for the grouping (no year,
// no genre) always form the last group, "Unknown", in either direction.
//
// A group's key carries the scope and the kind ("movie|decade|1940"), so
// collapsing the 1940s in Movies never collapses the year 1940 somewhere
// else -- the old app's collapse state collided exactly like that.
//
// Pure: no DOM. Labels for status and type groups come from the UI.
const Grouper = {
  kinds: {
    none: null,
    year: { value: ( row ) => row.t.year || null },
    decade: { value: ( row ) => ( row.t.year ? Math.floor( row.t.year / 10 ) * 10 : null ) },
    genre: { value: ( row ) => Genres.labels( row.t.genres )[ 0 ] || null , text: true },
    type: { value: ( row ) => row.t.type || null , text: true },
    status: { value: ( row ) => ( row.s && row.s.status ) || "none" , text: true , order: [ "watching" , "queue" , "watched" , "dropped" , "none" ] },
    rating: { value: ( row ) => ( row.s && row.s.rating ) || null },
    imdb: { value: ( row ) => ( row.score ? Math.floor( row.score[ 0 ] / 10 ) : null ) },
    cert: { value: ( row ) => row.t.certification || null , text: true , order: Filters.CERT_ORDER },
    added: { value: ( row ) => ( row.t.added_at ? row.t.added_at.slice( 0 , 7 ) : null ) , text: true },
    watched: { value: ( row ) => ( row.s && row.s.watched_at ? row.s.watched_at.slice( 0 , 7 ) : null ) , text: true },
    letter: { value: ( row ) => { const first = ( Sorter.keys.title.value( row ) || "" ).charAt( 0 ).toUpperCase(); return first ? ( /[A-Z]/.test( first ) ? first : "#" ) : null; } , text: true },
  },

  ORDER: [ "none" , "year" , "decade" , "genre" , "type" , "status" , "rating" , "imdb" , "cert" , "added" , "watched" , "letter" ],

  // rows (already sorted) -> [ { key , value , rows } ] in group order.
  group( rows , group , scope ) {
    const kind = this.kinds[ group.by ];
    if ( !kind ) return [ { key: scope + "|none|" , value: null , rows: rows } ];
    const buckets = new Map();
    rows.forEach( ( row ) => {
      const value = kind.value( row );
      const id = value == null ? "\u0000unknown" : String( value );
      if ( !buckets.has( id ) ) buckets.set( id , { key: scope + "|" + group.by + "|" + id , value: value , rows: [] } );
      buckets.get( id ).rows.push( row );
    } );
    const sign = group.dir === "desc" ? -1 : 1;
    return Array.from( buckets.values() ).sort( ( a , b ) => {
      if ( a.value == null ) return 1;
      if ( b.value == null ) return -1;
      if ( kind.order ) {
        const ia = kind.order.indexOf( a.value );
        const ib = kind.order.indexOf( b.value );
        if ( ia !== ib ) return ( ( ia < 0 ? 999 : ia ) - ( ib < 0 ? 999 : ib ) ) * sign;
      }
      if ( kind.text ) return String( a.value ).localeCompare( String( b.value ) ) * sign;
      return ( a.value - b.value ) * sign;
    } );
  },
};
