// Sorting: up to three keys, each with its own direction, and nothing hidden.
//
// Two rules the old app got wrong and this one keeps:
//   - Missing values always go last, whichever way a key runs. "IMDb, high
//     to low" and "low to high" both end with the titles that have no score.
//   - Ties are always broken the same way -- title, then year, then id -- so
//     the order never shuffles between two renders of the same data.
//
// Sorting never groups. Grouping (group.js) is a separate choice with its own
// direction, so "IMDb high to low" is one continuous list unless you ask for
// groups.
//
// Pure: no DOM.
const Sorter = {
  // value(row) -> a number or string, or null for "not known".
  keys: {
    title: { value: ( row ) => Search.fold( String( row.t.title || "" ).replace( /^(the|a|an)\s+/i , "" ) ) || null , text: true },
    year: { value: ( row ) => row.t.year || null },
    added: { value: ( row ) => row.t.added_at || null },
    updated: { value: ( row ) => row.t.updated_at || null },
    watched: { value: ( row ) => ( row.s && row.s.watched_at ) || null },
    rating: { value: ( row ) => ( row.s && row.s.rating ) || null },
    imdb: { value: ( row ) => ( row.score ? row.score[ 0 ] : null ) },
    // IMDb's own top-250 formula: a 9.4 from forty votes ranks below an 8.5
    // from half a million.
    imdb_weighted: { value: ( row ) => ( row.score ? ( row.score[ 1 ] * row.score[ 0 ] + 1000 * 65 ) / ( row.score[ 1 ] + 1000 ) : null ) },
    votes: { value: ( row ) => ( row.score ? row.score[ 1 ] : null ) },
    runtime: { value: ( row ) => row.t.runtime || null },
    family: { value: ( row ) => ( row.social ? row.social.watched.length : 0 ) },
    loved: { value: ( row ) => ( row.social ? row.social.loved.length : 0 ) },
    cert: { value: ( row ) => { const at = Filters.CERT_ORDER.indexOf( row.t.certification ); return at < 0 ? null : at; } },
    // Stable for a day, so a random order does not reshuffle on every click.
    random: { value: ( row ) => Sorter.hash( row.t.id + Sorter.today() ) },
  },

  // The order offered in the menu.
  ORDER: [ "added" , "title" , "year" , "imdb" , "imdb_weighted" , "votes" , "rating" , "watched" , "runtime" , "family" , "loved" , "cert" , "updated" , "random" ],

  today() {
    return new Date().toISOString().slice( 0 , 10 );
  },

  hash( text ) {
    let h = 2166136261;
    for ( let i = 0; i < text.length; i += 1 ) {
      h ^= text.charCodeAt( i );
      h = Math.imul( h , 16777619 );
    }
    return h >>> 0;
  },

  compareValues( a , b ) {
    if ( typeof a === "string" || typeof b === "string" ) return String( a ).localeCompare( String( b ) );
    return a - b;
  },

  tieBreak( a , b ) {
    const ta = Sorter.keys.title.value( a ) || "";
    const tb = Sorter.keys.title.value( b ) || "";
    if ( ta !== tb ) return ta < tb ? -1 : 1;
    const ya = a.t.year || 0;
    const yb = b.t.year || 0;
    if ( ya !== yb ) return ya - yb;
    return a.t.id < b.t.id ? -1 : a.t.id > b.t.id ? 1 : 0;
  },

  comparator( steps ) {
    const plan = steps.filter( ( step ) => this.keys[ step.key ] ).map( ( step ) => ( { value: this.keys[ step.key ].value , sign: step.dir === "desc" ? -1 : 1 } ) );
    return ( a , b ) => {
      for ( const step of plan ) {
        const va = step.value( a );
        const vb = step.value( b );
        const missingA = va == null || va === "";
        const missingB = vb == null || vb === "";
        if ( missingA && missingB ) continue;
        if ( missingA ) return 1;
        if ( missingB ) return -1;
        const order = this.compareValues( va , vb );
        if ( order !== 0 ) return order * step.sign;
      }
      return this.tieBreak( a , b );
    };
  },

  sort( rows , steps ) {
    // Values are read many times during a sort; read each once.
    return rows.slice().sort( this.comparator( steps ) );
  },
};
