/** `?lowgfx` in the address draws the room without shadows or smoothing, for computers without a graphics card. */
export function wantsLowGraphics(search: string = window.location.search): boolean {
  return new URLSearchParams(search).has('lowgfx')
}
