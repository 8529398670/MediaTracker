// A title's genres, read the two ways the app needs them. A title stores plain
// ingredients (Romance, Comedy); the specific genres people actually use are
// worked out from them, by the rules in app/media/genres.py, which arrive with
// the library payload so that they are written down in one place only.
//
//   terms  everything a title can be found by: filters, counts, search,
//          so picking Comedy still finds a romantic comedy
//   labels what a card shows: each genre spent once, so Romance, Comedy and
//          Drama reads Romantic Comedy, Drama
//
// Pure: no DOM.
const Genres = {
  parents: {},
  compounds: [],

  use( rules ) {
    this.parents = rules.parents || {};
    this.compounds = rules.compounds || [];
  },

  terms( genres ) {
    const out = ( genres || [] ).slice();
    ( genres || [] ).forEach( ( name ) => {
      const parent = this.parents[ name ];
      if ( parent && out.indexOf( parent ) < 0 ) out.push( parent );
    } );
    const have = out.slice();
    this.compounds.forEach( ( [ label , parts ] ) => {
      if ( parts.every( ( part ) => have.indexOf( part ) >= 0 ) && out.indexOf( label ) < 0 ) out.push( label );
    } );
    return out;
  },

  labels( genres ) {
    const list = genres || [];
    // A film noir need not also say Crime.
    const implied = list.map( ( name ) => this.parents[ name ] );
    const left = list.filter( ( name ) => implied.indexOf( name ) < 0 );
    const out = [];
    this.compounds.forEach( ( [ label , parts ] ) => {
      if ( !parts.every( ( part ) => left.indexOf( part ) >= 0 ) ) return;
      parts.forEach( ( part ) => left.splice( left.indexOf( part ) , 1 ) );
      if ( out.indexOf( label ) < 0 ) out.push( label );
    } );
    return out.concat( left );
  },
};
