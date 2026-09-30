/* Geometry only: no transaction text, amounts, account names or API calls.
 * Pass captureMobileLayout to Playwright page.evaluate or Safari's inspector.
 */
function captureMobileLayout() {
 const main = document.querySelector('main')
 const next = main && [...main.querySelectorAll('button')].find(button => button.textContent === 'Next')
 const footer = next?.parentElement
 const describe = element => {
  if (!element) return null
  const rect = element.getBoundingClientRect(), style = getComputedStyle(element)
  return {
   tag: element.tagName.toLowerCase(), classes: element.getAttribute('class'),
   hidden: element.hidden, open: element.tagName === 'DETAILS' ? element.open : undefined,
   rect: { top: rect.top, bottom: rect.bottom, height: rect.height, width: rect.width, documentBottom: rect.bottom + scrollY },
   scrollHeight: element.scrollHeight, scrollWidth: element.scrollWidth, clientHeight: element.clientHeight, offsetHeight: element.offsetHeight,
   styles: Object.fromEntries(['display', 'position', 'height', 'minHeight', 'maxHeight', 'paddingTop', 'paddingBottom',
    'marginTop', 'marginBottom', 'bottom', 'flexGrow', 'flexShrink', 'overflowX', 'overflowY', 'visibility', 'transform', 'contain']
    .map(property => [property, style[property]])),
  }
 }
 const ancestors = []
 for (let element = footer; element; element = element.parentElement) ancestors.push(describe(element))
 const rows = [...(main?.querySelectorAll('article') || [])]
 const disclosures = [...(main?.querySelectorAll('details') || [])].map(element => ({
  disclosure: describe(element), body: describe(element.querySelector(':scope > div')),
 }))
 const beyondFooter = [], horizontalOverflow = []
 if (footer) {
  const footerBottom = footer.getBoundingClientRect().bottom
  for (const element of document.body.querySelectorAll('*')) {
   const rect = element.getBoundingClientRect(), style = getComputedStyle(element)
   if (rect.height > 0 && rect.bottom > footerBottom + 1 && style.display !== 'none') {
    beyondFooter.push(describe(element))
   }
   if (rect.height > 0 && rect.right > document.documentElement.clientWidth + 1 && style.display !== 'none') {
    horizontalOverflow.push(describe(element))
   }
  }
 }
 const viewport = window.visualViewport
 return {
  path: location.pathname, userAgent: navigator.userAgent, capturedAt: new Date().toISOString(),
  viewport: { width: innerWidth, height: innerHeight, outerHeight, scrollY, screenHeight: screen.height,
   coarsePointer: matchMedia('(pointer: coarse)').matches,
   visual: viewport && { width: viewport.width, height: viewport.height, offsetTop: viewport.offsetTop, pageTop: viewport.pageTop, scale: viewport.scale } },
  viewportMeta: document.querySelector('meta[name=viewport]')?.content,
  scriptFiles: [...document.scripts].map(script => script.getAttribute('src')).filter(Boolean),
  root: describe(document.documentElement), body: describe(document.body), app: describe(document.querySelector('.pft-app')),
  main: describe(main), list: describe(rows.at(-1)?.parentElement), rowCount: rows.length,
  firstRow: describe(rows[0]), lastRow: describe(rows.at(-1)), footer: describe(footer),
  toolbar: describe(document.querySelector('[data-bulk-toolbar]')), spacers: [...document.querySelectorAll('[data-bulk-spacer]')].map(describe),
  footerAncestors: ancestors, disclosures, beyondFooter, horizontalOverflow,
 }
}
module.exports = { captureMobileLayout }
