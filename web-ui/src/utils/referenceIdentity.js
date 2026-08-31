const present = value => value != null && String(value) !== ''

export function referenceRowIdentity(reference, fallbackPosition = -1) {
  if (present(reference?.ref_uid)) return `uid:${String(reference.ref_uid)}`
  if (present(reference?.id)) return `id:${String(reference.id)}`

  // Legacy live results may briefly arrive before the backend-added UID. Add
  // title to the citation number so duplicate numbering does not share busy or
  // correction state while that transition is in progress.
  if (present(reference?.index)) {
    const title = String(reference?.title || '').trim().toLocaleLowerCase()
    return `legacy-index:${String(reference.index)}:${title}:${fallbackPosition}`
  }
  return `pos:${fallbackPosition}`
}

export function toApiReferenceId(reference, fallbackPosition = -1) {
  if (present(reference?.ref_uid)) return `uid:${String(reference.ref_uid)}`
  if (present(reference?.id)) return `id:${String(reference.id)}`
  if (present(reference?.index)) return `index:${String(reference.index)}`
  return `pos:${String(fallbackPosition)}`
}

export function referenceMatchesIdentity(reference, position, identity) {
  const key = String(identity || '')
  if (key.startsWith('uid:')) return String(reference?.ref_uid || '') === key.slice(4)
  if (key.startsWith('id:')) return String(reference?.id || '') === key.slice(3)
  if (key.startsWith('pos:')) return String(position) === key.slice(4)
  if (key.startsWith('legacy-index:')) {
    return referenceRowIdentity(reference, position) === key
  }
  // Compatibility for state created before typed identities were introduced.
  return String(reference?.ref_uid || '') === key || String(reference?.id || '') === key
}

