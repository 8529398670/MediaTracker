// Tests for the pure query layer (static/js/query/). Runs in a browser
// (open index.html) or under node (node tests/js/run.mjs); no build step,
// no test framework -- test( name , fn ) and ok( value , message ).

const rows = [
  { t: { id: "1" , title: "Heat" , year: 1995 , type: "movie" , genres: [ "Crime" , "Drama" ] , tags: [] , added_at: "2026-01-03" } , s: { status: "queue" , rating: 8 } , social: { watched: [] , loved: [] } , score: [ 83 , 700000 ] },
  { t: { id: "2" , title: "The Alien" , year: 1979 , type: "movie" , genres: [ "Horror" ] , tags: [ "space" ] , added_at: "2026-01-01" } , s: { status: "watched" , rating: null } , social: { watched: [ 2 ] , loved: [] } , score: [ 85 , 900000 ] },
  { t: { id: "3" , title: "Arrival" , year: null , type: "movie" , genres: [ "Drama" ] , tags: [] , added_at: "2026-01-02" } , s: { status: "queue" , rating: null } , social: null , score: null },
];
const ids = ( list ) => list.map( ( row ) => row.t.id ).join( "," );

test( "codec round-trips a query and leaves defaults out" , () => {
  const query = Query.defaults( "all" );
  query.text = "noir";
  query.filters.genre = { mode: "all" , values: [ "Crime" , "Drama" ] };
  query.filters.year = { from: 1940 , to: 1959 , unknown: true };
  query.filters.rating = { mode: "unrated" , from: null , to: null };
  query.sort = [ { key: "imdb" , dir: "desc" } , { key: "title" , dir: "asc" } ];
  query.group = { by: "decade" , dir: "desc" };
  const hash = QueryCodec.format( "library" , "movie" , query );
  ok( hash.indexOf( "genre=all:Crime,Drama" ) > 0 , hash );
  const back = QueryCodec.parse( hash );
  ok( back.scope === "movie" && back.query.list === "all" , "scope and list" );
  ok( JSON.stringify( back.query ) === JSON.stringify( Query.normalize( query , "movie" ) ) , JSON.stringify( back.query ) );
  ok( QueryCodec.format( "library" , "all" , Query.defaults( "all" ) ) === "#library/all/all" , "defaults are left out" );
} );

test( "a filter the list already decides is dropped" , () => {
  const query = Query.defaults( "watched" );
  query.filters.status = { mode: "any" , values: [ "dropped" ] };
  ok( !( "status" in Query.normalize( query , "all" ).filters ) , "status on Watched" );
  const all = Query.defaults( "all" );
  all.filters.type = { mode: "any" , values: [ "tv" ] };
  ok( !( "type" in Query.normalize( all , "movie" ).filters ) , "type inside one type" );
} );

test( "missing values sort last in both directions" , () => {
  ok( ids( Sorter.sort( rows , [ { key: "year" , dir: "asc" } ] ) ) === "2,1,3" , "asc" );
  ok( ids( Sorter.sort( rows , [ { key: "year" , dir: "desc" } ] ) ) === "1,2,3" , "desc" );
  ok( ids( Sorter.sort( rows , [ { key: "imdb" , dir: "desc" } ] ) ) === "2,1,3" , "imdb" );
} );

test( "ties break on title, ignoring articles" , () => {
  const same = rows.map( ( row ) => Object.assign( {} , row , { t: Object.assign( {} , row.t , { year: 2000 } ) } ) );
  ok( ids( Sorter.sort( same , [ { key: "year" , dir: "asc" } ] ) ) === "2,3,1" , "Alien, Arrival, Heat" );
} );

test( "grouping is separate from sorting and Unknown is last" , () => {
  const groups = Grouper.group( Sorter.sort( rows , [ { key: "title" , dir: "asc" } ] ) , { by: "decade" , dir: "desc" } , "movie" );
  ok( groups.map( ( g ) => g.value ).join( "," ) === "1990,1970," , JSON.stringify( groups.map( ( g ) => g.value ) ) );
  ok( groups[ 0 ].key === "movie|decade|1990" , groups[ 0 ].key );
  const asc = Grouper.group( rows , { by: "decade" , dir: "asc" } , "movie" );
  ok( asc[ asc.length - 1 ].value === null , "unknown last ascending too" );
} );

