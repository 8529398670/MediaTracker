// The readable API and MCP references: /docs/api renders config/api.md and
// /docs/mcp renders config/mcp.md, fetched from GET /api/api.md or
// /api/mcp.md (signed in). The cards on Account link here when app.repo is
// not set; with it, they link to the repository's own rendering instead.
//
// The files are written by scripts/api_docs.sh in GitHub's flavour: anchors
// are GitHub heading slugs, and the two files link to each other as api.md#x
// and mcp.md#x. Both are rebuilt here so every link works on this page.
const DocsPage = {
  pages: {
    api: { file: "/api/api.md" , title: "docs.api_title" },
    mcp: { file: "/api/mcp.md" , title: "docs.mcp_title" },
  },

  async init() {
    try {
      await I18n.load();
      I18n.apply();
    } catch ( error ) {
      return;
    }
    const name = window.location.pathname.replace( /\/+$/ , "" ).split( "/" ).pop();
    const page = this.pages[ name ];
    const status = Dom.get( "docs-status" );
    if ( !page ) {
      status.textContent = I18n.get( "docs.failed" );
      return;
    }
    const title = I18n.get( page.title );
    document.title = title;
    Dom.get( "docs-title" ).textContent = title;

    let text;
    try {
      const response = await fetch( page.file , { credentials: "same-origin" } );
      if ( !response.ok ) throw new Error( String( response.status ) );
      text = await response.text();
    } catch ( error ) {
      status.textContent = I18n.get( "docs.failed" );
      status.classList.add( "alert" , "alert-danger" );
      return;
    }
    this.render( text );
    status.remove();
    // The fragment in the address points at a heading that did not exist yet.
    if ( window.location.hash ) {
      const target = document.getElementById( decodeURIComponent( window.location.hash.slice( 1 ) ) );
      if ( target ) target.scrollIntoView();
    }
  },

  render( text ) {
    const root = Dom.get( "docs-root" );
    // Generated from the code, but sanitised all the same: nothing here is
    // assigned through innerHTML.
    const fragment = DOMPurify.sanitize( marked.parse( text , { gfm: true } ) , { RETURN_DOM_FRAGMENT: true } );
    root.appendChild( fragment );

    // GitHub's heading anchors: lower case, punctuation dropped, spaces to
    // hyphens, and -1, -2 ... on repeats.
    const seen = {};
    Dom.all( "h1, h2, h3, h4, h5, h6" , root ).forEach( function ( heading ) {
      let slug = heading.textContent.trim().toLowerCase()
        .replace( /[^\p{L}\p{N}\s_-]/gu , "" ).replace( /\s/g , "-" );
      if ( seen[ slug ] !== undefined ) {
        seen[ slug ] += 1;
        slug = slug + "-" + seen[ slug ];
      } else {
        seen[ slug ] = 0;
      }
      heading.id = slug;
    } );

    Dom.all( "a[href]" , root ).forEach( function ( link ) {
      const href = link.getAttribute( "href" );
      const other = /^(api|mcp)\.md(#.*)?$/.exec( href );
      if ( other ) {
        link.setAttribute( "href" , "/docs/" + other[ 1 ] + ( other[ 2 ] || "" ) );
      } else if ( /^https?:/i.test( href ) ) {
        link.setAttribute( "target" , "_blank" );
        link.setAttribute( "rel" , "noopener noreferrer" );
      }
    } );

    // Bootstrap tables, each scrolling sideways on its own on a phone.
    Dom.all( "table" , root ).forEach( function ( table ) {
      table.classList.add( "table" , "table-sm" , "table-striped" , "table-bordered" , "align-top" );
      const wrap = Dom.el( "div" , { class: "table-responsive" } );
      table.parentNode.insertBefore( wrap , table );
      wrap.appendChild( table );
    } );
  },
};

DocsPage.init();
