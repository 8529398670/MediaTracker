// The card catalog: every field a card can show and every button it can
// carry, each with its own icon and its own words (language.yaml: card.*).
// Which of them a card actually shows, and in what order, is each person's
// choice (customizer.js), saved on their account.
//
// One icon per meaning, from one icon set (Bootstrap Icons), everywhere in
// the app. The old app used the same shield for "Parents guide" and for "age
// rating", the same star for a score and for statistics, and two icon
// systems side by side.
const Vocab = {
  STATUS_ICON: { queue: "bookmark-fill" , watching: "play-circle-fill" , watched: "check-circle-fill" , dropped: "x-circle-fill" , none: "circle" },
  STATUS_TONE: { queue: "primary" , watching: "warning" , watched: "success" , dropped: "secondary" , none: "light" },

  // Fields, in the order the customizer lists them. The title is always
  // shown and is not in here.
  FIELDS: {
    poster: { icon: "image" },
    year: { icon: "calendar3" },
    type: { icon: "collection" },
    status: { icon: "bookmark" },
    genres: { icon: "tags" },
    runtime: { icon: "clock" },
    cert: { icon: "shield-check" },
    imdb: { icon: "star-half" },
    tmdb: { icon: "graph-up" },
    myrating: { icon: "star-fill" },
    creator: { icon: "person-video3" },
    cast: { icon: "people" },
    overview: { icon: "text-paragraph" },
    tags: { icon: "hash" },
    family: { icon: "people-fill" },
    added: { icon: "calendar-plus" },
    watched_on: { icon: "calendar-check" },
    notes: { icon: "journal-text" },
    mynote: { icon: "sticky" },
  },

  // Buttons. kind: "state" changes my state, "link" opens a page elsewhere,
  // "action" does something here.
  BUTTONS: {
    watched: { kind: "state" , icon: "check-circle" , activeIcon: "check-circle-fill" , tone: "success" },
    queue: { kind: "state" , icon: "bookmark-plus" , activeIcon: "bookmark-check-fill" , tone: "primary" },
    watching: { kind: "state" , icon: "play-circle" , activeIcon: "play-circle-fill" , tone: "warning" },
    drop: { kind: "state" , icon: "x-circle" , activeIcon: "x-circle-fill" , tone: "secondary" },
    love: { kind: "state" , icon: "heart" , activeIcon: "heart-fill" , tone: "danger" },
    rate: { kind: "state" , icon: "star" , activeIcon: "star-fill" , tone: "warning" },
    imdb: { kind: "link" , icon: "ticket-perforated" },
    parents: { kind: "link" , icon: "shield-exclamation" },
    wiki: { kind: "link" , icon: "wikipedia" },
    appletv: { kind: "link" , icon: "apple" },
    justwatch: { kind: "link" , icon: "display" },
    trailer: { kind: "link" , icon: "youtube" },
    edit: { kind: "action" , icon: "pencil-square" },
    playlist: { kind: "action" , icon: "collection-play" , tone: "primary" },
    // Discover only: films not (yet) in the library.
    add: { kind: "action" , icon: "bookmark-plus" , tone: "primary" },
    seen: { kind: "action" , icon: "check-circle" , tone: "success" },
    skip: { kind: "action" , icon: "eye-slash" , tone: "secondary" },
  },

  // Always on the face of every card, after Watched (which sits on the
  // poster's corner in the grid). Everything else waits behind More.
  MAIN_BUTTONS: [ "appletv" , "trailer" , "imdb" ],

  // The buttons at the top of a title's Details (which More opens), in this
  // order: the face's links, then the rest of them, then my state.
  DETAILS_BUTTONS: [ "appletv" , "trailer" , "imdb" , "parents" , "wiki" , "justwatch" , "watched" , "playlist" , "love" ],

  // The order a Discover card's own More row lists its buttons in.
  MORE_ORDER: [ "parents" , "add" , "seen" , "skip" ],

  // The details buttons offered per screen in the customizer.
  SCREEN_BUTTONS: {
    library: [ "watched" , "playlist" , "watching" , "drop" , "love" , "rate" , "parents" , "wiki" , "justwatch" , "edit" ],
    discover: [ "add" , "seen" , "skip" , "parents" , "wiki" , "justwatch" , "edit" ],
  },

  DEFAULT_CARD: {
    layout: "grid",
    size: "m",
    fields: [ "poster" , "year" , "runtime" , "cert" , "imdb" , "genres" , "family" ],
    buttons: [ "watched" , "love" , "rate" , "edit" ],
  },

  DEFAULT_DISCOVER_CARD: {
    layout: "grid",
    size: "m",
    fields: [ "poster" , "year" , "cert" , "imdb" , "genres" , "creator" , "cast" ],
    buttons: [ "add" , "seen" , "skip" , "wiki" ],
  },

  LAYOUTS: [ "grid" , "list" , "compact" ],
  SIZES: [ "s" , "m" , "l" ],

  query( title ) {
    return encodeURIComponent( [ title.title , title.year || "" ].join( " " ).trim() );
  },

  // Where a link button goes. A known id goes straight to the page; without
  // one it is a search there, which is still one tap from what you want.
  href( button , title ) {
    const q = this.query( title );
    switch ( button ) {
      case "imdb": return title.imdb_id ? "https://www.imdb.com/title/" + title.imdb_id + "/" : "https://www.imdb.com/find/?q=" + q;
      case "parents": return title.imdb_id ? "https://www.imdb.com/title/" + title.imdb_id + "/parentalguide" : "";
      case "wiki": return title.wiki_url || "https://en.wikipedia.org/w/index.php?search=" + q;
      case "appletv": return this.appleTv( "https://tv.apple.com/us/" + ( title.apple_tv || "search?term=" + encodeURIComponent( title.title ) ) );
      case "justwatch": return "https://www.justwatch.com/us/search?q=" + encodeURIComponent( title.title );
      case "trailer": return "https://www.youtube.com/results?search_query=" + q + "+trailer";
      default: return "";
    }
  },

  // On a Mac, iPhone or iPad the TV app is already there, so a title it
  // knows opens in the app: the same address under the app's own scheme. A
  // search does too, on the app's Search page. Each person can send them to
  // the website instead (Account, Prefs ui.appletv_app).
  appleDevice() {
    return /Macintosh|Mac OS X|iPhone|iPad|iPod/.test( navigator.userAgent || "" );
  },

  appleTv( url ) {
    if ( !this.appleDevice() || !Prefs.ui( "appletv_app" , true ) ) return url;
    return url.replace( /^https:\/\// , "com.apple.tv://" );
  },

  // A new tab for a web page; none for an app's own scheme, which would
  // otherwise leave an empty tab behind.
  target( href ) {
    return /^https?:/i.test( href ) ? "_blank" : null;
  },

  // A link that goes straight to the title, rather than to a search.
  direct( button , title ) {
    switch ( button ) {
      case "imdb": case "parents": return Boolean( title.imdb_id );
      case "wiki": return Boolean( title.wiki_url );
      case "appletv": return Boolean( title.apple_tv );
      default: return false;
    }
  },

  typeLabel( typeId ) {
    const type = ( Library.types || [] ).find( ( entry ) => entry.id === typeId );
    return type ? type.label : typeId;
  },

  typeIcon( typeId ) {
    const type = ( Library.types || [] ).find( ( entry ) => entry.id === typeId );
    return ( type && type.icon ) || ( typeId === "movie" ? "film" : typeId === "tv" ? "tv" : "collection" );
  },

  personName( id ) {
    const person = ( Library.people || [] ).find( ( entry ) => String( entry.id ) === String( id ) );
    return person ? person.display_name : "#" + id;
  },

  score( tenths ) {
    return ( tenths / 10 ).toFixed( 1 );
  },

  votes( count ) {
    if ( count >= 1000000 ) return ( count / 1000000 ).toFixed( 1 ).replace( /\.0$/ , "" ) + "M";
    if ( count >= 1000 ) return Math.round( count / 1000 ) + "k";
    return String( count );
  },

  runtime( minutes ) {
    if ( !minutes ) return "";
    const h = Math.floor( minutes / 60 );
    const m = minutes % 60;
    return h ? h + "h" + ( m ? " " + m + "m" : "" ) : m + "m";
  },

  date( iso ) {
    if ( !iso ) return "";
    const when = new Date( iso );
    if ( isNaN( when ) ) return "";
    return when.toLocaleDateString( undefined , { year: "numeric" , month: "short" , day: "numeric" } );
  },
};