test( "filters: unrated, year with and without unknown, all-of genres" , () => {
  const keep = ( filters ) => ids( rows.filter( Filters.predicate( filters ) ) );
  ok( keep( { rating: { mode: "unrated" } } ) === "2,3" , "unrated" );
  ok( keep( { year: { from: 1970 , to: 2000 } } ) === "1,2" , "year drops unknown" );
  ok( keep( { year: { from: 1970 , to: 2000 , unknown: true } } ) === "1,2,3" , "year keeps unknown" );
  ok( keep( { genre: { mode: "all" , values: [ "Crime" , "Drama" ] } } ) === "1" , "all of" );
  ok( keep( { genre: { mode: "any" , values: [ "Crime" , "Horror" ] } } ) === "1,2" , "any of" );
  ok( keep( { watchedby: { mode: "any" , values: [ "nobody" ] } } ) === "1,3" , "nobody watched" );
} );

test( "facets count with their own filter lifted" , () => {
  const counts = Facets.count( rows , { genre: { mode: "any" , values: [ "Horror" ] } , year: { from: 1900 , to: 2100 } } , [ "genre" ] );
  ok( counts.genre.get( "Drama" ) === 1 && counts.genre.get( "Horror" ) === 1 , JSON.stringify( Array.from( counts.genre ) ) );
} );

test( "search folds accents and understands operators" , () => {
  const match = Search.matcher( 'heat -alien genre:crime' );
  ok( ids( rows.filter( match ) ) === "1" , "operators" );
  ok( Search.fold( "Amélie & Co." ) === "amelie and co" , Search.fold( "Amélie & Co." ) );
  ok( ids( rows.filter( Search.matcher( "year:1970-1980" ) ) ) === "2" , "year range" );
} );

test( "an old link sorted by the removed manual order falls back to the list default" , () => {
  const parsed = QueryCodec.parse( "#library/all/all?sort=rank" );
  ok( JSON.stringify( parsed.query.sort ) === JSON.stringify( Query.defaults( "all" ).sort ) , JSON.stringify( parsed.query.sort ) );
} );

test( "an old Up next link opens Everything" , () => {
  ok( QueryCodec.parse( "#library/movie/queue?genre=Drama" ).query.list === "all" , "queue -> all" );
} );

test( "Everything hides watched and skipped by default; Watched hides nothing" , () => {
  const all = Query.defaults( "all" );
  ok( Filters.isActive( "hidewatched" , all.filters.hidewatched ) && Filters.isActive( "hideskipped" , all.filters.hideskipped ) , "both on" );
  ok( Object.keys( Query.defaults( "watched" ).filters ).length === 0 , "none on Watched" );
  const skipped = { t: { id: "4" , title: "Cats" , type: "movie" , genres: [] , tags: [] } , s: { status: "dropped" } , social: null , score: null };
  ok( ids( rows.concat( [ skipped ] ).filter( Filters.predicate( all.filters ) ) ) === "1,3" , "watched and dropped left out" );
  ok( Query.isDefault( all ) , "a fresh view is the default" );
  ok( QueryCodec.format( "library" , "all" , all ) === "#library/all/all" , "default hides stay out of the URL" );
} );

test( "turning a default hide off round-trips through the URL" , () => {
  const query = Query.defaults( "all" );
  delete query.filters.hidewatched;
  const hash = QueryCodec.format( "library" , "all" , query );
  ok( hash === "#library/all/all?hidewatched=off" , hash );
  const back = QueryCodec.parse( hash ).query;
  ok( !( "hidewatched" in back.filters ) && Filters.isActive( "hideskipped" , back.filters.hideskipped ) , JSON.stringify( back.filters ) );
  ok( !Query.isDefault( back ) , "not the default any more" );
  ok( ids( rows.filter( Filters.predicate( back.filters ) ) ) === "1,2,3" , "watched shows again" );
} );

test( "a drop lands on the number of the place it is dropped" , () => {
  const ids = [ "a" , "b" , "c" , "d" ];
  ok( OrderDrag.position( ids , "d" , "a" , false ) === 1 , "before the first is 1" );
  ok( OrderDrag.position( ids , "a" , "d" , true ) === 4 , "after the last is the end" );
  ok( OrderDrag.position( ids , "a" , "c" , false ) === 2 , "moving down counts without itself" );
  ok( OrderDrag.position( ids , "d" , "b" , true ) === 3 , "moving up" );
  ok( OrderDrag.position( ids , "a" , "zz" , false ) === 4 , "an unknown target is the end" );
} );

// Genres: a slice of the rules app/media/genres.py sends in the library
// payload, put back at the end so the tests above keep plain genres.
function withGenreRules( fn ) {
  Genres.use( {
    parents: { "Film Noir": "Crime" , "Musical": "Music" },
    compounds: [
      [ "Romantic Comedy" , [ "Romance" , "Comedy" ] ],
      [ "Comedy Drama" , [ "Comedy" , "Drama" ] ],
      [ "Musical Comedy" , [ "Musical" , "Comedy" ] ],
      [ "Musical Comedy" , [ "Music" , "Comedy" ] ],
      [ "Romantic Drama" , [ "Romance" , "Drama" ] ],
      [ "Crime Drama" , [ "Crime" , "Drama" ] ],
    ],
  } );
  try { fn(); } finally { Genres.use( {} ); }
}

