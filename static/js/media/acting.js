// "Acting for": an admin -- or a user an admin gave "Can use Showing" -- can look at and change someone else's queue,
// ratings and hearts -- one person keeping the household's lists tidy. The
// picker on the Account screen sets whose state every personal call is about (Api.subject,
// sent as ?user=<id>); the server refuses anyone without the grant. An admin
// can also say whose lists a user starts on (me.default_subject), which
// start() sets before the first library load. While it is
// set to someone else, the picker on the Account screen is highlighted.
//
// Card layout, filters and saved views stay the admin's own: only the state
// on the titles is the other person's. Undo history is cleared on a switch,
// so Ctrl+Z can never undo something into the wrong person's list.
const Acting = {
  me: null,

  start( me ) {
    this.me = me;
    if ( me.can_show_others && me.default_subject != null && me.default_subject !== me.id ) Api.subject = me.default_subject;
  },

  init( me ) {
    this.me = me;
    if ( !me.can_show_others ) return;
    const select = Dom.get( "acting-select" );
    Dom.show( Dom.get( "acting" ) , true );
    this.fill( select );
    select.addEventListener( "change" , () => this.switchTo( Number( select.value ) ) );
    Library.on( ( change ) => { if ( change.kind === "load" ) this.fill( select ); } );
  },

  fill( select ) {
    const current = Library.subject != null ? Library.subject : this.me.id;
    Dom.clear( select );
    ( Library.people.length ? Library.people : [ { id: this.me.id , display_name: this.me.display_name } ] ).forEach( ( person ) => {
      const label = person.id === this.me.id ? I18n.fill( "acting.me" , { name: person.display_name } ) : person.display_name;
      const option = Dom.el( "option" , { text: label , attrs: { value: String( person.id ) } } );
      if ( person.id === current ) option.selected = true;
      select.appendChild( option );
    } );
    document.documentElement.classList.toggle( "acting-for-other" , current !== this.me.id );
  },

  async switchTo( userId ) {
    Api.subject = userId === this.me.id ? null : userId;
    Undo.clear();
    await Library.load();
    const person = Library.people.find( ( entry ) => entry.id === userId );
    if ( userId !== this.me.id && person ) Dom.toast( I18n.fill( "acting.now" , { name: person.display_name } ) , "ok" );
  },
};
