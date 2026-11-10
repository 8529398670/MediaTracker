// The query: everything that decides what a library screen shows and in
// what order. One query per scope (All, Movies, TV, Radio drama...) -- never
// a global one, which is how a genre picked in Movies used to empty TV.
//
//   {
//     list:    "all" | "watched" | "skipped" | "trash"
//     text:    the search box
//     filters: { genre: { mode: "any", values: ["Drama"] } , year: { from , to , unknown } , ... }
//     sort:    [ { key: "imdb" , dir: "desc" } , { key: "title" , dir: "asc" } ]
//     group:   { by: "none" | "decade" | ... , dir: "asc" | "desc" }
//   }
//
// It lives in the URL hash (codec.js), so back, forward, a bookmark and a
// link sent to someone all reproduce a view exactly, and the last one used on
// each scope is remembered on the account (prefs).
//
// Pure: no DOM.
const Query = {
  // Lists split the library by where each title stands for you, so none of
  // them needs a filter switched on to make sense: Everything is what is
  // still ahead (never watched or skipped titles), Watched and Not for me
  // (skipped, status "dropped") hold the rest, Trash the deleted ones.
  LISTS: [ "all" , "watched" , "skipped" , "trash" ],

  // What each list sorts by until someone says otherwise: watched by when,
  // the rest by what was added last. A hand-made order is a playlist.
  DEFAULT_SORT: {
    watched: [ { key: "watched" , dir: "desc" } ],
    all: [ { key: "added" , dir: "desc" } ],
    skipped: [ { key: "updated" , dir: "desc" } ],
    trash: [ { key: "updated" , dir: "desc" } ],
  },

  defaults( list ) {
    const which = this.LISTS.indexOf( list ) >= 0 ? list : "all";
    return {
      list: which,
      text: "",
      filters: {},
      sort: this.DEFAULT_SORT[ which ].map( ( step ) => Object.assign( {} , step ) ),
      group: { by: "none" , dir: "asc" },
    };
  },

  clone( query ) {
    return JSON.parse( JSON.stringify( query ) );
  },

  // Only what differs from the list's defaults -- that is what the hash and
  // the "Clear all" button care about.
  isDefault( query ) {
    return this.activeCount( query ) === 0 && !query.text && this.sameSort( query.sort , this.defaults( query.list ).sort ) && query.group.by === "none";
  },

  sameSort( a , b ) {
    return JSON.stringify( a ) === JSON.stringify( b );
  },

  activeCount( query ) {
    return Object.keys( query.filters ).filter( ( id ) => Filters.isActive( id , query.filters[ id ] ) ).length;
  },

  equals( a , b ) {
    return JSON.stringify( a ) === JSON.stringify( b );
  },

  // A filter the list already decides is dropped: "Status: dropped" on the
  // Watched list could only ever show nothing.
  normalize( query , scope ) {
    const out = Object.assign( this.defaults( query.list ) , query );
    out.filters = {};
    Object.keys( query.filters || {} ).forEach( ( id ) => {
      if ( Filters.defs[ id ] && Filters.isActive( id , query.filters[ id ] ) && !Filters.subsumed( id , out.list , scope ) ) {
        out.filters[ id ] = query.filters[ id ];
      }
    } );
    if ( !Array.isArray( out.sort ) || !out.sort.length ) out.sort = this.defaults( out.list ).sort;
    out.sort = out.sort.filter( ( step ) => Sorter.keys[ step.key ] ).slice( 0 , 3 );
    if ( !out.sort.length ) out.sort = this.defaults( out.list ).sort;
    if ( !out.group || !Grouper.kinds[ out.group.by ] ) out.group = { by: "none" , dir: "asc" };
    return out;
  },
};
