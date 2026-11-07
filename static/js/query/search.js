// Text search over the library: what the search box types into.
//
// Plain words must all appear somewhere in a title's text (its name, year,
// creator, cast, genres, tags and the family's notes), accents and
// punctuation ignored. A few operators narrow it further, so a search can say
// what the filter sheet says without opening it:
//
//   "exact phrase"     -word (must not appear)
//   genre:drama        tag:pre-code       cast:hepburn     by:murnau
//   year:1930  year:1930-1939           note:"rewatch"
//
// Pure: no DOM, so tests/js can run it.
const Search = {
  fold( value ) {
    return String( value == null ? "" : value )
      .normalize( "NFKD" )
      .replace( /\p{M}+/gu , "" )
      .toLowerCase()
      .replace( /[&+]/g , " and " )
      .replace( /['‘’ʼ`´]/g , "" )
      .replace( /[^\p{L}\p{N}_\s]+/gu , " " )
      .split( /\s+/ )
      .filter( Boolean )
      .join( " " );
  },

  FIELDS: [ "genre" , "tag" , "cast" , "by" , "year" , "note" , "title" ],

  // "noir -remake genre:crime year:1940-1949" ->
  // { terms: ["noir"], not: ["remake"], fields: [{ field, value, not }] }
  parse( text ) {
    const out = { terms: [] , not: [] , fields: [] };
    const pattern = /(-?)(?:(\w+):)?(?:"([^"]*)"|(\S+))/g;
    let match;
    while ( ( match = pattern.exec( String( text || "" ) ) ) ) {
      const negate = match[ 1 ] === "-";
      const field = match[ 2 ] ? match[ 2 ].toLowerCase() : "";
      const value = match[ 3 ] !== undefined ? match[ 3 ] : match[ 4 ];
      if ( field && this.FIELDS.indexOf( field ) >= 0 ) {
        out.fields.push( { field: field , value: value , not: negate } );
        continue;
      }
      // An unknown "word:thing" is just a word with a colon in it.
      const whole = this.fold( ( field ? field + ":" : "" ) + value );
      if ( !whole ) continue;
      ( negate ? out.not : out.terms ).push( whole );
    }
    return out;
  },

  // Everything a row can be found by, folded once and kept on the row.
  haystack( row ) {
    if ( row._hay !== undefined && row._hayRev === row.t.rev ) return row._hay;
    const t = row.t;
    const parts = [ t.title , t.year , t.creator , ( t.cast || [] ).join( " " ) , Genres.terms( t.genres ).join( " " ) ,
      ( t.tags || [] ).join( " " ) , t.notes , t.certification ];
    row._hay = " " + this.fold( parts.join( " " ) ) + " ";
    row._hayRev = t.rev;
    return row._hay;
  },

  fieldMatches( row , clause ) {
    const t = row.t;
    const want = this.fold( clause.value );
    const has = function ( list ) {
      return ( list || [] ).some( ( item ) => Search.fold( item ).indexOf( want ) >= 0 );
    };
    switch ( clause.field ) {
      case "genre": return has( Genres.terms( t.genres ) );
      case "tag": return ( t.tags || [] ).some( ( tag ) => Search.fold( tag ) === want || Search.fold( tag ).indexOf( want ) === 0 );
      case "cast": return has( t.cast );
      case "by": return this.fold( t.creator ).indexOf( want ) >= 0;
      case "note": return this.fold( t.notes ).indexOf( want ) >= 0 || this.fold( row.s && row.s.note ).indexOf( want ) >= 0;
      case "title": return this.fold( t.title ).indexOf( want ) >= 0;
      case "year": {
        const range = /^(\d{4})\s*(?:-|\.\.)\s*(\d{4})$/.exec( clause.value );
        if ( range ) return t.year >= Number( range[ 1 ] ) && t.year <= Number( range[ 2 ] );
        return String( t.year || "" ) === String( clause.value ).trim();
      }
      default: return true;
    }
  },

  // Edits between two words, a swap of neighbours counting as one; stops
  // counting past limit.
  distance( a , b , limit ) {
    if ( Math.abs( a.length - b.length ) > limit ) return limit + 1;
    let before = null;
    let previous = Array.from( { length: b.length + 1 } , ( _ , j ) => j );
    for ( let i = 1; i <= a.length; i += 1 ) {
      const row = [ i ];
      let best = i;
      for ( let j = 1; j <= b.length; j += 1 ) {
        let d = Math.min( previous[ j ] + 1 , row[ j - 1 ] + 1 , previous[ j - 1 ] + ( a[ i - 1 ] === b[ j - 1 ] ? 0 : 1 ) );
        if ( before && i > 1 && j > 1 && a[ i - 1 ] === b[ j - 2 ] && a[ i - 2 ] === b[ j - 1 ] ) d = Math.min( d , before[ j - 2 ] + 1 );
        row.push( d );
        best = Math.min( best , d );
      }
      if ( best > limit ) return limit + 1;
      before = previous;
      previous = row;
    }
    return previous[ b.length ];
  },

  // How many typos a word of this length may have and still count.
  slack( word ) {
    return word.length >= 8 ? 2 : word.length >= 4 ? 1 : 0;
  },

  // The search, forgiving spelling: every word typed is within a typo or
  // two of a word in the title -- "forest gump" finds "Forrest Gump". Only
  // for plain words; a search with operators means exactly what it says.
  closeMatcher( text ) {
    const parsed = this.parse( text );
    if ( parsed.not.length || parsed.fields.length || !parsed.terms.length ) return null;
    const words = parsed.terms.join( " " ).split( " " );
    return ( row ) => {
      const title = this.fold( row.t.title ).split( " " );
      return words.every( ( word ) => title.some( ( have ) => have.indexOf( word ) === 0 || this.distance( word , have , this.slack( word ) ) <= this.slack( word ) ) );
    };
  },

  // A parsed query, compiled once, tested against many rows.
  matcher( text ) {
    const parsed = this.parse( text );
    if ( !parsed.terms.length && !parsed.not.length && !parsed.fields.length ) return null;
    return ( row ) => {
      const hay = this.haystack( row );
      for ( const term of parsed.terms ) if ( hay.indexOf( " " + term ) < 0 && hay.indexOf( term ) < 0 ) return false;
      for ( const term of parsed.not ) if ( hay.indexOf( term ) >= 0 ) return false;
      for ( const clause of parsed.fields ) if ( this.fieldMatches( row , clause ) === clause.not ) return false;
      return true;
    };
  },
};
