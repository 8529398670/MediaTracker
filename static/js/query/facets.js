// How many titles each filter value would show, given everything else.
//
// One rule for every facet: count over the current scope and list with every
// *other* filter applied, and this facet's own filter left out. So the genre
// counts answer "if I also picked this genre", and picking Drama does not
// make every other genre read 0. The old app counted genres one way and tags
// and age ratings over the whole library, which offered options that were
// not in the section at all. Discover's server-side facets follow the same
// rule.
//
// Pure: no DOM.
const Facets = {
  // rows: the scope + list + text-search pool. Returns { filter id: Map(value -> count) }.
  count( rows , filters , ids ) {
    const out = {};
    ids.forEach( ( id ) => {
      const def = Filters.defs[ id ];
      if ( !def || def.kind !== "multi" ) return;
      const keep = Filters.predicate( filters , id );
      const counts = new Map();
      rows.forEach( ( row ) => {
        if ( !keep( row ) ) return;
        def.values( row ).forEach( ( value ) => counts.set( value , ( counts.get( value ) || 0 ) + 1 ) );
      } );
      out[ id ] = counts;
    } );
    return out;
  },

  // [ [value, count] ] most common first, then alphabetical; values already
  // chosen are always included even at 0 so they can be unticked.
  ranked( counts , chosen ) {
    const entries = Array.from( counts.entries() );
    ( chosen || [] ).forEach( ( value ) => {
      if ( !counts.has( value ) ) entries.push( [ value , 0 ] );
    } );
    return entries.sort( ( a , b ) => b[ 1 ] - a[ 1 ] || String( a[ 0 ] ).localeCompare( String( b[ 0 ] ) ) );
  },
};
