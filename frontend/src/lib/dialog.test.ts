import { expect, it, vi } from 'vitest'
import { isDialogBackdrop } from './dialog'

it('recognizes clicks outside the dialog without treating padding or content as the backdrop', () => {
  const dialog = document.createElement('dialog')
  vi.spyOn(dialog, 'getBoundingClientRect').mockReturnValue({
    left: 100,
    right: 500,
    top: 80,
    bottom: 400,
  } as DOMRect)
  let backdrop = false
  dialog.addEventListener('click', (event) => { backdrop = isDialogBackdrop(event) })
  const button = document.createElement('button')
  dialog.append(button)
  function click(x: number, y: number, target: EventTarget = dialog) {
    target.dispatchEvent(new MouseEvent('click', { clientX: x, clientY: y, bubbles: true }))
    return backdrop
  }
  expect(click(99, 200)).toBe(true)
  expect(click(501, 200)).toBe(true)
  expect(click(200, 79)).toBe(true)
  expect(click(200, 401)).toBe(true)
  expect(click(110, 90)).toBe(false)
  expect(click(99, 200, button)).toBe(false)
})
