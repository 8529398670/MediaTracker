// The Appearance screen's tabs: Theme and Cards. Each tab
// has its own hash (#appearance/cards), so a link or a reload lands on it,
// and picking a tab updates the hash without adding a history step.
//
// What is in each tab is drawn elsewhere: the themes by themes_editor.js, the
// card settings by ui/customizer.js, and the settings every card shares
// (front links, Watched corner, Apple TV) by app.js (initCardLinks,
// initCornerWatch, initAppleTv).
const Appearance = {
  TABS: [ "theme" , "cards" ],
  // Tabs that were folded into another.
  MOVED: { links: "cards" },

  init() {
    Dom.all( "[data-appearance-tab]" ).forEach( ( button ) => {
      button.addEventListener( "shown.bs.tab" , () => {
        const tab = button.getAttribute( "data-appearance-tab" );
        if ( tab === "cards" ) Customizer.show();
        const hash = "#appearance" + ( tab === "theme" ? "" : "/" + tab );
        if ( Nav.screen() === "appearance" && window.location.hash !== hash ) window.history.replaceState( null , "" , hash );
      } );
    } );
    window.addEventListener( "hashchange" , () => this.route() );
    this.route();
  },

  // The tab named after #appearance/, or Theme.
  route() {
    if ( Nav.screen() !== "appearance" ) return;
    const asked = window.location.hash.replace( /^#/ , "" ).split( /[/?]/ )[ 1 ] || "theme";
    const named = this.MOVED[ asked ] || asked;
    const tab = this.TABS.indexOf( named ) >= 0 ? named : "theme";
    const button = document.querySelector( '[data-appearance-tab="' + tab + '"]' );
    if ( button ) bootstrap.Tab.getOrCreateInstance( button ).show();
    if ( tab === "cards" ) Customizer.show();
  },
};
