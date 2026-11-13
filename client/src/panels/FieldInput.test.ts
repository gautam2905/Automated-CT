import { describe, expect, test } from 'vitest'
import { formatFieldNumber } from './FieldInput'

describe('formatFieldNumber', () => {
  test('millimetres are whole numbers unless the field steps in fractions', () => {
    expect(formatFieldNumber(476.2340425531, 'mm')).toBe('476')
    expect(formatFieldNumber(476.2340425531, 'mm', 1)).toBe('476')
    expect(formatFieldNumber(1.5, 'mm', 0.5)).toBe('1.5')
  })
  test('centimetres and kilograms show one decimal, other numbers at most two', () => {
    expect(formatFieldNumber(176.38297872340428, 'cm')).toBe('176.4')
    expect(formatFieldNumber(69.18467952127685, 'kg')).toBe('69.2')
    expect(formatFieldNumber(0.8, null)).toBe('0.8')
    expect(formatFieldNumber(0.123456, 's')).toBe('0.12')
  })
})