const genreRows = () => [
  { t: { id: "a" , title: "Bride Wars" , genres: [ "Romance" , "Comedy" ] , tags: [] , rev: 1 } , s: null },
  { t: { id: "b" , title: "Airplane" , genres: [ "Comedy" ] , tags: [] , rev: 1 } , s: null },
  { t: { id: "c" , title: "Casablanca" , genres: [ "Romance" , "Drama" ] , tags: [] , rev: 1 } , s: null },
];

test( "a card reads each genre once, compounds first, leftovers kept" , () => withGenreRules( () => {
  const labels = ( list ) => Genres.labels( list ).join( "|" );
  ok( labels( [ "Romance" , "Comedy" ] ) === "Romantic Comedy" , labels( [ "Romance" , "Comedy" ] ) );
  ok( labels( [ "Comedy" , "Romance" , "Drama" ] ) === "Romantic Comedy|Drama" , labels( [ "Comedy" , "Romance" , "Drama" ] ) );
  ok( labels( [ "Horror" ] ) === "Horror" , "a lone genre stands" );
  ok( labels( [] ) === "" && labels( undefined ) === "" , "nothing is nothing" );
} ) );

test( "a specific genre hides its parent on a card and keeps its own name" , () => withGenreRules( () => {
  const labels = ( list ) => Genres.labels( list ).join( "|" );
  ok( labels( [ "Film Noir" , "Crime" ] ) === "Film Noir" , labels( [ "Film Noir" , "Crime" ] ) );
  ok( labels( [ "Film Noir" , "Crime" , "Drama" ] ) === "Film Noir|Drama" , labels( [ "Film Noir" , "Crime" , "Drama" ] ) );
  ok( labels( [ "Musical" , "Music" , "Comedy" ] ) === "Musical Comedy" , labels( [ "Musical" , "Music" , "Comedy" ] ) );
} ) );

test( "terms hold the ingredients, the parents and every compound" , () => withGenreRules( () => {
  const terms = Genres.terms( [ "Comedy" , "Romance" , "Drama" ] );
  [ "Comedy" , "Romance" , "Drama" , "Romantic Comedy" , "Comedy Drama" , "Romantic Drama" ].forEach( ( name ) => ok( terms.indexOf( name ) >= 0 , name ) );
  ok( Genres.terms( [ "Film Noir" ] ).join( "|" ) === "Film Noir|Crime" , Genres.terms( [ "Film Noir" ] ).join( "|" ) );
  ok( Genres.terms( [ "Film Noir" , "Drama" ] ).indexOf( "Crime Drama" ) >= 0 , "a parent can complete a compound" );
} ) );

test( "Romantic Comedy filters and counts, and Comedy still finds it" , () => withGenreRules( () => {
  const list = genreRows();
  const keep = ( filters ) => ids( list.filter( Filters.predicate( filters ) ) );
  ok( keep( { genre: { mode: "any" , values: [ "Romantic Comedy" ] } } ) === "a" , "the compound" );
  ok( keep( { genre: { mode: "any" , values: [ "Comedy" ] } } ) === "a,b" , "the ingredient" );
  const counts = Facets.count( list , {} , [ "genre" ] ).genre;
  ok( counts.get( "Romantic Comedy" ) === 1 && counts.get( "Comedy" ) === 2 && counts.get( "Romance" ) === 2 , JSON.stringify( Array.from( counts ) ) );
  const ranked = Facets.ranked( counts , [] ).map( ( entry ) => entry[ 0 ] );
  ok( ranked[ 0 ] === "Comedy" && ranked.indexOf( "Romantic Comedy" ) > 1 , "most used first: " + ranked.join( "," ) );
} ) );

test( "search finds a compound as words and as genre:" , () => withGenreRules( () => {
  const list = genreRows();
  const found = ( text ) => ids( list.filter( Search.matcher( text ) ) );
  ok( found( "romantic comedy" ) === "a" , found( "romantic comedy" ) );
  ok( found( 'genre:"romantic comedy"' ) === "a" , found( 'genre:"romantic comedy"' ) );
  ok( found( "genre:romance" ) === "a,c" , found( "genre:romance" ) );
} ) );

test( "grouping by first genre uses what the card shows" , () => withGenreRules( () => {
  const groups = Grouper.group( genreRows() , { by: "genre" , dir: "asc" } , "t" ).map( ( group ) => group.value );
  ok( groups.indexOf( "Romantic Comedy" ) >= 0 && groups.indexOf( "Romance" ) < 0 , groups.join( "," ) );
} ) );
