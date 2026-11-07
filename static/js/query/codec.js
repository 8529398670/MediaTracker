// The query in the URL hash, readable by a person:
//
//   #library/movie/all?q=noir&genre=all:Crime,Drama&year=1940..1959~unknown
//     &sort=-imdb,title&group=decade:desc
//
// Screen, scope and list are the path; text, filters, sort and grouping are
// the query string. Anything left at its default is left out, so a plain
// #library/movie/all means exactly the defaults. An old .../queue link (the
// retired Up next list) opens Everything.
//
// Pure: no DOM (takes and returns strings).
const QueryCodec = {
  parse( hash ) {
    const raw = String( hash || "" ).replace( /^#/ , "" );
    const cut = raw.indexOf( "?" );
    const path = ( cut < 0 ? raw : raw.slice( 0 , cut ) ).split( "/" ).filter( Boolean );
    const params = new URLSearchParams( cut < 0 ? "" : raw.slice( cut + 1 ) );
    const screen = path[ 0 ] || "";
    const scope = path[ 1 ] || "all";
    const list = Query.LISTS.indexOf( path[ 2 ] ) >= 0 ? path[ 2 ] : "all";
    const query = Query.defaults( list );
    query.text = params.get( "q" ) || "";
    Object.keys( Filters.defs ).forEach( ( id ) => {
      // "off" takes away a filter the list starts with (hidewatched=off).
      if ( params.get( id ) === "off" ) { delete query.filters[ id ]; return; }
      const value = Filters.decode( id , params.get( id ) );
      if ( value ) query.filters[ id ] = value;
    } );
    const sort = params.get( "sort" );
    if ( sort ) {
      query.sort = sort.split( "," ).filter( Boolean ).map( ( part ) => ( {
        key: part.replace( /^-/ , "" ),
        dir: part.charAt( 0 ) === "-" ? "desc" : "asc",
      } ) );
    }
    const group = params.get( "group" );
    if ( group ) {
      const halves = group.split( ":" );
      query.group = { by: halves[ 0 ] , dir: halves[ 1 ] === "desc" ? "desc" : "asc" };
    }
    return { screen: screen , scope: scope , hasQuery: cut >= 0 , query: Query.normalize( query , scope ) };
  },

  queryString( query ) {
    const params = new URLSearchParams();
    if ( query.text ) params.set( "q" , query.text );
    const defaults = Query.defaultFilters( query.list );
    Filters.ORDER.forEach( ( id ) => {
      const value = query.filters[ id ];
      const active = Filters.isActive( id , value );
      const standard = Filters.isActive( id , defaults[ id ] );
      if ( active && !( standard && JSON.stringify( value ) === JSON.stringify( defaults[ id ] ) ) ) params.set( id , Filters.encode( id , value ) );
      else if ( !active && standard ) params.set( id , "off" );
    } );
    if ( !Query.sameSort( query.sort , Query.defaults( query.list ).sort ) ) {
      params.set( "sort" , query.sort.map( ( step ) => ( step.dir === "desc" ? "-" : "" ) + step.key ).join( "," ) );
    }
    if ( query.group && query.group.by !== "none" ) params.set( "group" , query.group.by + ( query.group.dir === "desc" ? ":desc" : "" ) );
    // URLSearchParams escapes commas and colons that are perfectly readable
    // in a hash; put them back.
    return params.toString().replace( /%2C/g , "," ).replace( /%3A/g , ":" );
  },

  format( screen , scope , query ) {
    const search = this.queryString( query );
    return "#" + screen + "/" + scope + "/" + query.list + ( search ? "?" + search : "" );
  },
};
