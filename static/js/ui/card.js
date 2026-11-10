// One title, drawn as a card from (row, card config). What it shows and in
// what order is the person's own choice (Prefs.card / customizer.js); this
// file only knows how to draw each piece.
//
// Buttons are real Bootstrap buttons with a word on them -- "Watched", "Up
// next", "Love", "IMDb" -- not bare 15px glyphs. On a narrow card the words
// fold away and the buttons keep a 44px target (style.css, container query).
//
// Built with Dom.el only: titles, notes and names are user data.
const Card = {
  // The handlers a screen gives every card: { act( button , row , event ) ,
  // filter( id , value ) , open( row ) , select( row , event ) }.
  handlers: null,

  INLINE: [ "type" , "status" , "runtime" , "cert" , "imdb" , "tmdb" , "myrating" , "added" , "watched_on" ],

  build( row , card , options ) {
    const settings = options || {};
    const t = row.t;
    const s = row.s || Library.EMPTY_STATE;
    const status = s.status || "none";
    const classes = [ "media-card" , "card" , "status-" + status ];
    if ( s.heart ) classes.push( "is-loved" );
    if ( t.deleted_at ) classes.push( "is-deleted" );
    if ( settings.selected ) classes.push( "is-selected" );
    const article = Dom.el( "article" , { class: classes.join( " " ) , attrs: { "data-id": t.id , "data-key": "card-" + t.id } } );

    if ( settings.selecting ) {
      const box = Dom.el( "input" , { class: "form-check-input media-select" , attrs: { type: "checkbox" , "aria-label": I18n.fill( "card.select" , { title: t.title } ) } } );
      box.checked = Boolean( settings.selected );
      article.appendChild( box );
    }

    if ( card.fields.indexOf( "poster" ) >= 0 ) article.appendChild( this.poster( row ) );
    // Watched, on the poster's top-right corner. In list and compact (and a
    // grid card with no poster) it is the first button on the face instead;
    // style.css shows whichever one fits the layout.
    const watch = t.deleted_at ? null : this.watchButton( row , "media-watch" );
    if ( watch ) article.appendChild( watch );

    const body = Dom.el( "div" , { class: "card-body media-body" } );
    body.appendChild( this.titleLine( row , card ) );
    let meta = null;
    card.fields.forEach( ( field ) => {
      if ( field === "poster" || field === "year" ) return;
      if ( this.INLINE.indexOf( field ) >= 0 ) {
        const piece = this.inline( field , row );
        if ( !piece ) return;
        if ( !meta ) {
          meta = Dom.el( "div" , { class: "media-meta" } );
          body.appendChild( meta );
        }
        meta.appendChild( piece );
        return;
      }
      const block = this.block( field , row );
      if ( block ) body.appendChild( block );
    } );
    if ( t.deleted_at ) {
      body.appendChild( Dom.el( "p" , { class: "small text-danger mb-0" , text: I18n.fill( "card.deleted_on" , { date: Vocab.date( t.deleted_at ) } ) } ) );
    }
    article.appendChild( body );

    if ( t.deleted_at ) {
      article.appendChild( this.buttonRow( "card-footer media-actions" , [ "restore" ] , row ) );
      return article;
    }
    // The face: Watched, the chosen links and More. More opens the title's
    // Details, which carries every other button (Vocab.detailsButtons). A
    // Discover film not in the library has no Details, so its More opens a
    // row of its own buttons on the card instead.
    const footer = this.buttonRow( "card-footer media-actions" , Vocab.mainButtons() , row );
    const faceWatch = this.watchButton( row , "media-watch-face" );
    if ( faceWatch ) footer.insertBefore( faceWatch , footer.firstChild );
    article.appendChild( footer );
    if ( !( row.discover && !row.inLibrary ) ) {
      footer.appendChild( this.makeButton( "edit" , "three-dots" , I18n.get( "card.more" ) , "btn-outline-secondary media-toggle" ,
        { "data-action": "edit" , title: I18n.get( "card.more" ) } ) );
      return article;
    }
    const open = Boolean( settings.expanded ) || this.expanded.has( t.id );
    const toggle = this.makeButton( "expand" , open ? "chevron-up" : "chevron-down" , I18n.get( open ? "card.less" : "card.more" ) , "btn-outline-secondary media-toggle" ,
      { "data-action": "expand" , "aria-expanded": String( open ) , title: I18n.get( open ? "card.less" : "card.more" ) } );
    footer.appendChild( toggle );
    const main = Vocab.mainButtons();
    const more = card.buttons.filter( ( id ) => main.indexOf( id ) < 0 );
    if ( more.indexOf( "parents" ) < 0 && main.indexOf( "parents" ) < 0 ) more.push( "parents" );
    const rank = ( id ) => { const at = Vocab.MORE_ORDER.indexOf( id ); return at < 0 ? Vocab.MORE_ORDER.length : at; };
    more.sort( ( a , b ) => rank( a ) - rank( b ) );
    const details = this.buttonRow( "media-more media-actions" , more , row );
    details.hidden = !open;
    article.appendChild( details );
    if ( open ) article.classList.add( "is-open" );
    return article;
  },

  buttonRow( classes , ids , row ) {
    const box = Dom.el( "div" , { class: classes } );
    ids.forEach( ( id ) => {
      const button = this.button( id , row );
      if ( button ) box.appendChild( button );
    } );
    return box;
  },

  // Which cards have their details open, by title id -- kept here so a card
  // redrawn after a state change stays open.
  expanded: new Set(),

  toggle( article ) {
    const id = article.getAttribute( "data-id" );
    const details = article.querySelector( ".media-more" );
    if ( !details ) return;
    const open = details.hidden;
    if ( open ) this.expanded.add( id );
    else this.expanded.delete( id );
    details.hidden = !open;
    article.classList.toggle( "is-open" , open );
    const toggle = article.querySelector( ".media-toggle" );
    if ( toggle ) {
      const text = I18n.get( open ? "card.less" : "card.more" );
      toggle.setAttribute( "aria-expanded" , String( open ) );
      toggle.setAttribute( "title" , text );
      Dom.clear( toggle );
      toggle.appendChild( this.icon( open ? "chevron-up" : "chevron-down" ) );
      toggle.appendChild( Dom.el( "span" , { class: "btn-label" , text: text } ) );
    }
  },

  // A click on the card itself (poster, title, empty space) opens or closes
  // its details row; links, chips and buttons keep doing their own thing.
  // A card with no details row (every library card) answers false, and the
  // screen opens its Details instead.
  clicked( event , article ) {
    if ( event.target.closest( "a, input, .dropdown-menu, [data-bs-toggle], [data-filter], [data-action]:not([data-action='open'])" ) ) return false;
    if ( !article.querySelector( ".media-more" ) ) return false;
    this.toggle( article );
    return true;
  },

  icon( name ) {
    return Dom.el( "i" , { class: "bi bi-" + name , attrs: { "aria-hidden": "true" } } );
  },

  poster( row ) {
    const t = row.t;
    const button = Dom.el( "button" , {
      class: "media-poster",
      attrs: { type: "button" , "data-action": "open" , "aria-label": I18n.fill( "card.open" , { title: t.title } ) },
    } );
    if ( t.poster ) {
      button.appendChild( Dom.el( "img" , { attrs: { src: t.poster , alt: "" , loading: "lazy" , decoding: "async" } } ) );
    } else {
      button.classList.add( "is-empty" );
      button.appendChild( this.icon( Vocab.typeIcon( t.type ) ) );
      button.appendChild( Dom.el( "span" , { class: "media-poster-name" , text: t.title } ) );
    }
    return button;
  },

  // The Watched toggle: "watched" on a library title, "seen" on a Discover
  // film that is not in the library yet (which adds it as watched).
  watchButton( row , extra ) {
    const id = row.discover && !row.inLibrary ? "seen" : "watched";
    const button = this.button( id , row );
    if ( !button ) return null;
    const text = I18n.get( "card.button_watched" );
    button.classList.add( extra );
    button.setAttribute( "title" , text );
    button.setAttribute( "aria-label" , text );
    const on = this.active( id , row );
    if ( id === "seen" ) button.setAttribute( "aria-pressed" , String( on ) );
    // Grey until it is watched; green only then.
    if ( !on ) button.removeAttribute( "data-tone" );
    const label = button.querySelector( ".btn-label" );
    if ( label ) label.textContent = text;
    // On the poster it is a bare checkmark, not a check in a circle.
    if ( extra === "media-watch" ) button.querySelector( ".bi" ).className = "bi bi-check-lg";
    return button;
  },

  titleLine( row , card ) {
    const t = row.t;
    const heading = Dom.el( "h3" , { class: "media-title" } );
    heading.appendChild( Dom.el( "button" , { class: "media-title-link" , text: t.title , attrs: { type: "button" , "data-action": "open" } } ) );
    if ( card.fields.indexOf( "year" ) >= 0 && t.year ) {
      heading.appendChild( Dom.el( "span" , { class: "media-year" , text: String( t.year ) } ) );
    }
    return heading;
  },

  chip( text , filterId , value , tone ) {
    return Dom.el( "button" , {
      class: "media-chip media-chip-" + ( tone || "plain" ),
      text: text,
      attrs: { type: "button" , "data-filter": filterId , "data-value": value , title: I18n.fill( "card.filter_by" , { value: text } ) },
    } );
  },

  badge( iconName , text , title , extra ) {
    return Dom.el( "span" , {
      class: "media-badge" + ( extra ? " " + extra : "" ),
      attrs: title ? { title: title } : {},
      children: [ this.icon( iconName ) , Dom.el( "span" , { text: text } ) ],
    } );
  },

  inline( field , row ) {
    const t = row.t;
    const s = row.s || {};
    switch ( field ) {
      case "type": return this.chip( Vocab.typeLabel( t.type ) , "type" , t.type );
      case "status":
        return s.status ? this.badge( Vocab.STATUS_ICON[ s.status ] , I18n.get( "status." + s.status ) , null , "media-badge-" + Vocab.STATUS_TONE[ s.status ] ) : null;
      case "runtime": return t.runtime ? this.badge( "clock" , Vocab.runtime( t.runtime ) , I18n.get( "card.field_runtime" ) ) : null;
      case "cert": return t.certification ? this.chip( t.certification , "cert" , t.certification , "cert" ) : null;
      case "imdb":
        return row.score ? this.badge( "star-half" , Vocab.score( row.score[ 0 ] ) , I18n.fill( "card.imdb_score" , { votes: Vocab.votes( row.score[ 1 ] ) } ) , "media-badge-imdb" ) : null;
      case "tmdb": return t.ext_rating ? this.badge( "graph-up" , Vocab.score( t.ext_rating ) , I18n.get( "card.field_tmdb" ) ) : null;
      case "myrating": return s.rating ? this.badge( "star-fill" , String( s.rating ) , I18n.get( "card.field_myrating" ) , "media-badge-mine" ) : null;
      case "added": return t.added_at ? this.badge( "calendar-plus" , Vocab.date( t.added_at ) , I18n.get( "card.field_added" ) ) : null;
      case "watched_on": return s.watched_at ? this.badge( "calendar-check" , Vocab.date( s.watched_at ) , I18n.get( "card.field_watched_on" ) ) : null;
      default: return null;
    }
  },

  block( field , row ) {
    const t = row.t;
    const s = row.s || {};
    switch ( field ) {
      case "genres":
        if ( !( t.genres || [] ).length ) return null;
        return Dom.el( "div" , { class: "media-chips" , children: Genres.labels( t.genres ).map( ( genre ) => this.chip( genre , "genre" , genre , "genre" ) ) } );
      case "tags":
        if ( !( t.tags || [] ).length ) return null;
        return Dom.el( "div" , { class: "media-chips" , children: t.tags.map( ( tag ) => this.chip( "#" + tag , "tag" , tag , "tag" ) ) } );
      case "creator":
        return t.creator ? Dom.el( "p" , { class: "media-line" , children: [ this.icon( "person-video3" ) , Dom.el( "span" , { text: t.creator } ) ] } ) : null;
      case "cast":
        return ( t.cast || [] ).length ? Dom.el( "p" , { class: "media-line" , children: [ this.icon( "people" ) , Dom.el( "span" , { text: t.cast.slice( 0 , 4 ).join( ", " ) } ) ] } ) : null;
      case "overview":
        return t.overview ? Dom.el( "p" , { class: "media-overview" , text: t.overview } ) : null;
      case "notes":
        return t.notes ? Dom.el( "p" , { class: "media-note" , children: [ this.icon( "journal-text" ) , Dom.el( "span" , { text: t.notes } ) ] } ) : null;
      case "mynote":
        return s.note ? Dom.el( "p" , { class: "media-note media-note-mine" , children: [ this.icon( "sticky" ) , Dom.el( "span" , { text: s.note } ) ] } ) : null;
      case "family":
        return this.family( row );
      default:
        return null;
    }
  },

  // "Watched by Mom, Dad · Loved by Cameron" -- everyone but the subject,
  // whose own state the buttons already show.
  family( row ) {
    const social = row.social;
    if ( !social ) return null;
    const others = ( list ) => list.filter( ( id ) => id !== Library.subject ).map( ( id ) => Vocab.personName( id ) );
    const parts = [];
    const watched = others( social.watched );
    const watching = others( social.watching );
    const loved = others( social.loved );
    if ( watched.length ) parts.push( this.badge( "check-circle" , watched.join( ", " ) , I18n.get( "card.family_watched" ) , "media-badge-family" ) );
    if ( watching.length ) parts.push( this.badge( "play-circle" , watching.join( ", " ) , I18n.get( "card.family_watching" ) , "media-badge-family" ) );
    if ( loved.length ) parts.push( this.badge( "heart-fill" , loved.join( ", " ) , I18n.get( "card.family_loved" ) , "media-badge-family media-badge-loved" ) );
    if ( !parts.length ) return null;
    return Dom.el( "div" , { class: "media-family" , children: parts } );
  },

  // -- buttons ------------------------------------------------------------

  active( id , row ) {
    const s = row.s || {};
    switch ( id ) {
      case "watched": return s.status === "watched";
      case "queue": return s.status === "queue" || s.status === "watching";
      case "watching": return s.status === "watching";
      case "drop": return s.status === "dropped";
      case "love": return Boolean( s.heart );
      case "rate": return Boolean( s.rating );
      case "add": return Boolean( row.inLibrary );
      case "seen": return s.status === "watched";
      case "skip": return row.verdict === "skip";
      default: return false;
    }
  },

  label( id , row ) {
    const s = row.s || {};
    if ( id === "rate" && s.rating ) return I18n.fill( "card.button_rated" , { rating: s.rating } );
    if ( id === "queue" && ( s.status === "queue" || s.status === "watching" ) ) return I18n.get( "card.button_queued" );
    if ( id === "love" && s.heart ) return I18n.get( "card.button_loved" );
    if ( id === "add" && row.inLibrary ) return I18n.get( "card.button_in_library" );
    if ( id === "skip" && row.verdict === "skip" ) return I18n.get( "card.button_skipped" );
    return I18n.get( "card.button_" + id );
  },

  button( id , row ) {
    const t = row.t;
    if ( id === "restore" ) {
      return this.makeButton( "restore" , "arrow-counterclockwise" , I18n.get( "card.button_restore" ) , "btn-outline-secondary" , { "data-action": "restore" , "data-tone": "primary" } );
    }
    const def = Vocab.BUTTONS[ id ];
    if ( !def ) return null;
    const text = this.label( id , row );
    if ( def.kind === "link" ) {
      const href = Vocab.href( id , t );
      if ( !href ) return null;
      const direct = Vocab.direct( id , t );
      const link = Dom.el( "a" , {
        class: "btn btn-sm media-btn btn-outline-secondary" + ( direct ? "" : " is-search" ),
        attrs: {
          href: href,
          target: Vocab.target( href ),
          rel: "noopener noreferrer",
          title: I18n.fill( direct ? "card.link_direct" : "card.link_search" , { site: text , title: t.title } ),
        },
        children: [ this.icon( def.icon ) , Dom.el( "span" , { class: "btn-label" , text: text } ) ],
      } );
      return link;
    }
    const on = this.active( id , row );
    const tone = def.tone || "secondary";
    const attrs = { "data-action": id , "aria-label": text , title: text };
    if ( def.kind === "state" && id !== "rate" ) attrs[ "aria-pressed" ] = String( on );
    // Off, every button is the same neutral outline and only its icon carries
    // the tone; on, it is a soft tint of the tone, not a solid fill, so a
    // card with three things on is not three slabs of colour.
    const button = this.makeButton( id , on && def.activeIcon ? def.activeIcon : def.icon , text , on ? "btn-soft-" + tone : "btn-outline-secondary" , attrs );
    button.setAttribute( "data-tone" , tone );
    if ( id === "rate" ) return this.rateMenu( button , row );
    if ( id === "playlist" ) return row.discover && !row.inLibrary ? null : this.playlistMenu( button , row );
    if ( id === "edit" && !row.inLibrary && row.discover ) return null;
    if ( def.kind === "action" && !def.tone ) button.removeAttribute( "data-tone" );
    return button;
  },

  makeButton( id , iconName , text , tone , attrs ) {
    return Dom.el( "button" , {
      class: "btn btn-sm media-btn " + tone,
      attrs: Object.assign( { type: "button" } , attrs ),
      children: [ this.icon( iconName ) , Dom.el( "span" , { class: "btn-label" , text: text } ) ],
    } );
  },

  // Playlist opens a menu of your playlists, ticked where this title is in
  // one, and New playlist. Filled as it opens, so it is never stale.
  playlistMenu( button , row ) {
    button.setAttribute( "data-bs-toggle" , "dropdown" );
    button.setAttribute( "aria-expanded" , "false" );
    button.removeAttribute( "data-action" );
    const menu = Dom.el( "ul" , { class: "dropdown-menu playlist-menu" } );
    const box = Dom.el( "div" , { class: "dropdown media-playlist" , children: [ button , menu ] } );
    box.addEventListener( "show.bs.dropdown" , () => {
      Dom.clear( menu );
      menu.appendChild( Dom.el( "li" , { children: [ Dom.el( "h3" , { class: "dropdown-header" , text: I18n.get( "playlist.menu_heading" ) } ) ] } ) );
      if ( !Playlists.list.length ) menu.appendChild( Dom.el( "li" , { children: [ Dom.el( "span" , { class: "dropdown-item-text small text-body-secondary" , text: I18n.get( "playlist.menu_none" ) } ) ] } ) );
      Playlists.list.forEach( ( playlist ) => {
        const on = playlist.items.indexOf( row.t.id ) >= 0;
        menu.appendChild( Dom.el( "li" , { children: [ Dom.el( "button" , {
          class: "dropdown-item" + ( on ? " active" : "" ),
          attrs: { type: "button" , "data-action": "playlist" , "data-value": String( playlist.id ) , "aria-pressed": String( on ) },
          children: [ this.icon( on ? "check-square-fill" : "square" ) , Dom.el( "span" , { text: " " + playlist.name } ) ],
        } ) ] } ) );
      } );
      menu.appendChild( Dom.el( "li" , { children: [ Dom.el( "hr" , { class: "dropdown-divider" } ) ] } ) );
      menu.appendChild( Dom.el( "li" , { children: [ Dom.el( "button" , {
        class: "dropdown-item",
        attrs: { type: "button" , "data-action": "playlist" , "data-value": "new" },
        children: [ this.icon( "plus-lg" ) , Dom.el( "span" , { text: " " + I18n.get( "playlist.menu_new" ) } ) ],
      } ) ] } ) );
    } );
    return box;
  },

  // Rate opens a small menu: 1-10 and Clear. Bootstrap's dropdown is wired by
  // its data attribute, which it handles by delegation, so built cards need
  // no setup.
  rateMenu( button , row ) {
    button.setAttribute( "data-bs-toggle" , "dropdown" );
    button.setAttribute( "aria-expanded" , "false" );
    button.removeAttribute( "data-action" );
    const s = row.s || {};
    const grid = Dom.el( "div" , { class: "rate-grid" } );
    for ( let n = 1; n <= 10; n += 1 ) {
      grid.appendChild( Dom.el( "button" , {
        class: "btn btn-sm " + ( s.rating === n ? "btn-warning" : "btn-outline-warning" ),
        text: String( n ),
        attrs: { type: "button" , "data-action": "rate" , "data-value": String( n ) , "aria-label": I18n.fill( "card.rate_value" , { n: n } ) },
      } ) );
    }
    const menu = Dom.el( "div" , { class: "dropdown-menu rate-menu p-2" , children: [
      Dom.el( "div" , { class: "small text-body-secondary mb-1" , text: I18n.get( "card.rate_heading" ) } ),
      grid,
      Dom.el( "button" , { class: "btn btn-sm btn-link w-100 mt-1" , text: I18n.get( "card.rate_clear" ) , attrs: { type: "button" , "data-action": "rate" , "data-value": "" } } ),
    ] } );
    return Dom.el( "div" , { class: "dropdown media-rate" , children: [ button , menu ] } );
  },
};
