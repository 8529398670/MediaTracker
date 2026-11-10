#!/usr/bin/env node
// Holds every built-in theme in static/js/theme.js to a readable contrast: the
// same maths and pairs the Appearance screen checks (Theme.check), so a colour
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

let failed = 0;
Theme.builtIn.forEach( ( theme ) => {
  Theme.check( theme ).forEach( ( pair ) => {
    failed += 1;
    const colours = Theme.colours( theme );
    console.error( theme.id + ": " + pair.name + " is " + pair.ratio.toFixed( 2 ) + " (" + colours[ pair.front ] + " on " + colours[ pair.back ] + ")" );
  } );
} );
if ( failed > 0 ) process.exit( 1 );
console.log( "ok: " + Theme.builtIn.length + " themes" );
