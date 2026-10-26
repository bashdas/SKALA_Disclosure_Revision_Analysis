export function isDialogBackdrop(event: MouseEvent): boolean {
  if (event.target !== event.currentTarget || !(event.currentTarget instanceof HTMLDialogElement))
    return false
  const { left, right, top, bottom } = event.currentTarget.getBoundingClientRect()
  return (
    event.clientX < left || event.clientX > right || event.clientY < top || event.clientY > bottom
  )
}
