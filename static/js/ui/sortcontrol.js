// Sort and group, in the toolbar where they can be seen -- not inside the
// filter sheet. The button reads what is in force ("IMDb, high to low, then
// Title"); its menu has up to three sort keys, each with its own direction,
// and a separate grouping with its own direction.
const SortControl = {
  // Which way "ascending" reads for each key, so the direction button says
  // "A to Z" or "Oldest first" rather than an arrow nobody can decode.
  DIRECTION_WORDS: {
    title: [ "a_z" , "z_a" ],
    year: [ "oldest" , "newest" ],
    added: [ "oldest" , "newest" ],
    updated: [ "oldest" , "newest" ],
    watched: [ "oldest" , "newest" ],
  },

  dirWord( key , dir ) {
    const words = this.DIRECTION_WORDS[ key ] || [ "low_high" , "high_low" ];
    return I18n.get( "sort.dir_" + words[ dir === "desc" ? 1 : 0 ] );
  },

  summary( query ) {
    const first = query.sort[ 0 ];
    let text = I18n.get( "sort.key_" + first.key );
    if ( first.key !== "random" ) text += ", " + this.dirWord( first.key , first.dir ).toLowerCase();
    if ( query.sort.length > 1 ) text += ", " + I18n.fill( "sort.then" , { key: I18n.get( "sort.key_" + query.sort[ 1 ].key ) } );
    return text;
  },

  keys() {
    return Sorter.ORDER;
  },

  render( button , menu , query , change ) {
    Dom.clear( button );
    button.appendChild( Card.icon( "sort-down" ) );
    button.appendChild( Dom.el( "span" , { class: "btn-label" , text: this.summary( query ) } ) );
    Dom.clear( menu );
    menu.appendChild( Dom.el( "h3" , { class: "dropdown-header px-0" , text: I18n.get( "sort.heading" ) } ) );
    query.sort.forEach( ( step , index ) => menu.appendChild( this.stepRow( step , index , query , change ) ) );
    if ( query.sort.length < 3 ) {
      menu.appendChild( Dom.el( "button" , {
        class: "btn btn-sm btn-link px-0",
        attrs: { type: "button" },
        children: [ Card.icon( "plus-lg" ) , Dom.el( "span" , { text: " " + I18n.get( "sort.add_then" ) } ) ],
        on: { click: ( event ) => {
          event.stopPropagation();
          const next = Query.clone( query );
          const used = next.sort.map( ( s ) => s.key );
          const key = this.keys().find( ( k ) => used.indexOf( k ) < 0 && k !== "random" ) || "title";
          next.sort.push( { key: key , dir: "asc" } );
          change( next );
        } },
      } ) );
    }
    menu.appendChild( Dom.el( "hr" , { class: "my-2" } ) );
    menu.appendChild( Dom.el( "h3" , { class: "dropdown-header px-0" , text: I18n.get( "group.heading" ) } ) );
    menu.appendChild( this.groupRow( query , change ) );
    menu.appendChild( Dom.el( "p" , { class: "small text-body-secondary mt-2 mb-0" , text: I18n.get( "group.help" ) } ) );
  },

  select( options , current , onChange , label ) {
    const select = Dom.el( "select" , { class: "form-select form-select-sm" , attrs: { "aria-label": label } } );
    options.forEach( ( option ) => {
      const node = Dom.el( "option" , { text: option[ 1 ] , attrs: { value: option[ 0 ] } } );
      if ( option[ 0 ] === current ) node.selected = true;
      select.appendChild( node );
    } );
    select.addEventListener( "change" , () => onChange( select.value ) );
    select.addEventListener( "click" , ( event ) => event.stopPropagation() );
    return select;
  },

  dirButton( key , dir , onFlip ) {
    return Dom.el( "button" , {
      class: "btn btn-sm btn-outline-secondary text-nowrap",
      attrs: { type: "button" , title: I18n.get( "sort.flip" ) },
      children: [ Card.icon( dir === "desc" ? "sort-down" : "sort-up" ) , Dom.el( "span" , { text: " " + this.dirWord( key , dir ) } ) ],
      on: { click: ( event ) => { event.stopPropagation(); onFlip(); } },
    } );
  },

  stepRow( step , index , query , change ) {
    const row = Dom.el( "div" , { class: "sort-row" } );
    row.appendChild( Dom.el( "span" , { class: "sort-row-label small text-body-secondary" , text: I18n.get( index === 0 ? "sort.by" : "sort.then_by" ) } ) );
    row.appendChild( this.select(
      this.keys().map( ( key ) => [ key , I18n.get( "sort.key_" + key ) ] ),
      step.key,
      ( value ) => {
        const next = Query.clone( query );
        next.sort[ index ] = { key: value , dir: next.sort[ index ].dir };
        change( next );
      },
      I18n.get( index === 0 ? "sort.by" : "sort.then_by" ),
    ) );
    if ( step.key !== "random" ) {
      row.appendChild( this.dirButton( step.key , step.dir , () => {
        const next = Query.clone( query );
        next.sort[ index ].dir = step.dir === "desc" ? "asc" : "desc";
        change( next );
      } ) );
    }
    if ( index > 0 ) {
      row.appendChild( Dom.el( "button" , {
        class: "btn btn-sm btn-outline-danger",
        attrs: { type: "button" , "aria-label": I18n.get( "sort.remove" ) , title: I18n.get( "sort.remove" ) },
        children: [ Card.icon( "x-lg" ) ],
        on: { click: ( event ) => {
          event.stopPropagation();
          const next = Query.clone( query );
          next.sort.splice( index , 1 );
          change( next );
        } },
      } ) );
    }
    return row;
  },

  groupRow( query , change ) {
    const row = Dom.el( "div" , { class: "sort-row" } );
    row.appendChild( this.select(
      Grouper.ORDER.map( ( by ) => [ by , I18n.get( "group.by_" + by ) ] ),
      query.group.by,
      ( value ) => {
        const next = Query.clone( query );
        next.group = { by: value , dir: next.group.dir };
        change( next );
      },
      I18n.get( "group.heading" ),
    ) );
    if ( query.group.by !== "none" ) {
      const key = { year: "year" , decade: "year" , added: "added" , watched: "watched" , letter: "title" , genre: "title" , type: "title" , cert: "title" }[ query.group.by ] || "imdb";
      row.appendChild( this.dirButton( key , query.group.dir , () => {
        const next = Query.clone( query );
        next.group.dir = query.group.dir === "desc" ? "asc" : "desc";
        change( next );
      } ) );
    }
    return row;
  },
};
