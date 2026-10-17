/* Duplicates: the same film under two names, found before it is added twice
 * and found when it already has been.
 *
 *     ./tests/ui.sh
 */
import './dom.mjs';

globalThis.fetch = async () => ({ ok: true, status: 200, text: async () => '{}' });

const {
  similarity, findMatches, findDuplicateGroups, mergedFields, normKey, warning, bestMatch,
  CERTAIN, LIKELY, SIMILAR, REMAKE,
} = await import('./dupes.js');

let failures = 0;
const check = (label, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) failures += 1;
  console.log(`${ok ? 'ok  ' : 'FAIL'}  ${label}`
    + (ok ? '' : `\n        got  ${JSON.stringify(got)}\n        want ${JSON.stringify(want)}`));
};

const t = (title, year = null, extra = {}) => ({ title, year, ...extra });
const tier = (a, b) => {
  const { score } = similarity(a, b);
  return score >= CERTAIN ? 'certain' : score >= LIKELY ? 'likely' : score >= SIMILAR ? 'similar'
    : score >= REMAKE ? 'remake' : 'no';
};

check('a subtitle on one side, same year',
  tier(t('Sunrise', 1927), t('Sunrise: A Song of Two Humans', 1927)), 'likely');
check('a year typed on the end, an article dropped',
  tier(t('The Weather Girl - 2009'), t('Weather Girl (2009)')), 'likely');
check('and with the years on the cards', tier(t('The Weather Girl - 2009', 2009), t('Weather Girl', 2009)), 'certain');
check('roman numerals and digits', tier(t('Godfather Part II', 1974), t('The Godfather Part 2', 1974)), 'certain');
check('curly and straight apostrophes', tier(t("Can't Buy Me Love", 1987), t('Can’t Buy Me Love', 1987)), 'certain');
check('the same IMDb title under two names',
  tier(t('Le Fabuleux Destin', 2001, { imdbId: 'tt0211915' }), t('Amélie', 2001, { imdbId: 'tt0211915' })), 'certain');
check('a typo', tier(t('The Shawshank Redemtion', 1994), t('The Shawshank Redemption', 1994)), 'similar');
check('words the other way round, nearly', tier(t('Ocean\'s Eleven', 2001), t('Oceans 11', 2001)), 'certain');

check('a sequel is not the film', tier(t('Rocky II', 1979), t('Rocky III', 1982)), 'no');
check('nor with the years agreeing', tier(t('Rocky II'), t('Rocky III')), 'no');
check('a sequel with no numeral first', tier(t('Rocky'), t('Rocky II')), 'no');
check('Alien is not Aliens', tier(t('Alien', 1979), t('Aliens', 1986)), 'no');
check('nor without years', tier(t('Alien'), t('Aliens')), 'no');
check('a remake is only mentioned', tier(t('Heat', 1995), t('Heat', 1986)), 'remake');
check('two different IMDb titles are two films',
  tier(t('Little Women', 2019, { imdbId: 'tt3281548' }), t('Little Women', 2019, { imdbId: 'tt0110367' })), 'no');
check('a subtitle needs the years', tier(t('Alien'), t('Alien: Resurrection', 1997)), 'no');
check('I, Robot keeps its I', normKey('I, Robot'), 'i robot');
check('Rocky V counts its V', normKey('Rocky V'), 'rocky 5');

const lib = [
  { id: 'a', title: 'Sunrise: A Song of Two Humans', year: 1927, type: 'movie', status: 'watched',
    watchedAt: '2025-03-04T00:00:00Z', tags: ['silent'], links: [], notes: '', rating: 9, heart: true },
  { id: 'b', title: 'Sunrise', year: 1927, type: 'tv', status: 'queue', watchedAt: null,
    tags: ['murnau'], links: [{ label: '', url: 'https://x' }], notes: 'from the list', rating: null,
    heart: false, poster: '/p.jpg' },
  { id: 'c', title: 'Heat', year: 1995, type: 'movie', status: 'queue', tags: [], links: [], notes: '' },
  { id: 'd', title: 'Heat', year: 1986, type: 'movie', status: 'queue', tags: [], links: [], notes: '' },
  { id: 'e', title: 'Rocky II', year: 1979, type: 'movie', status: 'queue', tags: [], links: [], notes: '' },
  { id: 'f', title: 'Rocky III', year: 1982, type: 'movie', status: 'queue', tags: [], links: [], notes: '' },
];

check('the exact one is the surer match', bestMatch(t('Sunrise', 1927), lib).item.id, 'b');
check('a warning names what you have and when you watched it',
  warning(bestMatch(t('Sunrise', 1927), lib, { except: new Set(['b']) })), 'Looks like one you have: Watched Mar 2025 · “Sunrise: A Song of Two Humans” (1927) · Movie');
check('finds across Movie and TV', findMatches(t('Sunrise: A Song of Two Humans', 1927), lib).map((m) => m.item.id), ['a', 'b']);
check('the groups are the real duplicates, not the remake or the sequel',
  findDuplicateGroups(lib).map((g) => g.items.map((i) => i.id).sort()), [['a', 'b']]);

const merged = mergedFields(lib[1], [lib[0]]);
check('merging into the unwatched one keeps the watch, the rating, the heart',
  [merged.status, merged.watchedAt, merged.rating, merged.heart], ['watched', '2025-03-04T00:00:00Z', 9, true]);
check('and every tag', merged.tags, ['murnau', 'silent']);

check('a bare year typed on the end counts as the year',
  findMatches({ title: 'sleepless in seattle 1993' }, [{ id: 's', title: 'Sleepless in Seattle', year: 1993 }])
    .map((m) => m.score), [CERTAIN]);
check('but a year that is the name still matches by name',
  findMatches({ title: 'Blade Runner 2049' }, [{ id: 'br', title: 'Blade Runner 2049', year: 2017 }])
    .map((m) => m.item.id), ['br']);

console.log(failures ? `\n${failures} failed` : '\nall passed');
process.exit(failures ? 1 : 0);
