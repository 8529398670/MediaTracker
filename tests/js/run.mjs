// node tests/js/run.mjs -- runs the pure-JS tests without a browser. The
// app's files are plain scripts that each declare one global, so they are
// read and evaluated in one shared context, in the order index.html loads
// them.
import { readFileSync } from "node:fs";
import { dirname , join } from "node:path";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

const here = dirname( fileURLToPath( import.meta.url ) );
const root = join( here , ".." , ".." , "static" , "js" );
const files = [ "query/search.js" , "query/filters.js" , "query/sort.js" , "query/group.js" , "query/facets.js" , "query/model.js" , "query/codec.js" , "ui/orderdrag.js" ];
const results = [];
const context = vm.createContext( {
  URLSearchParams,
  console,
  test( name , fn ) {
    try { fn(); results.push( [ name , null ] ); } catch ( error ) { results.push( [ name , error ] ); }
  },
  ok( value , message ) {
    if ( !value ) throw new Error( message || "not ok" );
  },
} );
const source = files.map( ( file ) => readFileSync( join( root , file ) , "utf8" ) ).join( "\n" ) + "\n" + readFileSync( join( here , "query.test.js" ) , "utf8" );
vm.runInContext( source , context , { filename: "query-bundle.js" } );
let failed = 0;
for ( const [ name , error ] of results ) {
  console.log( ( error ? "FAIL " : "ok   " ) + name + ( error ? "\n     " + error.message : "" ) );
  if ( error ) failed += 1;
}
console.log( `${ results.length - failed } passed, ${ failed } failed` );
process.exit( failed ? 1 : 0 );
