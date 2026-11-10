#!/usr/bin/env node
// Holds every built-in theme in static/js/theme.js to a readable contrast: the
// same maths and pairs the Appearance screen checks (Theme.check), so a color
// added to one cannot quietly fail. Run by the tests, or on its own:
// node scripts/check_themes.js
const fs = require( "fs" );
const path = require( "path" );
const vm = require( "vm" );

const source = fs.readFileSync( path.join( __dirname , ".." , "static" , "js" , "theme.js" ) , "utf8" );
const page = {
  document: { documentElement: { setAttribute() {} , removeAttribute() {} , style: { setProperty() {} } } },
  window: { localStorage: { getItem() { return ""; } } },
};
vm.createContext( page );
vm.runInContext( source + "\nglobalThis.Theme = Theme;" , page );
const Theme = page.Theme;

// Each built-in theme as it starts, and switched to the mode it keeps its
// other colors for (WSU's dark).
const looks = [];
Theme.builtIn.forEach( ( theme ) => {
  looks.push( { label: theme.id , theme: theme } );
  Object.keys( Theme.modes ).forEach( ( mode ) => {
    if ( theme[ mode ] ) looks.push( { label: theme.id + " (" + mode + ")" , theme: Theme.setMode( Theme.copy( theme ) , mode ) } );
  } );
} );

let failed = 0;
looks.forEach( ( { label , theme } ) => {
  Theme.check( theme ).forEach( ( pair ) => {
    failed += 1;
    const colors = Theme.colors( theme );
    console.error( label + ": " + pair.name + " is " + pair.ratio.toFixed( 2 ) + " (" + colors[ pair.front ] + " on " + colors[ pair.back ] + ")" );
  } );
} );
if ( failed > 0 ) process.exit( 1 );
console.log( "ok: " + Theme.builtIn.length + " themes" );
