import { describe, expect, it } from 'vitest'
import { wantsLowGraphics } from './graphicsMode'

describe('wantsLowGraphics', () => {
  it('is on when the address carries lowgfx', () => {
    expect(wantsLowGraphics('?lowgfx')).toBe(true)
    expect(wantsLowGraphics('?a=1&lowgfx=1')).toBe(true)
  })
  it('is off otherwise', () => {
    expect(wantsLowGraphics('')).toBe(false)
    expect(wantsLowGraphics('?speed=20')).toBe(false)
  })
})
